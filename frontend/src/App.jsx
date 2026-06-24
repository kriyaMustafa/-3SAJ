import { createSignal, createEffect, onCleanup, For, Show } from "solid-js";

export default function App() {
  const [file, setFile] = createSignal(null);
  const [voiceChoice, setVoiceChoice] = createSignal("male");
  const [ttsEngine, setTtsEngine] = createSignal("voxcpm2");
  const [enableSubtitles, setEnableSubtitles] = createSignal(true);
  
  const [projectId, setProjectId] = createSignal(null);
  const [job, setJob] = createSignal({ step: "Idle", progress: 0, detail: "Select a video to begin", eta: null });
  const [isRunning, setIsRunning] = createSignal(false);
  const [isCompleted, setIsCompleted] = createSignal(false);
  
  const [showManualReview, setShowManualReview] = createSignal(false);
  const [manualSegments, setManualSegments] = createSignal([]);
  const [submitBusy, setSubmitBusy] = createSignal(false);
  const [copiedId, setCopiedId] = createSignal(null);
  const [downloadUrl, setDownloadUrl] = createSignal(null);

  let wsRef = null;
  const hostname = window.location.hostname;
  const apiBase = `http://${hostname}:8000`;
  const wsBase = `ws://${hostname}:8000`;

  const startPolling = (id) => {
    if (wsRef) clearInterval(wsRef);
    
    wsRef = setInterval(async () => {
      try {
        const res = await fetch(`${apiBase}/api/projects/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        const p = data.project;
        
        setJob({
          step: p.status.charAt(0).toUpperCase() + p.status.slice(1),
          progress: data.progress_percentage || 0,
          detail: "Working...",
          eta: null
        });

        if (p.status === "needs_manual_translation") {
          setShowManualReview(true);
        }

        if (p.status === "completed" || data.progress_percentage >= 100) {
          setIsRunning(false);
          setIsCompleted(true);
          setDownloadUrl(`${apiBase}/api/downloads/${id}/video/mp4`);
          clearInterval(wsRef);
        } else if (p.status === "failed") {
          setIsRunning(false);
          clearInterval(wsRef);
        }
      } catch (err) {
        console.error(err);
      }
    }, 2000);
  };

  createEffect(() => {
    const savedId = localStorage.getItem("activeProjectId");
    if (savedId && !projectId() && !isRunning() && !isCompleted()) {
      setProjectId(savedId);
      setIsRunning(true);
      setJob({ step: "Reconnecting", progress: 0, detail: "Restoring active session...", eta: null });
      startPolling(savedId);
    }
  });

  createEffect(() => {
    if (showManualReview() && projectId() && manualSegments().length === 0) {
      fetch(`${apiBase}/api/projects/${projectId()}/segments/export-prompts`)
        .then(res => res.json())
        .then(data => {
          const segs = Array.isArray(data) ? data : (data.segments || []);
          setManualSegments(segs.map(s => ({ ...s, translated_text: "" })));
        })
        .catch(console.error);
    }
  });

  const handleUpload = async () => {
    if (!file() || isRunning()) return;
    setIsRunning(true);
    setJob({ step: "Uploading", progress: 5, detail: "Uploading media to server..." });

    try {
      const formData = new FormData();
      formData.append("file", file());
      
      const uploadRes = await fetch(`${apiBase}/upload`, { method: "POST", body: formData });
      if (!uploadRes.ok) throw new Error("Upload failed");
      const uploadData = await uploadRes.json();

      const payload = {
        input_type: "local",
        input_source: uploadData.filename,
        source_language: "auto",
        target_language: "km",
        genre_mode: "anime_recap",
        narrator_voice: voiceChoice(),
        tts_engine: ttsEngine(),
        enable_subtitles: enableSubtitles(),
        manual_review: true // Important to trigger review phase
      };

      const processRes = await fetch(`${apiBase}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!processRes.ok) throw new Error("Processing failed");
      
      const projData = await processRes.json();
      setProjectId(projData.project_id);
      localStorage.setItem("activeProjectId", projData.project_id);
      startPolling(projData.project_id);
      
    } catch (err) {
      setIsRunning(false);
      setJob({ step: "Failed", progress: 0, detail: err.message });
      alert("Error: " + err.message);
    }
  };

  const handleCopy = async (id, text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch (err) {
      alert("Copy failed");
    }
  };

  const handlePaste = async (id) => {
    try {
      const text = await navigator.clipboard.readText();
      setManualSegments(prev => prev.map(s => s.segment_id === id ? { ...s, translated_text: text } : s));
    } catch (err) {
      alert("Paste failed");
    }
  };

  const updateText = (id, val) => {
    setManualSegments(prev => prev.map(s => s.segment_id === id ? { ...s, translated_text: val } : s));
  };

  const handleCopyAll = async () => {
    const segs = manualSegments();
    if (!segs.length) return;

    let combinedPrompt = "You are a professional English-to-Khmer localization translator for video recaps.\n" +
      "Translate the following dialogue segments from English into natural, concise Khmer.\n" +
      "Ensure each line is short and fast to read so it fits the audio duration (about 3-4 Khmer characters per second of duration).\n\n" +
      "Input segments:\n--------------------------------------------------\n";

    segs.forEach(s => {
      let duration = s.end_time - s.start_time;
      if (duration <= 0) duration = 1.0;
      combinedPrompt += `Line [${s.segment_id}] | Duration: ${duration.toFixed(1)}s\n`;
      combinedPrompt += `English: "${s.original_text}"\n\n`;
    });

    combinedPrompt += "--------------------------------------------------\n\n" +
      "Instructions:\n1. Translate all lines into natural Khmer.\n" +
      "2. Return ONLY the translations in this exact format (including brackets and line IDs):\n" +
      "[id] <Khmer translation>\n\n" +
      "Example:\n[1] ជំរាបសួរ\n[2] តើអ្នកសុខសប្បាយជាទេ?\n";

    combinedPrompt += "\n3. Do not include any notes, formatting, introductory text, or markdown codeblocks.\n";

    try {
      await navigator.clipboard.writeText(combinedPrompt);
      alert("Copied full batch prompt to clipboard!");
    } catch (err) {
      alert("Copy failed");
    }
  };

  const handlePasteAll = async () => {
    try {
      const text = await navigator.clipboard.readText();
      
      const regex = /\[([^\]]+)\]\s*([^\[]*)/g;
      let match;
      let matchedCount = 0;
      const updates = {};
      
      while ((match = regex.exec(text)) !== null) {
          const id = match[1].trim();
          const translation = match[2].trim();
          updates[id] = translation;
          matchedCount++;
      }
      
      if (matchedCount > 0) {
          setManualSegments(prev => prev.map(s => {
              if (updates[String(s.segment_id)]) {
                  return { ...s, translated_text: updates[String(s.segment_id)] };
              }
              return s;
          }));
          alert(`Successfully pasted and matched ${matchedCount} segments!`);
      } else {
          alert("No matching translations found. Make sure the AI included the [id] brackets.");
      }
    } catch (err) {
      alert("Paste failed. Browser might be blocking clipboard access.");
    }
  };

  const handleSubmitReview = async () => {
    if (!projectId() || submitBusy()) return;
    setSubmitBusy(true);

    try {
      const payload = {
        translations: manualSegments().map(s => ({
          segment_id: s.segment_id,
          translated_text: s.translated_text
        }))
      };

      await fetch(`${apiBase}/api/projects/${projectId()}/segments/batch-translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      setShowManualReview(false);
      setManualSegments([]);
      setJob({ step: "Synthesizing", progress: 35, detail: "Rendering dubbed voices..." });
      // Reconnect to continue listening
      startPolling(projectId());
    } catch (err) {
      alert("Submit failed: " + err.message);
    } finally {
      setSubmitBusy(false);
    }
  };

  const handleReset = async () => {
    if (projectId()) {
      try { await fetch(`${apiBase}/api/projects/${projectId()}`, { method: "DELETE" }); } catch (e) {}
    }
    setFile(null);
    setProjectId(null);
    localStorage.removeItem("activeProjectId");
    setIsRunning(false);
    setIsCompleted(false);
    setShowManualReview(false);
    setManualSegments([]);
    setJob({ step: "Idle", progress: 0, detail: "Select a video to begin" });
    if (wsRef) clearInterval(wsRef);
  };
  const handleDownload = async (e) => {
    e.preventDefault();
    const url = `${apiBase}/api/downloads/${projectId()}/video/16_9`;
    try {
      if (window.showSaveFilePicker) {
        const handle = await window.showSaveFilePicker({
          suggestedName: `translated_video_${projectId()}.mp4`,
          types: [{
            description: 'MP4 Video',
            accept: {'video/mp4': ['.mp4']},
          }],
        });
        const writable = await handle.createWritable();
        const response = await fetch(url);
        if (!response.ok) throw new Error("Network response was not ok");
        await response.body.pipeTo(writable);
      } else {
        const a = document.createElement('a');
        a.href = url;
        a.download = `translated_video_${projectId()}.mp4`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error("Download failed:", err);
        alert("Failed to download: " + err.message);
      }
    }
  };

  return (
    <main class="min-h-screen bg-[#0a0a0a] text-zinc-100 font-sans selection:bg-emerald-500/30">
      <div class="fixed inset-0 z-0 pointer-events-none">
        <div class="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-emerald-600/20 blur-[120px]" />
        <div class="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-cyan-600/20 blur-[120px]" />
      </div>

      <div class="relative z-10 mx-auto w-full max-w-4xl px-6 py-12">
        <header class="mb-12 text-center">
          <h1 class="text-4xl font-black tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white to-zinc-500 mb-2">Anime Dub Studio</h1>
          <p class="text-sm font-medium text-emerald-400/80 tracking-widest uppercase">Professional AI Pipeline</p>
        </header>

        {/* PHASE 1: UPLOAD */}
        <Show when={!isRunning() && !showManualReview() && !isCompleted()}>
          <div class="flex flex-col gap-6 animate-fade-in">
            <div class="rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl">
              <h2 class="text-2xl font-bold text-white mb-6">1. Upload & Configure</h2>
              
              <div class="space-y-6">
                <div>
                  <label class="block text-sm font-semibold text-zinc-300 mb-2">Select Video</label>
                  <label class="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-white/20 rounded-2xl cursor-pointer bg-white/5 hover:bg-white/10 hover:border-emerald-400 transition-all duration-300">
                    <div class="flex flex-col items-center justify-center pt-5 pb-6">
                      <svg class="w-8 h-8 mb-3 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
                      <p class="text-sm text-zinc-300"><span class="font-semibold">Click to upload</span> or drag and drop</p>
                      <Show when={file()}><p class="text-emerald-400 font-medium mt-2">{file().name}</p></Show>
                    </div>
                    <input type="file" class="hidden" accept="video/*" onChange={(e) => setFile(e.target.files[0])} />
                  </label>
                </div>

                <div class="grid grid-cols-2 gap-6">
                  <div>
                    <label class="block text-sm font-semibold text-zinc-300 mb-2">Voice AI Engine</label>
                    <div class="flex bg-black/40 p-1 rounded-xl">
                      <button onClick={() => setTtsEngine("voxcpm2")} class={`flex-1 py-2 rounded-lg text-sm font-bold transition-all ${ttsEngine() === "voxcpm2" ? "bg-emerald-500 text-black shadow-lg" : "text-zinc-400 hover:text-white"}`}>VoxCPM2</button>
                      <button onClick={() => setTtsEngine("edge")} class={`flex-1 py-2 rounded-lg text-sm font-bold transition-all ${ttsEngine() === "edge" ? "bg-emerald-500 text-black shadow-lg" : "text-zinc-400 hover:text-white"}`}>Edge Cloud</button>
                    </div>
                  </div>
                </div>

                <div class="mt-4 grid grid-cols-2 gap-6">
                  <div>
                    <label class="block text-sm font-semibold text-zinc-300 mb-2">Choose Voice</label>
                    <div class="flex bg-black/40 p-1 rounded-xl">
                      <button onClick={() => setVoiceChoice("male")} class={`flex-1 py-2 rounded-lg text-sm font-bold transition-all ${voiceChoice() === "male" ? "bg-emerald-500 text-black shadow-lg" : "text-zinc-400 hover:text-white"}`}>Male</button>
                      <button onClick={() => setVoiceChoice("female")} class={`flex-1 py-2 rounded-lg text-sm font-bold transition-all ${voiceChoice() === "female" ? "bg-emerald-500 text-black shadow-lg" : "text-zinc-400 hover:text-white"}`}>Female</button>
                    </div>
                  </div>
                  <div>
                    <label class="block text-sm font-semibold text-zinc-300 mb-2">Video Type</label>
                    <select disabled class="w-full h-[40px] rounded-xl border border-white/10 bg-black/40 px-3 text-sm text-zinc-300 opacity-70">
                      <option value="anime">Anime (Locked)</option>
                    </select>
                  </div>
                </div>

                <div class="mt-4 flex items-center justify-between bg-black/40 p-4 rounded-xl border border-white/5">
                  <div>
                    <h4 class="text-sm font-bold text-white">Khmer Subtitles</h4>
                    <p class="text-xs text-zinc-400 mt-1">Burn translated text into video</p>
                  </div>
                  <button 
                    onClick={() => setEnableSubtitles(!enableSubtitles())} 
                    class={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${enableSubtitles() ? 'bg-emerald-500' : 'bg-zinc-600'}`}
                  >
                    <span class={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${enableSubtitles() ? 'translate-x-6' : 'translate-x-1'}`} />
                  </button>
                </div>

                <button onClick={handleUpload} disabled={!file()} class="w-full mt-4 rounded-2xl bg-gradient-to-r from-emerald-500 to-cyan-500 py-4 text-base font-extrabold text-black shadow-[0_0_20px_rgba(16,185,129,0.3)] transition-all hover:scale-[1.02] disabled:opacity-50 disabled:hover:scale-100">
                  Start Translation
                </button>
              </div>
            </div>
          </div>
        </Show>

        {/* PHASE 2: PROCESSING */}
        <Show when={isRunning() && !showManualReview() && !isCompleted()}>
          <div class="flex flex-col items-center justify-center py-20">
            <div class="relative w-64 h-64 flex items-center justify-center">
              <svg class="absolute w-full h-full animate-spin-slow" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="45" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="4" />
                <circle cx="50" cy="50" r="45" fill="none" stroke="url(#gradient)" stroke-width="4" stroke-dasharray="283" stroke-dashoffset={283 - (283 * job().progress) / 100} class="transition-all duration-500" />
                <defs>
                  <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stop-color="#10b981" />
                    <stop offset="100%" stop-color="#06b6d4" />
                  </linearGradient>
                </defs>
              </svg>
              <div class="text-center">
                <h3 class="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-400">{Math.round(job().progress)}%</h3>
              </div>
            </div>
            
            <h2 class="text-2xl font-bold text-white mt-8 mb-2">{job().step}</h2>
            <p class="text-zinc-400 text-sm max-w-md text-center">{job().detail}</p>
            
            <div class="flex gap-8 mt-8 border border-white/10 bg-white/5 rounded-2xl px-8 py-4 backdrop-blur-md">
              <div class="text-center">
                <p class="text-xs text-zinc-500 uppercase tracking-wider mb-1">Time Remaining</p>
                <p class="text-lg font-semibold text-emerald-400">{job().eta || "Calculating..."}</p>
              </div>
            </div>
            
            <button onClick={handleReset} class="mt-8 rounded-xl border border-red-500/30 bg-red-500/10 px-6 py-3 text-sm font-bold text-red-400 transition-all hover:bg-red-500/20">
              Cancel & Start New
            </button>
          </div>
        </Show>

        {/* PHASE 3: REVIEW */}
        <Show when={showManualReview()}>
          <div class="flex flex-col gap-6">
            <div class="rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl">
              <div class="flex justify-between items-center mb-6">
                <div>
                  <h2 class="text-2xl font-bold text-white mb-2">Translate & Review</h2>
                  <p class="text-sm text-zinc-400">Copy the professional AI prompt, paste it into an AI tool, and paste the result back.</p>
                  <div class="flex gap-3 mt-4">
                    <button onClick={handleCopyAll} class="rounded-xl bg-white/10 hover:bg-white/20 px-4 py-2 text-xs font-bold text-white transition-all">Copy Batch Prompt</button>
                    <button onClick={handlePasteAll} class="rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 px-4 py-2 text-xs font-bold text-emerald-400 transition-all border border-emerald-500/50">Paste AI Response (Auto Fill)</button>
                  </div>
                </div>
                <div class="flex gap-3">
                  <button onClick={handleReset} class="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm font-bold text-red-400 transition-all hover:bg-red-500/20">
                    Cancel & Start New
                  </button>
                  <button onClick={handleSubmitReview} disabled={submitBusy()} class="rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 px-6 py-3 text-sm font-bold text-black shadow-lg transition-all hover:scale-105 disabled:opacity-50">
                    {submitBusy() ? "Processing..." : "Next Part / Submit"}
                  </button>
                </div>
              </div>

              <div class="space-y-6 max-h-[60vh] overflow-y-auto pr-2">
                <For each={manualSegments()}>
                  {(seg, i) => (
                    <div class="rounded-2xl border border-white/10 bg-black/40 p-5 group transition-colors hover:border-emerald-500/50">
                      <div class="flex items-center justify-between mb-3">
                        <span class="text-xs font-bold text-emerald-400 uppercase tracking-wider bg-emerald-500/10 px-2 py-1 rounded-md">Segment #{i() + 1}</span>
                        <button onClick={() => handleCopy(seg.segment_id, seg.ai_prompt)} class="text-xs font-semibold text-zinc-300 bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded-lg transition-colors">
                          {copiedId() === seg.segment_id ? "Copied!" : "Copy Professional Prompt"}
                        </button>
                      </div>
                      
                      <div class="mb-4">
                        <p class="text-xs text-zinc-500 mb-1">Original Text:</p>
                        <p class="text-sm text-zinc-300 bg-white/5 p-3 rounded-xl border border-white/5">"{seg.original_text}"</p>
                      </div>

                      <div>
                        <div class="flex justify-between items-center mb-1">
                          <p class="text-xs text-zinc-500">Translated Result:</p>
                        </div>
                        <textarea
                          value={manualSegments().find(m => m.segment_id === seg.segment_id)?.translated_text || ""}
                          onInput={(e) => updateText(seg.segment_id, e.target.value)}
                          placeholder="Paste the translated text here..."
                          class="w-full min-h-[80px] rounded-xl border border-white/10 bg-black/50 p-3 text-sm text-white focus:border-emerald-500 outline-none transition-colors"
                        />
                      </div>
                    </div>
                  )}
                </For>
                <Show when={manualSegments().length === 0}><p class="text-center text-zinc-500 py-10">Loading segments...</p></Show>
              </div>
            </div>
          </div>
        </Show>

        {/* PHASE 4: DONE */}
        <Show when={isCompleted()}>
          <div class="flex flex-col items-center justify-center py-20">
            <div class="w-24 h-24 bg-emerald-500/20 rounded-full flex items-center justify-center mb-6 border border-emerald-500/50">
              <svg class="w-12 h-12 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <h2 class="text-3xl font-extrabold text-white mb-4">Translation Complete!</h2>
            <p class="text-zinc-400 mb-8 text-center max-w-md">Your anime video has been successfully translated and dubbed.</p>
            
            <div class="flex flex-col gap-4 w-full max-w-sm">
              <button onClick={handleDownload} class="w-full block text-center rounded-2xl bg-gradient-to-r from-emerald-500 to-cyan-500 py-4 text-sm font-bold text-black shadow-lg hover:shadow-emerald-500/25 transition-all hover:-translate-y-1">
                Download Final Video
              </button>
              <button onClick={handleReset} class="w-full rounded-2xl border border-red-500/30 bg-red-500/10 py-4 text-sm font-bold text-red-400 transition-all hover:bg-red-500/20">
                Start New Translation (Deletes Old Data)
              </button>
            </div>
          </div>
        </Show>

      </div>
    </main>
  );
}
