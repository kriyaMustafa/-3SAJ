"use client";

import { useState, useEffect, useRef } from "react";

type JobStatus = {
  status?: string;
  step: string;
  progress: number;
  eta?: string | null;
  detail?: string;
  elapsed_seconds?: number;
  error?: string;
  message?: string;
  traceback?: string;
  review_text?: string;
  result?: {
    whisper_runtime?: {
      device?: string;
      compute_type?: string;
    };
    background_mode?: string;
    voice_cast?: string;
    pipeline_mode?: string;
    voice_tone?: string;
    translated_video?: string;
    execution_log?: string;
    total_video_duration?: number;
    speakers_detected?: number;
    review_segments?: ReviewSegment[];
  };
  review_segments?: ReviewSegment[];
};

type ReviewSegment = {
  index: number;
  start: number;
  end: number;
  source_text: string;
  translated_text: string;
  voice: string;
  speaker?: string;
  emotion?: string;
  confidence?: number;
};

const initialStatus: JobStatus = {
  step: "Idle",
  progress: 0,
  eta: null,
  detail: "Select a video to begin",
};

const voiceOptions = [
  { id: "auto", label: "Auto" },
  { id: "male", label: "Male" },
  { id: "female", label: "Female" },
  { id: "kid", label: "Kid" },
] as const;

const emotionOptions = [
  { id: "NEUTRAL", label: "Neutral" },
  { id: "HAPPY", label: "Happy" },
  { id: "SAD", label: "Sad" },
  { id: "ANGRY", label: "Angry" },
  { id: "EXCITED", label: "Excited" },
  { id: "WHISPER", label: "Whisper" },
] as const;

const formatTime = (seconds: number) => {
  const safe = Math.max(0, Number(seconds) || 0);
  const whole = Math.floor(safe);
  const minutes = Math.floor(whole / 60);
  const secs = whole % 60;
  const tenths = Math.floor((safe - whole) * 10);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${tenths}`;
};

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus>(initialStatus);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  // Configuration settings
  const [voiceCast, setVoiceCast] = useState("auto");
  const [manualReview, setManualReview] = useState(true);
  const [enableBackgroundSound, setEnableBackgroundSound] = useState(true);
  const [translationStyle, setTranslationStyle] = useState("cinematic");
  const [pipelineMode, setPipelineMode] = useState("balanced");
  const [sourceLang, setSourceLang] = useState("auto");
  const [targetLang, setTargetLang] = useState("km");
  const [voiceTone, setVoiceTone] = useState("auto");

  // State for reviews
  const [reviewSegments, setReviewSegments] = useState<ReviewSegment[]>([]);
  const [pastedKhmer, setPastedKhmer] = useState("");
  const [submitBusy, setSubmitBusy] = useState(false);
  const [playingIndex, setPlayingIndex] = useState<number | null>(null);
  const [bulkVoice, setBulkVoice] = useState("auto");

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Computations
  const isAwaitingReview = job.status === "awaiting_review" || job.step === "Awaiting Review";
  const isCompleted = job.step === "Completed" || job.status === "success";

  const getApiBase = () => {
    const hostname = typeof window !== "undefined" ? window.location.hostname : "localhost";
    return `http://${hostname}:8000`;
  };

  const connectToEvents = (filename: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const apiBase = getApiBase();
    const eventSource = new EventSource(`${apiBase}/events/${filename}`);
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const data: JobStatus = JSON.parse(event.data);
        setJob(data);

        const segSource = data.review_segments || data.result?.review_segments;
        if (Array.isArray(segSource) && segSource.length > 0) {
          setReviewSegments(segSource);
        }

        if (data.step === "Completed" || data.status === "success") {
          setIsRunning(false);
          setDownloadUrl(`${apiBase}/download/${filename}`);
          eventSource.close();
          localStorage.removeItem("current_processing_file");
        } else if (data.step === "Failed") {
          setIsRunning(false);
          eventSource.close();
          localStorage.removeItem("current_processing_file");
        }
      } catch (err) {
        console.error("Error parsing event stream:", err);
      }
    };

    eventSource.onerror = () => {
      console.warn("EventSource disconnected.");
    };
  };

  useEffect(() => {
    const saved = localStorage.getItem("current_processing_file");
    if (saved) {
      setUploadedFilename(saved);
      setIsRunning(true);
      connectToEvents(saved);
    }
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const handleUpload = async () => {
    if (!file || isRunning) return;

    setIsRunning(true);
    setDownloadUrl(null);
    setReviewSegments([]);
    setJob({ step: "Uploading", progress: 2, eta: null, detail: "Uploading media to server" });

    const formData = new FormData();
    formData.append("file", file);

    const apiBase = getApiBase();

    try {
      const uploadRes = await fetch(`${apiBase}/upload`, {
        method: "POST",
        body: formData,
      });
      if (!uploadRes.ok) throw new Error("Upload failed");
      const uploadData = await uploadRes.json();

      const filename = uploadData.filename;
      setUploadedFilename(filename);
      localStorage.setItem("current_processing_file", filename);

      setJob({ step: "Queued", progress: 5, eta: null, detail: "Initializing translation pipeline" });

      const queryParams = new URLSearchParams({
        voice_cast: voiceCast,
        enable_background_sound: String(enableBackgroundSound),
        translation_style: translationStyle,
        manual_review: String(manualReview),
        source_lang: sourceLang,
        target_lang: targetLang,
        pipeline_mode: pipelineMode,
        voice_tone: voiceTone,
      });

      const processRes = await fetch(`${apiBase}/process/${filename}?${queryParams.toString()}`, {
        method: "POST",
      });
      if (!processRes.ok) throw new Error("Could not start processing");

      connectToEvents(filename);
    } catch (error) {
      setIsRunning(false);
      const errMsg = error instanceof Error ? error.message : String(error);
      setJob({
        step: "Failed",
        progress: 0,
        eta: null,
        detail: errMsg,
      });
    }
  };

  const updateReviewSegment = (index: number, key: keyof ReviewSegment, value: string) => {
    setReviewSegments((prev) =>
      prev.map((segment) =>
        segment.index === index ? { ...segment, [key]: value } : segment
      )
    );
  };

  const playPreview = async (index: number, text: string, voice: string) => {
    if (!text || !text.trim()) return;

    if (playingIndex === index) {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setPlayingIndex(null);
      return;
    }

    let actualVoice = voice;
    if (actualVoice === "auto") {
      const segment = reviewSegments.find((s) => s.index === index);
      const spk = (segment?.speaker || "").toLowerCase();
      if (spk.includes("male")) {
        actualVoice = "male";
      } else if (spk.includes("kid")) {
        actualVoice = "kid";
      } else {
        actualVoice = "female";
      }
    }

    try {
      setPlayingIndex(index);
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      const queryParams = new URLSearchParams({
        text,
        voice: actualVoice,
        target_lang: targetLang || "km",
        voice_tone: "auto",
        translation_style: translationStyle || "cinematic",
      });

      const apiBase = getApiBase();
      const res = await fetch(`${apiBase}/preview_tts?${queryParams.toString()}`);
      if (!res.ok) throw new Error("Failed to generate preview audio");

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;

      audio.onended = () => {
        setPlayingIndex(null);
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        setPlayingIndex(null);
        URL.revokeObjectURL(url);
        alert("Error playing preview audio");
      };

      await audio.play();
    } catch (err) {
      console.error(err);
      const errMsg = err instanceof Error ? err.message : String(err);
      alert(errMsg || "Could not play preview");
      setPlayingIndex(null);
    }
  };

  const handleApplyVoiceToAll = (voice: string) => {
    setReviewSegments((prev) => prev.map((segment) => ({ ...segment, voice })));
  };

  const handleParseClipboard = () => {
    const text = pastedKhmer.replace(/\r\n/g, "\n").trim();
    if (!text) return;

    const matches = [...text.matchAll(/\[(\d+)\]\s*(?:\[(auto|male|female|kid)\])?\s*([\s\S]*?)(?=(?:\n\s*\[\d+\])|$)/gi)];
    if (matches.length > 0) {
      setReviewSegments((prev) =>
        prev.map((seg) => {
          const match = matches.find((m) => Number(m[1]) === seg.index);
          if (match) {
            return {
              ...seg,
              voice: match[2] || seg.voice || "auto",
              translated_text: match[3].trim(),
            };
          }
          return seg;
        })
      );
      setPastedKhmer("");
      alert("Successfully parsed clipboard text and updated segments!");
    } else {
      alert("Could not parse. Target format example: [0] ជម្រាបសួរ, [1] [male] ស្វាគមន៍");
    }
  };

  const handleSubmitReview = async () => {
    if (!uploadedFilename || submitBusy) return;

    setSubmitBusy(true);
    const apiBase = getApiBase();

    try {
      const textPayload = reviewSegments
        .map((seg) => `[${seg.index}] [${seg.voice || "auto"}] ${seg.translated_text}`)
        .join("\n");

      const res = await fetch(`${apiBase}/submit_review/${uploadedFilename}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          khmer_text: textPayload,
          segments: reviewSegments.map((seg) => ({
            index: seg.index,
            translated_text: seg.translated_text,
            voice: seg.voice || "auto",
            emotion: seg.emotion || "NEUTRAL",
          })),
        }),
      });

      if (!res.ok) throw new Error("Failed to submit review");

      setReviewSegments([]);
      setJob((prev) => ({ ...prev, step: "Synthesizing", progress: 35, detail: "Rendering dubbed voices..." }));
      connectToEvents(uploadedFilename);
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      alert(errMsg || "Failed to submit manual review edits");
    } finally {
      setSubmitBusy(false);
    }
  };

  const handleResetWorkspace = () => {
    localStorage.removeItem("current_processing_file");
    setUploadedFilename(null);
    setFile(null);
    setDownloadUrl(null);
    setReviewSegments([]);
    setJob(initialStatus);
    setIsRunning(false);
  };

  const progress = Math.max(0, Math.min(job.progress || 0, 100));
  const canStart = Boolean(file) && !isRunning;

  const sourceVideoUrl = uploadedFilename ? `${apiBase}/media/source/${uploadedFilename}` : null;
  const finalVideoUrl = uploadedFilename ? `${apiBase}/media/final/${uploadedFilename}` : null;
  const previewVideoUrl = isCompleted ? finalVideoUrl : sourceVideoUrl;

  const reviewBatchCount = reviewSegments.length;
  const totalBatchDuration = reviewSegments.reduce((sum, seg) => sum + Math.max(0, seg.end - seg.start), 0);

  return (
    <main className="min-h-screen text-zinc-100 font-sans leading-relaxed">
      <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-5 py-8">
        
        {/* Header */}
        <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-white/10 pb-5">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-emerald-400 to-sky-400 bg-clip-text text-transparent">
              AI Khmer Video Translator
            </h1>
            <p className="text-sm text-zinc-400 mt-1">
              High-fidelity translation, neural dubbed speakers, and precise timestamp syncing.
            </p>
          </div>
          {(uploadedFilename || isRunning) && (
            <button
              type="button"
              onClick={handleResetWorkspace}
              className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-2 text-xs font-semibold text-red-400 hover:bg-red-500/20 transition-all duration-300"
            >
              Reset Session
            </button>
          )}
        </header>

        {/* Dashboard Grid */}
        <section className="grid gap-6 lg:grid-cols-[380px_1fr]">
          
          {/* Left Column: Settings and Audio/Video Player */}
          <div className="flex flex-col gap-6">
            
            {/* Upload/Config Card */}
            <div className="rounded-[28px] border border-white/10 bg-white/5 p-5 shadow-2xl backdrop-blur-md">
              <h2 className="text-lg font-bold text-zinc-100 flex items-center gap-2 mb-4">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5 text-emerald-400">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
                </svg>
                Upload & Pipeline
              </h2>

              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Video File</label>
                  <input
                    type="file"
                    accept="video/*"
                    disabled={isRunning}
                    onChange={(event) => setFile(event.target.files?.[0] || null)}
                    className="block w-full text-xs text-zinc-300 file:mr-3 file:rounded-xl file:border-0 file:bg-emerald-400 file:px-3 file:py-2.5 file:text-xs file:font-bold file:text-zinc-950 hover:file:bg-emerald-300 disabled:opacity-50"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">Source Language</label>
                    <select
                      value={sourceLang}
                      disabled={isRunning}
                      onChange={(event) => setSourceLang(event.target.value)}
                      className="w-full rounded-xl border border-white/10 bg-zinc-950 px-3 py-2.5 text-xs outline-none focus:border-emerald-400 disabled:opacity-50"
                    >
                      <option value="auto">Auto Detect</option>
                      <option value="en">English</option>
                      <option value="zh">Chinese</option>
                      <option value="ja">Japanese</option>
                      <option value="ko">Korean</option>
                      <option value="th">Thai</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">Target Language</label>
                    <select
                      value={targetLang}
                      disabled={isRunning}
                      onChange={(event) => setTargetLang(event.target.value)}
                      className="w-full rounded-xl border border-white/10 bg-zinc-950 px-3 py-2.5 text-xs outline-none focus:border-emerald-400 disabled:opacity-50"
                    >
                      <option value="km">Khmer</option>
                      <option value="en">English</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">Speaker Dub Model Routing</label>
                  <select
                    value={voiceCast}
                    disabled={isRunning}
                    onChange={(event) => setVoiceCast(event.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-zinc-950 px-3 py-2.5 text-xs outline-none focus:border-emerald-400 disabled:opacity-50"
                  >
                    <option value="auto">Auto Diarization (Male/Female/Kid)</option>
                    <option value="dual">Dual Cast (Male & Female)</option>
                    <option value="male">Male Only</option>
                    <option value="female">Female Only</option>
                    <option value="kid">Kid Only</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">Translation Style Style</label>
                  <select
                    value={translationStyle}
                    disabled={isRunning}
                    onChange={(event) => setTranslationStyle(event.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-zinc-950 px-3 py-2.5 text-xs outline-none focus:border-emerald-400 disabled:opacity-50"
                  >
                    <option value="cinematic">Legendary Storyteller (Poetic)</option>
                    <option value="drama">Emotional Screenplay (Drama)</option>
                    <option value="manga">Anime Recap Narrator (Fast Recaps)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">Processing Mode</label>
                  <select
                    value={pipelineMode}
                    disabled={isRunning}
                    onChange={(event) => setPipelineMode(event.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-zinc-950 px-3 py-2.5 text-xs outline-none focus:border-emerald-400 disabled:opacity-50"
                  >
                    <option value="fast">Fast (Lower latency, default values)</option>
                    <option value="balanced">Balanced (High quality audio overlays)</option>
                    <option value="rich">Rich (Advanced sidechain ducking + full DSP)</option>
                  </select>
                </div>

                <div className="flex flex-col gap-2 pt-2 border-t border-white/5">
                  <label className="flex items-center gap-2 text-xs font-medium text-zinc-300 cursor-pointer">
                    <input
                      type="checkbox"
                      disabled={isRunning}
                      checked={manualReview}
                      onChange={(e) => setManualReview(e.target.checked)}
                      className="rounded border-white/10 bg-zinc-950 text-emerald-400 focus:ring-emerald-400 w-4 h-4"
                    />
                    Enable Manual Quality Review
                  </label>
                  <label className="flex items-center gap-2 text-xs font-medium text-zinc-300 cursor-pointer">
                    <input
                      type="checkbox"
                      disabled={isRunning}
                      checked={enableBackgroundSound}
                      onChange={(e) => setEnableBackgroundSound(e.target.checked)}
                      className="rounded border-white/10 bg-zinc-950 text-emerald-400 focus:ring-emerald-400 w-4 h-4"
                    />
                    Retain Background Audio Bed
                  </label>
                </div>

                <button
                  type="button"
                  onClick={handleUpload}
                  disabled={!canStart}
                  className="w-full rounded-2xl bg-gradient-to-r from-emerald-400 to-sky-400 py-3.5 text-sm font-bold text-zinc-950 shadow-xl transition-all duration-300 hover:from-emerald-300 hover:to-sky-300 disabled:from-zinc-700 disabled:to-zinc-800 disabled:text-zinc-400 disabled:cursor-not-allowed"
                >
                  {isRunning ? "Running Pipeline..." : "Translate Video"}
                </button>
              </div>
            </div>

            {/* Video Player Card */}
            <div className="rounded-[28px] border border-white/10 bg-white/5 p-4 shadow-2xl backdrop-blur-md">
              <h3 className="text-sm font-semibold text-zinc-300 mb-3 flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4 text-sky-400">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 0 1 0 12.728M16.463 8.288a5.25 5.25 0 0 1 0 7.424M6.75 8.25l4.72-4.72a.75.75 0 0 1 1.28.53v15.88a.75.75 0 0 1-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.009 9.009 0 0 1 2.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75Z" />
                </svg>
                Media Preview player
              </h3>
              
              {previewVideoUrl ? (
                <div className="overflow-hidden rounded-2xl border border-white/10 bg-zinc-950">
                  <video
                    key={previewVideoUrl}
                    controls
                    className="w-full aspect-video"
                    src={previewVideoUrl}
                  />
                  <div className="p-3 bg-zinc-900/40 text-center text-xs text-zinc-400">
                    {isCompleted ? "🔴 Dubbed Khmer Output Preview" : "🔵 Raw Uploaded Source Preview"}
                  </div>
                </div>
              ) : (
                <div className="flex aspect-video items-center justify-center rounded-2xl border border-dashed border-white/10 bg-zinc-950/20 text-xs text-zinc-500 text-center p-6">
                  Player will load automatically once upload is completed
                </div>
              )}
            </div>

            {/* Status Card */}
            <div className="rounded-[28px] border border-white/10 bg-white/5 p-5 shadow-2xl backdrop-blur-md">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-widest text-zinc-400">Status</p>
                  <h3 className="text-xl font-bold mt-1 text-zinc-100">{job.step}</h3>
                </div>
                <div className="text-right text-xs text-zinc-400 space-y-1">
                  <p>ETA: {job.eta || "--"}</p>
                  <p>Elapsed: {job.elapsed_seconds ? `${job.elapsed_seconds}s` : "0s"}</p>
                </div>
              </div>

              <div className="mt-4 h-2.5 w-full overflow-hidden rounded-full bg-zinc-950 border border-white/5">
                <div
                  className="h-full bg-gradient-to-r from-emerald-400 to-sky-400 transition-all duration-500 rounded-full"
                  style={{ width: `${progress}%` }}
                />
              </div>
              
              <div className="mt-2.5 flex justify-between text-xs text-zinc-400">
                <span className="line-clamp-1">{job.detail || "Ready to upload"}</span>
                <span className="font-semibold text-emerald-400">{progress}%</span>
              </div>

              {job.error && (
                <div className="mt-4 rounded-xl border border-red-500/20 bg-red-950/30 p-3.5 text-xs text-red-200 leading-relaxed font-mono">
                  {job.error}
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Review Interface and Workspace */}
          <div className="flex flex-col gap-6">
            
            {/* Main Interactive Workspace Card */}
            <div className="rounded-[28px] border border-white/10 bg-white/5 p-5 shadow-2xl backdrop-blur-md flex-1 flex flex-col min-h-[480px]">
              
              {/* Workspace Header */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/10 pb-4 mb-4">
                <div>
                  <h2 className="text-lg font-bold text-zinc-100">Interactive Dubbing Workspace</h2>
                  <p className="text-xs text-zinc-400 mt-1">
                    {isAwaitingReview
                      ? `Quality Control: Dub script batch awaiting review (${reviewBatchCount} items)`
                      : isCompleted
                      ? "Dubbing completed! View final script below."
                      : "Workspace idle. Pipeline progress shows up here once transcribing is finished."}
                  </p>
                </div>
                
                {reviewSegments.length > 0 && (
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-zinc-900 border border-white/10 px-3 py-1 text-xs text-zinc-300">
                      {reviewBatchCount} segments ({formatTime(totalBatchDuration)})
                    </span>
                  </div>
                )}
              </div>

              {reviewSegments.length > 0 ? (
                <div className="flex flex-col gap-6 flex-1">
                  
                  {/* Bulk Actions Controls */}
                  {isAwaitingReview && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 rounded-2xl border border-white/10 bg-black/20 p-4">
                      
                      {/* Apply Bulk Voice */}
                      <div>
                        <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1.5">Apply voice style to all</label>
                        <div className="flex gap-2">
                          <select
                            value={bulkVoice}
                            onChange={(e) => setBulkVoice(e.target.value)}
                            className="h-10 rounded-xl border border-white/10 bg-zinc-950 px-3 text-xs outline-none focus:border-emerald-400"
                          >
                            {voiceOptions.map((opt) => (
                              <option key={opt.id} value={opt.id}>{opt.label}</option>
                            ))}
                          </select>
                          <button
                            type="button"
                            onClick={() => handleApplyVoiceToAll(bulkVoice)}
                            className="h-10 rounded-xl bg-sky-500 hover:bg-sky-400 px-4 text-xs font-bold text-white transition-all duration-300"
                          >
                            Apply All
                          </button>
                        </div>
                      </div>

                      {/* Import formatted transcriptions */}
                      <div>
                        <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1.5">Bulk Paste Transcript Translation</label>
                        <div className="flex gap-2">
                          <input
                            type="text"
                            placeholder="[0] translation here..."
                            value={pastedKhmer}
                            onChange={(e) => setPastedKhmer(e.target.value)}
                            className="h-10 flex-1 rounded-xl border border-white/10 bg-zinc-950 px-3 text-xs outline-none focus:border-emerald-400"
                          />
                          <button
                            type="button"
                            onClick={handleParseClipboard}
                            className="h-10 rounded-xl bg-emerald-500 hover:bg-emerald-400 px-4 text-xs font-bold text-zinc-950 transition-all duration-300"
                          >
                            Parse Text
                          </button>
                        </div>
                      </div>

                    </div>
                  )}

                  {/* List of segment cards */}
                  <div className="space-y-4 max-h-[64vh] overflow-y-auto pr-1.5 flex-1">
                    {reviewSegments.map((segment) => (
                      <div key={segment.index} className="rounded-2xl border border-white/10 bg-white/5 p-4 shadow-lg">
                        
                        {/* Segment Top Panel */}
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/5 pb-3">
                          <div className="flex items-center gap-3 text-xs font-semibold text-zinc-100">
                            <span className="rounded-full bg-emerald-400/10 border border-emerald-400/20 px-2.5 py-1 text-emerald-400">
                              #{segment.index}
                            </span>
                            <span className="font-mono text-zinc-400">
                              {formatTime(segment.start)} - {formatTime(segment.end)}
                            </span>
                            <span className="rounded-full bg-zinc-900 border border-white/10 px-2 py-0.5 text-zinc-400">
                              Speaker: {segment.speaker || "Auto"}
                            </span>
                          </div>

                          <div className="flex items-center gap-2">
                            {/* LIVE PREVIEW BUTTON */}
                            <button
                              type="button"
                              onClick={() => playPreview(segment.index, segment.translated_text, segment.voice || "auto")}
                              className={`flex h-9 items-center gap-1.5 rounded-xl border px-3 text-xs font-semibold uppercase tracking-[0.06em] transition-all duration-300 ${
                                playingIndex === segment.index
                                  ? "bg-amber-500/20 text-amber-400 border-amber-500/40"
                                  : "bg-white/5 text-zinc-300 border-white/10 hover:bg-white/10 hover:border-emerald-400"
                              }`}
                            >
                              {playingIndex === segment.index ? (
                                <>
                                  <span className="relative flex h-2 w-2">
                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                                    <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                                  </span>
                                  Stop Preview
                                </>
                              ) : (
                                <>
                                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5 text-emerald-400">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 0 1 0 12.728M16.463 8.288a5.25 5.25 0 0 1 0 7.424M6.75 8.25l4.72-4.72a.75.75 0 0 1 1.28.53v15.88a.75.75 0 0 1-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.009 9.009 0 0 1 2.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75Z" />
                                  </svg>
                                  Preview Voice
                                </>
                              )}
                            </button>

                            <select
                              value={segment.voice || "auto"}
                              disabled={!isAwaitingReview}
                              onChange={(e) => updateReviewSegment(segment.index, "voice", e.target.value)}
                              className="h-9 rounded-xl border border-white/10 bg-zinc-950 px-2 text-xs text-zinc-100 outline-none focus:border-emerald-400"
                            >
                              {voiceOptions.map((opt) => (
                                <option key={opt.id} value={opt.id}>
                                  {opt.label}
                                </option>
                              ))}
                            </select>

                            <select
                              value={segment.emotion || "NEUTRAL"}
                              disabled={!isAwaitingReview}
                              onChange={(e) => updateReviewSegment(segment.index, "emotion", e.target.value)}
                              className="h-9 rounded-xl border border-white/10 bg-zinc-950 px-2 text-xs text-zinc-100 outline-none focus:border-emerald-400"
                            >
                              {emotionOptions.map((opt) => (
                                <option key={opt.id} value={opt.id}>
                                  {opt.label}
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>

                        {/* Text editing fields */}
                        <div className="mt-3">
                          <textarea
                            value={segment.translated_text}
                            disabled={!isAwaitingReview}
                            onChange={(e) => updateReviewSegment(segment.index, "translated_text", e.target.value)}
                            className="w-full min-h-[72px] rounded-xl border border-white/10 bg-zinc-950 px-3 py-2 text-sm leading-6 text-zinc-100 outline-none transition focus:border-emerald-400 disabled:opacity-75"
                            placeholder="Provide translation"
                          />
                        </div>

                        <div className="mt-2 text-xs text-zinc-500 line-clamp-2">
                          Original: "{segment.source_text}"
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Render video execution submissions panel */}
                  {isAwaitingReview && (
                    <div className="pt-4 border-t border-white/10 flex justify-end">
                      <button
                        type="button"
                        onClick={handleSubmitReview}
                        disabled={submitBusy}
                        className="rounded-2xl bg-emerald-400 px-6 py-3 text-sm font-bold text-zinc-950 shadow-xl transition-all duration-300 hover:bg-emerald-300 disabled:opacity-50"
                      >
                        {submitBusy ? "Re-dubbing & rendering..." : "Finalize & Dub Translation"}
                      </button>
                    </div>
                  )}

                </div>
              ) : (
                <div className="flex flex-col items-center justify-center flex-1 text-center py-16">
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-12 h-12 text-zinc-600 mb-3 animate-pulse">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 0 1 0 12.728M16.463 8.288a5.25 5.25 0 0 1 0 7.424M6.75 8.25l4.72-4.72a.75.75 0 0 1 1.28.53v15.88a.75.75 0 0 1-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.009 9.009 0 0 1 2.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75Z" />
                  </svg>
                  <p className="text-sm font-semibold text-zinc-500">Workspace is empty</p>
                  <p className="text-xs text-zinc-600 mt-1 max-w-[280px]">
                    Once transcription matches, edit translations and live play speech cues here.
                  </p>
                </div>
              )}

            </div>

          </div>

        </section>

      </div>
    </main>
  );
}
