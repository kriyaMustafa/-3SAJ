import { createSignal, createEffect, onCleanup, For, Show } from "solid-js";

function App() {
  const [projects, setProjects] = createSignal([]);
  const [selectedProjectId, setSelectedProjectId] = createSignal("");
  const [projectDetails, setProjectDetails] = createSignal(null);
  
  // Pipeline real-time status signals
  const [pipelineState, setPipelineState] = createSignal({
    status: "pending",
    progress: 0,
    chunks: { total: 0, completed: 0, failed: 0 },
    segments: { total: 0, completed: 0 }
  });

  // Dual-tab configuration state
  const [activeTab, setActiveTab] = createSignal("url"); // 'local' or 'url'
  const [localFile, setLocalFile] = createSignal(null);
  const [videoUrl, setVideoUrl] = createSignal("");
  const [sourceLang, setSourceLang] = createSignal("en");
  const [targetLang, setTargetLang] = createSignal("km");
  const [genreMode, setGenreMode] = createSignal("anime_recap");
  const [generateShorts, setGenerateShorts] = createSignal(false);
  const [isSubmitting, setIsSubmitting] = createSignal(false);
  const [previewMode, setPreviewMode] = createSignal("original"); // 'original' or 'dubbed'

  // Resolve backend hosts dynamically
  const API_HOST = typeof window !== "undefined" 
    ? (window.location.port === "5173" || window.location.port === "3000" ? `${window.location.hostname}:8000` : window.location.host)
    : "127.0.0.1:8000";
  const httpProtocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "https://" : "http://";
  const wsProtocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss://" : "ws://";

  // Fetch projects list on mount
  const fetchProjects = async () => {
    try {
      const res = await fetch(`${httpProtocol}${API_HOST}/api/projects`);
      if (res.ok) {
        const data = await res.json();
        setProjects(data);
        if (data.length > 0 && !selectedProjectId()) {
          setSelectedProjectId(data[0].id);
        }
      }
    } catch (e) {
      console.error("Failed to load projects", e);
    }
  };

  createEffect(() => {
    fetchProjects();
  });

  // Pull details when project selection changes
  const fetchProjectDetails = async (projectId) => {
    if (!projectId) return;
    try {
      const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${projectId}`);
      if (res.ok) {
        const data = await res.json();
        setProjectDetails(data);
        
        // Sync static pipeline state
        setPipelineState({
          status: data.project.status,
          progress: data.project.progress || 0,
          chunks: {
            total: data.chunks.length,
            completed: data.chunks.filter(c => c.status === "completed").length,
            failed: data.chunks.filter(c => c.status === "failed").length
          },
          segments: {
            total: data.segments.length,
            completed: data.segments.filter(s => s.status === "synthesized").length
          }
        });
      }
    } catch (e) {
      console.error("Failed to fetch project details", e);
    }
  };

  createEffect(() => {
    const id = selectedProjectId();
    fetchProjectDetails(id);
  });

  // WebSocket Live Updates with Fallback to Smart Polling
  createEffect(() => {
    const id = selectedProjectId();
    if (!id) return;

    let ws = null;
    let pollInterval = null;
    let isTerminated = false;

    const connectWS = () => {
      if (isTerminated) return;
      const wsUrl = `${wsProtocol}${API_HOST}/ws/progress/${id}`;
      console.log(`[WebSocket] Connecting to ${wsUrl}`);
      ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setPipelineState({
            status: data.status,
            progress: data.progress,
            chunks: data.chunks,
            segments: data.segments
          });

          // Sync project details on status transition or completion
          if (["completed", "failed", "cancelled"].includes(data.status)) {
            isTerminated = true;
            ws.close();
            fetchProjectDetails(id);
            fetchProjects();
          }
        } catch (err) {
          console.error("[WebSocket] Parse error:", err);
        }
      };

      ws.onclose = (event) => {
        if (!isTerminated) {
          console.warn("[WebSocket] Closed, starting smart fallback polling.");
          startPolling();
        }
      };

      ws.onerror = (err) => {
        console.error("[WebSocket] Connection error:", err);
        ws.close();
      };
    };

    const startPolling = () => {
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = setInterval(async () => {
        if (isTerminated) {
          clearInterval(pollInterval);
          return;
        }
        try {
          const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${id}`);
          if (res.ok) {
            const data = await res.json();
            setPipelineState({
              status: data.project.status,
              progress: data.project.progress || 0,
              chunks: {
                total: data.chunks.length,
                completed: data.chunks.filter(c => c.status === "completed").length,
                failed: data.chunks.filter(c => c.status === "failed").length
              },
              segments: {
                total: data.segments.length,
                completed: data.segments.filter(s => s.status === "synthesized").length
              }
            });

            if (["completed", "failed", "cancelled"].includes(data.project.status)) {
              isTerminated = true;
              clearInterval(pollInterval);
              fetchProjectDetails(id);
              fetchProjects();
            }
          }
        } catch (e) {
          console.error("[Polling] Error fetching status:", e);
        }
      }, 4000);
    };

    // Initialize WS connection
    connectWS();

    onCleanup(() => {
      isTerminated = true;
      if (ws) ws.close();
      if (pollInterval) clearInterval(pollInterval);
    });
  });

  // Handle local file selection
  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      setLocalFile(e.target.files[0]);
    }
  };

  // Submit new translation job
  const handleStartPipeline = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      let source = videoUrl();
      if (activeTab() === "local") {
        if (!localFile()) {
          alert("Please select a local video file first.");
          setIsSubmitting(false);
          return;
        }
        
        const formData = new FormData();
        formData.append("file", localFile());
        
        const uploadRes = await fetch(`${httpProtocol}${API_HOST}/upload`, {
          method: "POST",
          body: formData
        });
        if (!uploadRes.ok) throw new Error("File upload failed");
        
        const uploadData = await uploadRes.json();
        source = uploadData.filename;
      }

      // Create translation project
      const payload = {
        input_type: activeTab(),
        input_source: source,
        source_language: sourceLang(),
        target_language: targetLang(),
        genre_mode: genreMode(),
        generate_shorts: generateShorts()
      };

      const res = await fetch(`${httpProtocol}${API_HOST}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const newProj = await res.json();
        alert("Pipeline initialized successfully!");
        setVideoUrl("");
        setLocalFile(null);
        await fetchProjects();
        setSelectedProjectId(newProj.project_id);
      } else {
        const errorData = await res.json();
        alert(`Error starting pipeline: ${errorData.detail}`);
      }
    } catch (err) {
      console.error(err);
      alert(`Server error starting pipeline: ${err.message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Edit segment in line and save to database
  const handleUpdateSegmentText = async (segmentId, newText) => {
    const id = selectedProjectId();
    try {
      const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${id}/segments/${segmentId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ translated_text: newText })
      });
      if (res.ok) {
        const details = projectDetails();
        if (details) {
          const updatedSegs = details.segments.map(s => 
            s.id === segmentId ? { ...s, translated_text: newText, status: "translated" } : s
          );
          setProjectDetails({ ...details, segments: updatedSegs });
        }
      }
    } catch (err) {
      console.error("Failed to update segment text", err);
    }
  };

  // Override speaker voice profile / gender
  const handleUpdateSegmentSpeaker = async (segmentId, newSpeakerId) => {
    const id = selectedProjectId();
    try {
      const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${id}/segments/${segmentId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speaker_id: newSpeakerId })
      });
      if (res.ok) {
        const details = projectDetails();
        if (details) {
          const updatedSegs = details.segments.map(s => 
            s.id === segmentId ? { ...s, speaker_id: newSpeakerId, status: "translated" } : s
          );
          setProjectDetails({ ...details, segments: updatedSegs });
        }
      }
    } catch (err) {
      console.error("Failed to update speaker override", err);
    }
  };

  // Trigger individual segment audio re-rendering
  const handleReRenderSegment = async (segmentId) => {
    const id = selectedProjectId();
    try {
      const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${id}/segments/${segmentId}/render`, {
        method: "POST"
      });
      if (res.ok) {
        alert("Segment re-render triggered. Synthesizing new audio chunk...");
        fetchProjectDetails(id);
      }
    } catch (err) {
      console.error("Failed to re-render segment", err);
    }
  };

  // Cancel running project pipeline
  const handleCancelProject = async (projectId) => {
    if (!confirm("Are you sure you want to stop/cancel this translation job?")) return;
    try {
      const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${projectId}/cancel`, {
        method: "POST"
      });
      if (res.ok) {
        alert("Pipeline cancel request sent!");
        await fetchProjects();
        if (selectedProjectId() === projectId) {
          await fetchProjectDetails(projectId);
        }
      } else {
        const data = await res.json();
        alert(`Failed to cancel: ${data.detail}`);
      }
    } catch (e) {
      alert(`Error cancelling: ${e.message}`);
    }
  };

  // Permanently delete project and files
  const handleDeleteProject = async (projectId) => {
    if (!confirm("Are you sure you want to permanently delete this project? All processed data will be wiped.")) return;
    try {
      const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${projectId}`, {
        method: "DELETE"
      });
      if (res.ok) {
        alert("Project deleted successfully!");
        if (selectedProjectId() === projectId) {
          setSelectedProjectId("");
          setProjectDetails(null);
        }
        await fetchProjects();
      } else {
        const data = await res.json();
        alert(`Failed to delete: ${data.detail}`);
      }
    } catch (e) {
      alert(`Error deleting: ${e.message}`);
    }
  };

  const formatTimeStr = (sec) => {
    if (sec == null) return "00:00.00";
    const minutes = Math.floor(sec / 60);
    const seconds = Math.floor(sec % 60);
    const ms = Math.floor((sec - Math.floor(sec)) * 100);
    return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}.${ms.toString().padStart(2, "0")}`;
  };

  // Define steps for progress visualization
  const pipelineSteps = [
    { key: "ingesting", label: "Ingesting Video & Splitting", desc: "Downloading/parsing video file and running frame analysis." },
    { key: "stemming", label: "Vocal Stem Separation (Demucs)", desc: "Splitting vocals from background audio tracks offline." },
    { key: "transcribing", label: "Speech Transcription (Whisper)", desc: "Detecting dialogue markers and timestamping speech segments." },
    { key: "translating", label: "Gemini Translation (Rolling Context)", desc: "Contextual translation into natural, paced Khmer text." },
    { key: "synthesizing", label: "VoxCPM2 Speech Synthesis (Local)", desc: "Offline neural speech generation via GPU weights." },
    { key: "exporting", label: "BGM Mixing & Subtitle Rendering", desc: "Auto-stretching audio and compositing the final dubbed video." },
    { key: "completed", label: "Pipeline Completed", desc: "All dubbed video and metadata assets ready for export." }
  ];

  const getStepStatus = (stepKey) => {
    const currentStatus = pipelineState().status;
    const stepOrder = ["pending", "ingesting", "stemming", "transcribing", "translating", "synthesizing", "exporting", "completed"];
    const currentIndex = stepOrder.indexOf(currentStatus);
    const stepIndex = stepOrder.indexOf(stepKey);

    if (currentStatus === "failed") {
      return "failed";
    }
    if (currentIndex >= stepIndex) {
      return currentIndex === stepIndex && currentStatus !== "completed" ? "active" : "completed";
    }
    return "pending";
  };

  // Calculate statistics from segment list
  const getStats = () => {
    const details = projectDetails();
    if (!details || !details.segments || details.segments.length === 0) {
      return { duration: 0, characters: 0, speakers: 0 };
    }
    const maxTime = Math.max(...details.segments.map(s => s.end_time));
    const minTime = Math.min(...details.segments.map(s => s.start_time));
    const duration = Math.max(0, maxTime - minTime);
    const characters = details.segments.reduce((acc, s) => acc + (s.translated_text?.length || 0), 0);
    const speakers = new Set(details.segments.map(s => s.speaker_id?.toLowerCase())).size;
    return { duration, characters, speakers };
  };

  return (
    <div class="flex h-screen bg-[#070c18] text-slate-100 overflow-hidden font-sans">
      
      {/* Sidebar - Projects Registry List */}
      <div class="w-80 bg-[#0c1427]/90 backdrop-blur-xl border-r border-slate-800/80 flex flex-col justify-between shadow-2xl relative z-10">
        <div>
          {/* Logo & Header */}
          <div class="p-6 border-b border-slate-800/80 bg-[#0f1a30]/20 flex items-center gap-3">
            <div class="bg-gradient-to-tr from-emerald-400 to-teal-500 text-slate-950 p-2.5 rounded-xl shadow-lg shadow-emerald-500/20">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </div>
            <div>
              <h1 class="text-lg font-black tracking-wider bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-100 to-slate-400">VocalTransl8</h1>
              <p class="text-[10px] text-emerald-400 font-extrabold uppercase tracking-widest">Orchestrator v2.0</p>
            </div>
          </div>

          {/* Project Registry */}
          <div class="p-5">
            <div class="flex items-center justify-between mb-4">
              <h2 class="text-[10px] font-black text-slate-400 uppercase tracking-widest">Active Registry</h2>
              <span class="text-[10px] bg-slate-800 text-slate-300 font-bold px-2 py-0.5 rounded-md">{projects().length} Jobs</span>
            </div>
            
            <div class="space-y-2 overflow-y-auto max-h-[60vh] pr-1 custom-scrollbar">
              <For each={projects()}>
                {(proj) => {
                  const isSelected = selectedProjectId() === proj.id;
                  return (
                    <div
                      onClick={() => setSelectedProjectId(proj.id)}
                      class={`group relative w-full text-left p-3.5 rounded-xl cursor-pointer transition-all duration-300 border ${
                        isSelected 
                          ? "bg-gradient-to-r from-[#10b981]/15 to-[#0b9064]/5 border-emerald-500/40 shadow-lg shadow-emerald-500/5 text-white" 
                          : "bg-slate-900/40 border-slate-800/80 hover:border-slate-700/60 text-slate-300 hover:bg-slate-800/30"
                      }`}
                    >
                      <div class="flex items-start justify-between gap-2">
                        <span class={`text-xs truncate font-bold ${isSelected ? "text-emerald-300" : "text-slate-200"}`}>
                          {proj.name}
                        </span>
                        
                        {/* Control Actions (Cancel/Delete) */}
                        <div class="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-all duration-200">
                          {["pending", "ingesting", "stemming", "transcribing", "translating", "synthesizing", "exporting"].includes(proj.status) && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleCancelProject(proj.id);
                              }}
                              title="Cancel Pipeline"
                              class="p-1 text-slate-400 hover:text-amber-400 hover:bg-slate-800 rounded-lg transition-colors border border-slate-800"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                              </svg>
                            </button>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteProject(proj.id);
                            }}
                            title="Delete Project Data"
                            class="p-1 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition-colors border border-slate-800"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                        </div>
                      </div>
                      
                      <div class="flex items-center justify-between w-full mt-2.5">
                        <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                          {proj.genre_mode === "anime_recap" ? "🎬 Anime Mode" : "🎭 Drama Mode"}
                        </span>
                        
                        <span class={`text-[9px] px-2 py-0.5 rounded-full font-black uppercase border ${
                          proj.status === "completed" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                          proj.status === "failed" ? "bg-rose-500/10 text-rose-400 border-rose-500/20" :
                          proj.status === "cancelled" ? "bg-slate-800 text-slate-400 border-slate-700" :
                          "bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse"
                        }`}>{proj.status}</span>
                      </div>
                    </div>
                  );
                }}
              </For>
            </div>
          </div>
        </div>

        {/* Node GPU status */}
        <div class="p-5 border-t border-slate-800/80 bg-[#0b101f]/80">
          <div class="flex items-center gap-3 bg-slate-900/60 p-3 rounded-xl border border-slate-800/60">
            <div class="relative flex h-3 w-3">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
            </div>
            <div>
              <p class="text-[10px] font-black text-slate-400 uppercase tracking-widest">VoxCPM2 Node Status</p>
              <h3 class="text-xs font-black text-white mt-0.5">GPU Accel Active (BF16)</h3>
            </div>
          </div>
        </div>
      </div>

      {/* Main Core Dashboard Grid */}
      <div class="flex-1 flex flex-col overflow-hidden relative">
        
        {/* Glowing Background Orbs */}
        <div class="absolute top-0 right-0 w-96 h-96 bg-emerald-500/5 rounded-full filter blur-[100px] pointer-events-none"></div>
        <div class="absolute bottom-0 left-1/4 w-96 h-96 bg-indigo-500/5 rounded-full filter blur-[100px] pointer-events-none"></div>

        {/* Top Panel Section */}
        <div class="p-6 border-b border-slate-800/60 bg-[#080d19]/40 overflow-y-auto max-h-[42vh] custom-scrollbar relative z-10">
          <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Launch New Translation Pipeline Panel */}
            <div class="bg-gradient-to-b from-slate-900/70 to-slate-900/30 backdrop-blur-md border border-slate-800/80 rounded-2xl p-5 shadow-2xl flex flex-col justify-between">
              <div>
                <h2 class="text-sm font-black text-white uppercase tracking-widest mb-4 flex items-center gap-2">
                  <span class="bg-emerald-500/10 text-emerald-400 p-1.5 rounded-lg">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4.5 w-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 4v16m8-8H4" />
                    </svg>
                  </span>
                  Translate Pipeline
                </h2>
                
                <form onSubmit={handleStartPipeline} class="space-y-4">
                  {/* Mode Tabs */}
                  <div class="flex bg-slate-950/60 p-1 rounded-xl border border-slate-800/80">
                    <button
                      type="button"
                      onClick={() => setActiveTab("url")}
                      class={`flex-1 text-center py-2 text-xs rounded-lg transition-all font-bold ${
                        activeTab() === "url" 
                          ? "bg-gradient-to-r from-emerald-500 to-teal-500 text-slate-950 shadow-md" 
                          : "text-slate-400 hover:text-white"
                      }`}
                    >
                      Remote URL
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveTab("local")}
                      class={`flex-1 text-center py-2 text-xs rounded-lg transition-all font-bold ${
                        activeTab() === "local" 
                          ? "bg-gradient-to-r from-emerald-500 to-teal-500 text-slate-950 shadow-md" 
                          : "text-slate-400 hover:text-white"
                      }`}
                    >
                      Local Video
                    </button>
                  </div>

                  <Show when={activeTab() === "url"}>
                    <div class="space-y-1">
                      <label class="text-[10px] font-black text-slate-400 uppercase tracking-widest">Video Stream URL</label>
                      <input
                        type="url"
                        placeholder="YouTube, TikTok or MP4 Web Link"
                        value={videoUrl()}
                        onInput={(e) => setVideoUrl(e.target.value)}
                        class="w-full bg-slate-950/60 border border-slate-850 hover:border-slate-700/60 focus:border-emerald-500 rounded-xl px-3 py-2 text-slate-100 text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500/20 transition-all font-medium"
                      />
                    </div>
                  </Show>

                  <Show when={activeTab() === "local"}>
                    <div class="space-y-1">
                      <label class="text-[10px] font-black text-slate-400 uppercase tracking-widest">Drag & Drop Media</label>
                      <div class="border border-dashed border-slate-800 hover:border-emerald-500/50 rounded-xl p-4 text-center cursor-pointer transition-all duration-300 bg-slate-950/30 hover:bg-slate-950/60">
                        <input
                          type="file"
                          accept="video/*"
                          onChange={handleFileChange}
                          class="hidden"
                          id="fileUploadInput"
                        />
                        <label for="fileUploadInput" class="cursor-pointer">
                          <svg xmlns="http://www.w3.org/2000/svg" class="mx-auto h-7 w-7 text-slate-500 mb-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                          </svg>
                          <span class="text-xs font-black block text-slate-300">
                            {localFile() ? localFile().name : "Choose Media File"}
                          </span>
                          <span class="text-[9px] text-slate-500 mt-0.5 block">Supports MP4, MKV up to 2GB</span>
                        </label>
                      </div>
                    </div>
                  </Show>

                  {/* Settings Grid */}
                  <div class="grid grid-cols-2 gap-3">
                    <div class="space-y-1">
                      <label class="text-[10px] font-black text-slate-400 uppercase tracking-widest">Target Language</label>
                      <select
                        value={targetLang()}
                        onChange={(e) => setTargetLang(e.target.value)}
                        class="w-full bg-slate-950/60 border border-slate-850 focus:border-emerald-500 rounded-xl px-2.5 py-2 text-slate-100 text-xs focus:outline-none transition-all cursor-pointer font-bold"
                      >
                        <option value="km">Khmer (ភាសាខ្មែរ)</option>
                        <option value="en">English</option>
                        <option value="es">Spanish</option>
                        <option value="vi">Vietnamese</option>
                      </select>
                    </div>
                    <div class="space-y-1">
                      <label class="text-[10px] font-black text-slate-400 uppercase tracking-widest">Genre Setting</label>
                      <select
                        value={genreMode()}
                        onChange={(e) => setGenreMode(e.target.value)}
                        class="w-full bg-slate-950/60 border border-slate-850 focus:border-emerald-500 rounded-xl px-2.5 py-2 text-slate-100 text-xs focus:outline-none transition-all cursor-pointer font-bold"
                      >
                        <option value="anime_recap">Anime (Paced/Tight)</option>
                        <option value="drama_recap">Drama (Dramatic)</option>
                      </select>
                    </div>
                  </div>

                  <div class="flex items-center justify-between pt-2 border-t border-slate-850">
                    <div class="flex items-center gap-2">
                      <input
                        type="checkbox"
                        id="shortsCheckbox"
                        checked={generateShorts()}
                        onChange={(e) => setGenerateShorts(e.target.checked)}
                        class="w-4 h-4 text-emerald-500 border-slate-800 rounded focus:ring-emerald-500 bg-slate-950 focus:ring-offset-0"
                      />
                      <label for="shortsCheckbox" class="text-xs font-bold text-slate-400 select-none cursor-pointer">Export Shorts (9:16)</label>
                    </div>
                    
                    <button
                      type="submit"
                      disabled={isSubmitting()}
                      class="bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 disabled:from-slate-850 disabled:to-slate-800 disabled:text-slate-500 text-slate-950 font-black px-4 py-2.5 rounded-xl text-xs flex items-center gap-1.5 transition-all duration-300 shadow-lg shadow-emerald-500/10 active:scale-95 cursor-pointer"
                    >
                      {isSubmitting() ? "Synthesizing..." : "Run Dubbing"}
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd" />
                      </svg>
                    </button>
                  </div>
                </form>
              </div>
            </div>

            {/* Panel A: Media Player Preview */}
            <div class="bg-gradient-to-b from-slate-900/70 to-slate-900/30 backdrop-blur-md border border-slate-800/80 rounded-2xl p-5 shadow-2xl flex flex-col justify-between">
              <div>
                <h2 class="text-sm font-black text-white uppercase tracking-widest mb-4 flex items-center justify-between">
                  <span class="flex items-center gap-2">
                    <span class="bg-indigo-500/10 text-indigo-400 p-1.5 rounded-lg">
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-4.5 w-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                      </svg>
                    </span>
                    Panel A: Media Player
                  </span>
                  <Show when={selectedProjectId() && projectDetails()}>
                    <span class="text-[10px] font-bold bg-slate-800 text-slate-300 px-2 py-0.5 rounded border border-slate-700 capitalize">{previewMode()} Mode</span>
                  </Show>
                </h2>
                
                <Show
                  when={selectedProjectId() && projectDetails()}
                  fallback={
                    <div class="bg-slate-950/60 rounded-xl aspect-video flex flex-col items-center justify-center text-slate-500 border border-slate-850/80 h-40">
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-slate-650 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                      <p class="text-[10px] font-black uppercase tracking-widest text-slate-600">No Project Selected</p>
                    </div>
                  }
                >
                  <div class="relative rounded-xl overflow-hidden aspect-video bg-black border border-slate-850 shadow-2xl h-40 flex items-center justify-center group/video">
                    <video
                      id="mainVideoPlayer"
                      src={
                        previewMode() === "dubbed"
                          ? `${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/video/16_9`
                          : `${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/video/original`
                      }
                      controls
                      class="w-full h-full object-contain"
                    />
                  </div>
                  
                  <div class="flex items-center justify-between gap-4 mt-3 pt-3 border-t border-slate-850">
                    <div class="flex bg-slate-950/60 p-1 rounded-xl border border-slate-800/80">
                      <button
                        type="button"
                        onClick={() => setPreviewMode("original")}
                        class={`px-3 py-1.5 text-[10px] rounded-lg transition-all font-black uppercase tracking-wider ${
                          previewMode() === "original" 
                            ? "bg-slate-800 text-white border border-slate-700/60 shadow-md" 
                            : "text-slate-400 hover:text-white"
                        }`}
                      >
                        Original
                      </button>
                      <button
                        type="button"
                        disabled={projectDetails()?.project.status !== "completed"}
                        onClick={() => setPreviewMode("dubbed")}
                        class={`px-3 py-1.5 text-[10px] rounded-lg transition-all font-black uppercase tracking-wider ${
                          previewMode() === "dubbed" 
                            ? "bg-gradient-to-r from-emerald-500 to-teal-500 text-slate-950 font-black" 
                            : "text-slate-400 hover:text-white disabled:opacity-30 disabled:pointer-events-none"
                        }`}
                      >
                        Khmer Dubbed
                      </button>
                    </div>
                    
                    <span class="text-[10px] text-slate-400 font-extrabold uppercase tracking-wider">
                      Stereo Audio Output
                    </span>
                  </div>
                </Show>
              </div>
            </div>

            {/* Panel C: Worker Cluster Status / Live Pipeline Tracker */}
            <div class="bg-gradient-to-b from-slate-900/70 to-slate-900/30 backdrop-blur-md border border-slate-800/80 rounded-2xl p-5 shadow-2xl flex flex-col justify-between">
              <div>
                <h2 class="text-sm font-black text-white uppercase tracking-widest mb-3.5 flex items-center justify-between">
                  <span class="flex items-center gap-2">
                    <span class="bg-emerald-500/10 text-emerald-400 p-1.5 rounded-lg flex items-center">
                      <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span>
                    </span>
                    Live Worker Cluster
                  </span>
                  <span class="text-emerald-400 font-mono text-xs font-black">{pipelineState().progress}%</span>
                </h2>
                
                <div class="w-full bg-slate-950 rounded-full h-2 mb-4 overflow-hidden border border-slate-850">
                  <div
                    class="bg-gradient-to-r from-emerald-400 to-teal-500 h-2 rounded-full transition-all duration-700 shadow-[0_0_8px_rgba(16,185,129,0.3)]"
                    style={{ width: `${pipelineState().progress}%` }}
                  ></div>
                </div>

                <div class="space-y-2 overflow-y-auto max-h-[17vh] custom-scrollbar pr-1">
                  <For each={pipelineSteps}>
                    {(step) => {
                      const status = getStepStatus(step.key);
                      return (
                        <div class="flex items-start justify-between text-[11px] py-1 border-b border-slate-900/60 last:border-b-0">
                          <div class="flex items-start gap-2.5">
                            <span class={`w-4 h-4 rounded-full flex items-center justify-center font-black text-[9px] mt-0.5 ${
                              status === "completed" ? "bg-emerald-500 text-slate-950" :
                              status === "active" ? "bg-amber-500 text-slate-950 animate-pulse" :
                              status === "failed" ? "bg-rose-500 text-white" :
                              "bg-slate-950 text-slate-650 border border-slate-850"
                            }`}>
                              {status === "completed" ? "✓" : "•"}
                            </span>
                            <div>
                              <p class={`font-black ${
                                status === "active" ? "text-amber-400" :
                                status === "completed" ? "text-slate-200" :
                                status === "failed" ? "text-rose-400" :
                                "text-slate-500"
                              }`}>{step.label}</p>
                            </div>
                          </div>
                          <span class={`text-[9px] font-black uppercase tracking-widest ${
                            status === "completed" ? "text-emerald-400" :
                            status === "active" ? "text-amber-400" :
                            status === "failed" ? "text-rose-400" :
                            "text-slate-700"
                          }`}>{status}</span>
                        </div>
                      );
                    }}
                  </For>
                </div>
              </div>

              <div class="grid grid-cols-2 gap-3 mt-4 pt-3 border-t border-slate-850 text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                <div class="flex justify-between items-center bg-slate-950/40 p-2 rounded-xl border border-slate-850">
                  <span>60s Chunks</span>
                  <span class="text-white font-mono font-bold">{pipelineState().chunks.completed} / {pipelineState().chunks.total}</span>
                </div>
                <div class="flex justify-between items-center bg-slate-950/40 p-2 rounded-xl border border-slate-850">
                  <span>Lines Dubbed</span>
                  <span class="text-white font-mono font-bold">{pipelineState().segments.completed} / {pipelineState().segments.total}</span>
                </div>
              </div>
            </div>

          </div>
        </div>

        {/* Interactive Translation Edit Workspace (Panel B) */}
        <div class="flex-1 flex flex-col min-h-0 bg-[#070c18]/90 relative z-10">
          <div class="px-6 py-4 border-b border-slate-800/80 flex flex-col sm:flex-row justify-between sm:items-center bg-[#0a1224]/30 gap-4">
            <div>
              <h2 class="text-md font-black text-white uppercase tracking-wider flex items-center gap-2">
                <span class="bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded text-[10px] font-black">Panel B</span>
                Dialogue Dubbing Workspace
              </h2>
              <p class="text-xs text-slate-400 mt-0.5">Edit transcription translation alignment and trigger offline selective neural synthesis.</p>
            </div>
            
            <Show when={projectDetails()}>
              <div class="flex flex-wrap items-center gap-3">
                {/* Statistics Cards */}
                <div class="bg-slate-900/60 border border-slate-800 px-3 py-1.5 rounded-xl text-[10px] font-bold text-slate-400 flex items-center gap-1.5">
                  Duration: <span class="text-white font-mono text-xs">{formatTimeStr(getStats().duration)}</span>
                </div>
                <div class="bg-slate-900/60 border border-slate-800 px-3 py-1.5 rounded-xl text-[10px] font-bold text-slate-400 flex items-center gap-1.5">
                  Speakers: <span class="text-white text-xs">{getStats().speakers}</span>
                </div>
                <div class="bg-slate-900/60 border border-slate-800 px-3 py-1.5 rounded-xl text-[10px] font-bold text-slate-400 flex items-center gap-1.5">
                  Characters: <span class="text-white font-mono text-xs">{getStats().characters}</span>
                </div>
              </div>
            </Show>
          </div>

          <div class="flex-1 overflow-y-auto p-6 custom-scrollbar">
            <Show
              when={projectDetails() && projectDetails().segments.length > 0}
              fallback={
                <div class="flex flex-col items-center justify-center h-full text-slate-500 py-12 border border-dashed border-slate-850 rounded-2xl bg-slate-900/10">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-10 w-10 mb-2.5 text-slate-700 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
                  </svg>
                  <p class="text-xs font-black uppercase tracking-widest text-slate-600">No Dialogue Segments Found</p>
                  <p class="text-[10px] text-slate-650 mt-1">Select or launch a project to display the dubbing logs.</p>
                </div>
              }
            >
              <div class="w-full border border-slate-850/80 rounded-2xl overflow-hidden shadow-2xl bg-slate-950/30">
                <table class="w-full text-left border-collapse text-xs sm:text-sm">
                  <thead>
                    <tr class="bg-[#0f172a]/80 text-slate-400 font-black uppercase tracking-wider text-[10px] border-b border-slate-850">
                      <th class="p-4 w-28">Timeline</th>
                      <th class="p-4 w-28">Speaker</th>
                      <th class="p-4">Original Text</th>
                      <th class="p-4">Khmer Translation Override</th>
                      <th class="p-4 w-44 text-center">Synthesis Trigger</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-slate-900/60">
                    <For each={projectDetails()?.segments}>
                      {(seg) => (
                        <tr class="hover:bg-slate-900/30 transition-colors duration-150 group">
                          <td class="p-4 font-mono text-emerald-400 font-bold whitespace-nowrap">
                            {formatTimeStr(seg.start_time)} <br/>
                            <span class="text-slate-500 font-semibold text-[10px]">→ {formatTimeStr(seg.end_time)}</span>
                          </td>
                          <td class="p-4 whitespace-nowrap">
                            <select
                              value={seg.speaker_id?.toLowerCase() || "male"}
                              onChange={(e) => handleUpdateSegmentSpeaker(seg.id, e.target.value)}
                              class="bg-slate-950 border border-slate-800 hover:border-slate-700/60 rounded-xl px-2.5 py-1.5 text-slate-300 text-xs font-bold focus:outline-none focus:border-emerald-500 transition-all cursor-pointer shadow-inner"
                            >
                              <option value="male">🗣️ Male Voice</option>
                              <option value="female">👧 Female Voice</option>
                              <option value="kid">👶 Kid Voice</option>
                            </select>
                          </td>
                          <td class="p-4 text-slate-300 max-w-xs md:max-w-md font-medium leading-relaxed">
                            {seg.original_text}
                          </td>
                          <td class="p-4">
                            <textarea
                              value={seg.translated_text || ""}
                              onChange={(e) => handleUpdateSegmentText(seg.id, e.target.value)}
                              rows="2"
                              class="w-full bg-slate-950/80 border border-slate-800 hover:border-slate-700/60 focus:border-emerald-500/80 focus:ring-1 focus:ring-emerald-500/20 rounded-xl p-2.5 text-slate-100 text-xs font-semibold resize-none focus:outline-none transition-all duration-200 shadow-inner"
                              placeholder="Input target translation..."
                            />
                          </td>
                          <td class="p-4 text-center">
                            <div class="flex flex-col items-center gap-2">
                              <span class={`text-[9px] font-black px-2.5 py-0.5 rounded-full uppercase tracking-wider border ${
                                seg.status === "synthesized" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                                seg.status === "translated" ? "bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse" :
                                seg.status === "failed" ? "bg-rose-500/10 text-rose-400 border-rose-500/20" :
                                "bg-slate-800 text-slate-400 border-slate-700"
                              }`}>{seg.status}</span>
                              <button
                                onClick={() => handleReRenderSegment(seg.id)}
                                class="bg-slate-900 hover:bg-emerald-500/10 hover:text-emerald-400 border border-slate-800 hover:border-emerald-500/50 text-slate-300 px-2.5 py-1.5 rounded-xl text-[10px] font-black flex items-center gap-1 transition-all duration-200 active:scale-95 cursor-pointer"
                              >
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                                  <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 110 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.005a1 1 0 01.737.824 5.002 5.002 0 009.254 1.671H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd" />
                                </svg>
                                Synthesis Node
                              </button>
                            </div>
                          </td>
                        </tr>
                      )}
                    </For>
                  </tbody>
                </table>
              </div>
            </Show>
          </div>
        </div>

        {/* Action Footer & Visual Carousel */}
        <Show when={projectDetails() && projectDetails().project.status === "completed"}>
          <div class="p-6 border-t border-slate-800/80 bg-[#090f1e]/85 backdrop-blur-md flex flex-col gap-5 relative z-10">
            
            {/* Visual Thumbnail Score Carousel */}
            <div>
              <h3 class="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                <span class="w-1.5 h-1.5 rounded-full bg-indigo-400"></span>
                AI Visual Engagement Highlights (Highest Engagement Frames)
              </h3>
              <div class="flex gap-4 overflow-x-auto pb-2 scrollbar-thin custom-scrollbar">
                <For each={projectDetails()?.thumbnails}>
                  {(thumb) => (
                    <div class="relative w-48 bg-slate-950/80 border border-slate-850 rounded-xl overflow-hidden flex-shrink-0 group shadow-xl">
                      <img
                        src={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/thumbnail/${thumb.filename}`}
                        alt={`Scene score: ${thumb.score}`}
                        class="w-full h-26 object-cover group-hover:scale-105 transition-transform duration-300"
                      />
                      <div class="absolute top-2 left-2 bg-gradient-to-r from-amber-400 to-orange-500 text-slate-950 text-[9px] font-black px-1.5 py-0.5 rounded shadow-lg flex items-center gap-0.5">
                        ★ {thumb.score.toFixed(1)}
                      </div>
                      <div class="absolute bottom-2 right-2 bg-black/85 text-slate-300 text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border border-slate-800">
                        {formatTimeStr(thumb.timestamp)}
                      </div>
                      <div class="p-2 bg-slate-900/40 text-center border-t border-slate-900/60">
                        <a
                          href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/thumbnail/${thumb.filename}`}
                          download
                          class="text-[10px] text-emerald-400 hover:text-emerald-300 font-extrabold uppercase tracking-wide block transition-colors"
                        >
                          Save Frame
                        </a>
                      </div>
                    </div>
                  )}
                </For>
              </div>
            </div>

            {/* Final Export Download Anchors */}
            <div class="flex flex-col sm:flex-row items-center justify-between gap-4 border-t border-slate-800/80 pt-4">
              <div class="flex items-center gap-2">
                <span class="relative flex h-3 w-3">
                  <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                </span>
                <span class="text-xs text-slate-300 font-black uppercase tracking-wider">Khmer Dubbed Production Assets Ready</span>
              </div>
              
              <div class="flex flex-wrap gap-2.5">
                <a
                  href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/video/16_9`}
                  target="_blank"
                  class="bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-slate-950 font-black px-5 py-2.5 rounded-xl shadow-lg shadow-emerald-500/10 hover:shadow-emerald-500/25 flex items-center gap-1.5 text-xs transition-all duration-300 active:scale-95"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Video (16:9)
                </a>

                <Show when={projectDetails()?.project.generate_shorts}>
                  <a
                    href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/video/9_16`}
                    target="_blank"
                    class="bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-100 font-black px-5 py-2.5 rounded-xl flex items-center gap-1.5 text-xs transition-all duration-300 active:scale-95"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
                    </svg>
                    Shorts (9:16)
                  </a>
                </Show>

                <a
                  href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/audio/mp3`}
                  target="_blank"
                  class="bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-100 font-black px-5 py-2.5 rounded-xl flex items-center gap-1.5 text-xs transition-all duration-300 active:scale-95"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                  </svg>
                  Export MP3
                </a>

                <a
                  href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/subtitles/srt`}
                  target="_blank"
                  class="bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-100 font-black px-5 py-2.5 rounded-xl flex items-center gap-1.5 text-xs transition-all duration-300 active:scale-95"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
                  </svg>
                  Export SRT
                </a>
              </div>
            </div>

          </div>
        </Show>
        
      </div>
    </div>
  );
}

export default App;
