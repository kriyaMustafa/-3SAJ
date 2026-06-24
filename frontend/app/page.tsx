"use client";

import { useState, useEffect, useRef } from "react";

// Types
type JobStatus = {
  status?: string;
  step: string;
  progress: number;
  eta?: string | null;
  detail?: string;
  elapsed_seconds?: number;
  error?: string;
};

type ManualTranslationSegment = {
  segment_id: number;
  original_text: string;
  ai_prompt: string;
  start_time: number;
  end_time: number;
  speaker_id: string;
  translated_text: string;
};

const initialStatus: JobStatus = {
  step: "Idle",
  progress: 0,
  eta: null,
  detail: "Select a video to begin",
};

export default function Home() {
  // Phase 1 State
  const [file, setFile] = useState<File | null>(null);
  const [voiceChoice, setVoiceChoice] = useState("male");
  const [videoType, setVideoType] = useState("anime");

  // Global State
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus>(initialStatus);
  const [isRunning, setIsRunning] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  // Phase 3 State
  const [manualSegments, setManualSegments] = useState<ManualTranslationSegment[]>([]);
  const [showManualReview, setShowManualReview] = useState(false);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);

  const getApiBase = () => {
    const hostname = typeof window !== "undefined" ? window.location.hostname : "localhost";
    return `http://${hostname}:8000`;
  };

  const isCompleted = job.step === "Completed" || job.status === "success";
  
  // Connect to WebSocket Events
  const connectToEvents = (projectId: string) => {
    if (eventSourceRef.current) {
      (eventSourceRef.current as any).close();
    }
    const hostname = typeof window !== "undefined" ? window.location.hostname : "localhost";
    const ws = new WebSocket(`ws://${hostname}:8000/ws/progress/${projectId}`);
    (eventSourceRef as any).current = ws;

    ws.onmessage = (event) => {
      try {
        const data: JobStatus = JSON.parse(event.data);
        setJob(data);

        if (data.status === "needs_manual_translation" || data.step === "Needs Manual Translation") {
          setShowManualReview(true);
        }

        if (data.step === "Completed" || data.status === "success") {
          setIsRunning(false);
          setDownloadUrl(`http://${hostname}:8000/api/downloads/${projectId}/video/mp4`);
          ws.close();
        } else if (data.step === "Failed") {
          setIsRunning(false);
          ws.close();
        }
      } catch (err) {
        console.error("Error parsing websocket stream:", err);
      }
    };
  };

  // Auto-fetch manual segments
  useEffect(() => {
    if (showManualReview && uploadedFilename && manualSegments.length === 0) {
      const fetchSegments = async () => {
        try {
          const apiBase = getApiBase();
          const res = await fetch(`${apiBase}/api/projects/${uploadedFilename}/segments/export-prompts`);
          if (!res.ok) throw new Error("Failed to fetch prompts");
          const data = await res.json();
          const segs = Array.isArray(data) ? data : (data.segments || []);
          setManualSegments(segs.map((s: any) => ({ ...s, translated_text: "" })));
        } catch (err) {
          console.error(err);
        }
      };
      fetchSegments();
    }
  }, [showManualReview, uploadedFilename, manualSegments.length]);

  const handleUpload = async () => {
    if (!file || isRunning) return;
    setIsRunning(true);
    setJob({ step: "Uploading", progress: 5, detail: "Uploading media..." });

    const formData = new FormData();
    formData.append("file", file);
    const apiBase = getApiBase();

    try {
      const uploadRes = await fetch(`${apiBase}/upload`, { method: "POST", body: formData });
      if (!uploadRes.ok) throw new Error("Upload failed");
      const uploadData = await uploadRes.json();
      const filePath = uploadData.filename;

      const payload = {
        input_type: "local",
        input_source: filePath,
        source_language: "auto",
        target_language: "km",
        genre_mode: "anime_recap",
        narrator_voice: voiceChoice,
        manual_review: true
      };

      const processRes = await fetch(`${apiBase}/api/projects`, { 
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!processRes.ok) throw new Error("Processing start failed");
      
      const processData = await processRes.json();
      const projectId = processData.project_id;
      setUploadedFilename(projectId);

      connectToEvents(projectId);
    } catch (err) {
      setIsRunning(false);
      setJob({ step: "Failed", progress: 0, detail: String(err) });
    }
  };

  const handleCopyPrompt = async (id: number, prompt: string) => {
    await navigator.clipboard.writeText(prompt);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handlePasteTranslate = async (id: number) => {
    try {
      const text = await navigator.clipboard.readText();
      setManualSegments((prev) =>
        prev.map((seg) => (seg.segment_id === id ? { ...seg, translated_text: text } : seg))
      );
    } catch (err) {
      alert("Failed to read clipboard");
    }
  };

  const handleTextChange = (id: number, val: string) => {
    setManualSegments((prev) =>
      prev.map((seg) => (seg.segment_id === id ? { ...seg, translated_text: val } : seg))
    );
  };

  const handleSubmitReview = async () => {
    if (!uploadedFilename || submitBusy) return;
    setSubmitBusy(true);
    const apiBase = getApiBase();

    try {
      // Depending on the backend, it could be the normal review endpoint OR the batch-translate endpoint.
      // We will try batch-translate first.
      const payload = {
        translations: manualSegments.map((seg) => ({
          segment_id: seg.segment_id,
          translated_text: seg.translated_text,
        })),
      };

      const res = await fetch(`${apiBase}/api/projects/${uploadedFilename}/segments/batch-translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        // Fallback to normal submit_review if batch-translate is only for quota errors
        const textPayload = manualSegments.map(s => `[${s.segment_id}] [auto] ${s.translated_text}`).join("\n");
        const fbRes = await fetch(`${apiBase}/submit_review/${uploadedFilename}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ khmer_text: textPayload, segments: manualSegments.map(s => ({ index: s.segment_id, translated_text: s.translated_text, voice: "auto", emotion: "NEUTRAL" })) }),
        });
        if (!fbRes.ok) throw new Error("Failed to submit review");
      }

      setShowManualReview(false);
      setManualSegments([]);
      setJob((prev) => ({ ...prev, step: "Synthesizing", progress: 35, detail: "Rendering dubbed voices..." }));
      connectToEvents(uploadedFilename);
    } catch (err) {
      alert("Failed to submit translations");
    } finally {
      setSubmitBusy(false);
    }
  };

  const handleReset = async () => {
    if (uploadedFilename) {
      // Call backend to delete data to save space!
      try {
        await fetch(`${getApiBase()}/api/projects/${uploadedFilename}`, { method: "DELETE" });
      } catch (e) {}
    }
    setFile(null);
    setUploadedFilename(null);
    setJob(initialStatus);
    setIsRunning(false);
    setDownloadUrl(null);
    setShowManualReview(false);
    setManualSegments([]);
    if (eventSourceRef.current) eventSourceRef.current.close();
  };

  // Determine current phase
  let currentPhase = 1;
  if (isCompleted) currentPhase = 4;
  else if (showManualReview) currentPhase = 3;
  else if (isRunning) currentPhase = 2;

  // --- RENDERERS ---

  const renderPhase1 = () => (
    <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl">
        <h2 className="text-2xl font-bold text-white mb-6">1. Upload & Configure</h2>
        
        <div className="space-y-6">
          {/* File Picker */}
          <div>
            <label className="block text-sm font-semibold text-zinc-300 mb-2">Select Video to Translate</label>
            <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-white/20 rounded-2xl cursor-pointer bg-white/5 hover:bg-white/10 hover:border-emerald-400 transition-all duration-300">
              <div className="flex flex-col items-center justify-center pt-5 pb-6">
                <svg className="w-8 h-8 mb-3 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
                <p className="text-sm text-zinc-300"><span className="font-semibold">Click to upload</span> or drag and drop</p>
                {file && <p className="text-emerald-400 font-medium mt-2">{file.name}</p>}
              </div>
              <input type="file" className="hidden" accept="video/*" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Voice Choice */}
            <div>
              <label className="block text-sm font-semibold text-zinc-300 mb-2">Choose Voice</label>
              <div className="flex bg-black/40 p-1 rounded-xl">
                <button onClick={() => setVoiceChoice("male")} className={`flex-1 py-2 rounded-lg text-sm font-bold transition-all ${voiceChoice === "male" ? "bg-emerald-500 text-black shadow-lg" : "text-zinc-400 hover:text-white"}`}>Male</button>
                <button onClick={() => setVoiceChoice("female")} className={`flex-1 py-2 rounded-lg text-sm font-bold transition-all ${voiceChoice === "female" ? "bg-emerald-500 text-black shadow-lg" : "text-zinc-400 hover:text-white"}`}>Female</button>
              </div>
            </div>

            {/* Video Type */}
            <div>
              <label className="block text-sm font-semibold text-zinc-300 mb-2">Video Type</label>
              <select disabled className="w-full h-[40px] rounded-xl border border-white/10 bg-black/40 px-3 text-sm text-zinc-300 opacity-70">
                <option value="anime">Anime (Locked)</option>
              </select>
            </div>
          </div>

          <button
            onClick={handleUpload}
            disabled={!file}
            className="w-full mt-4 rounded-2xl bg-gradient-to-r from-emerald-500 to-cyan-500 py-4 text-base font-extrabold text-black shadow-[0_0_20px_rgba(16,185,129,0.3)] transition-all hover:scale-[1.02] disabled:opacity-50 disabled:hover:scale-100"
          >
            Start Translation Process
          </button>
        </div>
      </div>
    </div>
  );

  const renderPhase2 = () => (
    <div className="flex flex-col items-center justify-center py-20 animate-in zoom-in-95 duration-700">
      <div className="relative w-64 h-64 flex items-center justify-center">
        <svg className="absolute w-full h-full animate-spin-slow" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="45" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="4" />
          <circle cx="50" cy="50" r="45" fill="none" stroke="url(#gradient)" strokeWidth="4" strokeDasharray="283" strokeDashoffset={283 - (283 * job.progress) / 100} className="transition-all duration-500" />
          <defs>
            <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#10b981" />
              <stop offset="100%" stopColor="#06b6d4" />
            </linearGradient>
          </defs>
        </svg>
        <div className="text-center">
          <h3 className="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-400">{job.progress}%</h3>
        </div>
      </div>
      
      <h2 className="text-2xl font-bold text-white mt-8 mb-2">{job.step}</h2>
      <p className="text-zinc-400 text-sm max-w-md text-center">{job.detail}</p>
      
      <div className="flex gap-8 mt-8 border border-white/10 bg-white/5 rounded-2xl px-8 py-4 backdrop-blur-md">
        <div className="text-center">
          <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Time Remaining</p>
          <p className="text-lg font-semibold text-emerald-400">{job.eta || "Calculating..."}</p>
        </div>
        <div className="w-px bg-white/10"></div>
        <div className="text-center">
          <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Elapsed</p>
          <p className="text-lg font-semibold text-zinc-300">{job.elapsed_seconds ? `${job.elapsed_seconds}s` : "0s"}</p>
        </div>
      </div>
    </div>
  );

  const renderPhase3 = () => (
    <div className="flex flex-col gap-6 animate-in fade-in duration-700">
      <div className="rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h2 className="text-2xl font-bold text-white mb-2">Translate & Review</h2>
            <p className="text-sm text-zinc-400">Copy the professional AI prompt, paste it into an AI tool, and paste the result back here.</p>
          </div>
          <button onClick={handleSubmitReview} disabled={submitBusy} className="rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 px-6 py-3 text-sm font-bold text-black shadow-lg transition-all hover:scale-105 disabled:opacity-50">
            {submitBusy ? "Processing..." : "Next Part / Submit"}
          </button>
        </div>

        <div className="space-y-6 max-h-[60vh] overflow-y-auto pr-2 custom-scrollbar">
          {manualSegments.map((seg, i) => (
            <div key={seg.segment_id} className="rounded-2xl border border-white/10 bg-black/40 p-5 group transition-colors hover:border-emerald-500/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-bold text-emerald-400 uppercase tracking-wider bg-emerald-500/10 px-2 py-1 rounded-md">Segment #{i + 1}</span>
                <button onClick={() => handleCopyPrompt(seg.segment_id, seg.ai_prompt)} className="text-xs font-semibold text-zinc-300 bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded-lg flex items-center gap-2 transition-colors">
                  {copiedId === seg.segment_id ? "Copied!" : "Copy Professional Prompt"}
                </button>
              </div>
              
              <div className="mb-4">
                <p className="text-xs text-zinc-500 mb-1">Text Detail (Original):</p>
                <p className="text-sm text-zinc-300 bg-white/5 p-3 rounded-xl border border-white/5">"{seg.original_text}"</p>
              </div>

              <div>
                <div className="flex justify-between items-center mb-1">
                  <p className="text-xs text-zinc-500">Translated Result:</p>
                  <button onClick={() => handlePasteTranslate(seg.segment_id)} className="text-xs text-emerald-400 hover:text-emerald-300 font-medium">Paste from clipboard</button>
                </div>
                <textarea
                  value={seg.translated_text}
                  onChange={(e) => handleTextChange(seg.segment_id, e.target.value)}
                  placeholder="Paste the translated text here..."
                  className="w-full min-h-[80px] rounded-xl border border-white/10 bg-black/50 p-3 text-sm text-white focus:border-emerald-500 outline-none transition-colors"
                />
              </div>
            </div>
          ))}
          {manualSegments.length === 0 && <p className="text-center text-zinc-500 py-10">Loading segments...</p>}
        </div>
      </div>
    </div>
  );

  const renderPhase4 = () => (
    <div className="flex flex-col items-center justify-center py-20 animate-in slide-in-from-bottom-8 duration-700">
      <div className="w-24 h-24 bg-emerald-500/20 rounded-full flex items-center justify-center mb-6 border border-emerald-500/50">
        <svg className="w-12 h-12 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
      </div>
      <h2 className="text-3xl font-extrabold text-white mb-4">Translation Complete!</h2>
      <p className="text-zinc-400 mb-8 text-center max-w-md">Your anime video has been successfully translated and dubbed with your chosen voice.</p>
      
      <div className="flex flex-col gap-4 w-full max-w-sm">
        {downloadUrl && (
          <a href={downloadUrl} download className="w-full block text-center rounded-2xl bg-gradient-to-r from-emerald-500 to-cyan-500 py-4 text-sm font-bold text-black shadow-lg hover:shadow-emerald-500/25 transition-all hover:-translate-y-1">
            Download Final Video
          </a>
        )}
        <button onClick={handleReset} className="w-full rounded-2xl border border-red-500/30 bg-red-500/10 py-4 text-sm font-bold text-red-400 transition-all hover:bg-red-500/20">
          Start New Translation (Deletes Old Data)
        </button>
      </div>
    </div>
  );

  return (
    <main className="min-h-screen bg-[#0a0a0a] text-zinc-100 font-sans selection:bg-emerald-500/30">
      {/* Cool Background Gradient */}
      <div className="fixed inset-0 z-0 pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-emerald-600/20 blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-cyan-600/20 blur-[120px]" />
      </div>

      <div className="relative z-10 mx-auto w-full max-w-4xl px-6 py-12">
        <header className="mb-12 text-center">
          <h1 className="text-4xl font-black tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white to-zinc-500 mb-2">Anime Dub Studio</h1>
          <p className="text-sm font-medium text-emerald-400/80 tracking-widest uppercase">Professional AI Pipeline</p>
        </header>

        {currentPhase === 1 && renderPhase1()}
        {currentPhase === 2 && renderPhase2()}
        {currentPhase === 3 && renderPhase3()}
        {currentPhase === 4 && renderPhase4()}
      </div>
    </main>
  );
}
