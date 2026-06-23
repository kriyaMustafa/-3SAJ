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

  const API_HOST = typeof window !== "undefined" 
    ? `${window.location.hostname === "localhost" ? "127.0.0.1" : window.location.hostname}:8000` 
    : "127.0.0.1:8000";
  const httpProtocol = "http://";
  const wsProtocol = "ws://";

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
        // Sync static pipeline state if socket isn't running
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

  // Smart API polling loop — fetches real status FIRST before deciding to poll
  createEffect(() => {
    const id = selectedProjectId();
    if (!id) return;

    const TERMINAL_STATES = ["completed", "failed", "cancelled"];
    let timerId = null;
    let stopped = false;
    let currentDelay = 4000;
    const maxDelay = 15000;
    const backoffMultiplier = 1.5;
    let lastStatus = null;

    const applyData = (data) => {
      setProjectDetails(data);
      const status = data.project.status;
      setPipelineState({
        status: status,
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
      if (status !== lastStatus) {
        fetchProjects();
        lastStatus = status;
      }
      return status;
    };

    const poll = async () => {
      if (stopped) return;
      try {
        const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${id}`);
        if (res.ok) {
          const data = await res.json();
          const status = applyData(data);
          currentDelay = 4000; // reset on success

          if (TERMINAL_STATES.includes(status)) {
            console.log(`[Polling] Project ${id} reached terminal state "${status}". Polling stopped.`);
            stopped = true;
            return; // ← do NOT schedule next poll
          }
        } else {
          currentDelay = Math.min(currentDelay * backoffMultiplier, maxDelay);
          console.warn(`[Polling] Non-OK response. Backing off to ${currentDelay}ms`);
        }
      } catch (err) {
        currentDelay = Math.min(currentDelay * backoffMultiplier, maxDelay);
        console.error(`[Polling] Network error. Backing off to ${currentDelay}ms`, err);
      }
      if (!stopped) {
        timerId = setTimeout(poll, currentDelay);
      }
    };

    // ── CRITICAL FIX: always fetch real status first, THEN decide whether to poll ──
    const bootstrap = async () => {
      try {
        const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${id}`);
        if (res.ok) {
          const data = await res.json();
          const status = applyData(data);
          if (TERMINAL_STATES.includes(status)) {
            console.log(`[Polling] Project ${id} already terminal ("${status}"). Polling will NOT start.`);
            stopped = true;
            return; // ← project is done, never schedule any poll
          }
        }
      } catch (e) {
        console.error("[Polling] Bootstrap fetch failed:", e);
      }
      // Only reach here if status is non-terminal
      if (!stopped) {
        console.log(`[Polling] Project ${id} is active. Starting poll loop (${currentDelay}ms interval).`);
        timerId = setTimeout(poll, currentDelay);
      }
    };

    bootstrap();

    onCleanup(() => {
      stopped = true;
      if (timerId) clearTimeout(timerId);
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
    const minutes = Math.floor(sec / 60);
    const seconds = Math.floor(sec % 60);
    const ms = Math.floor((sec - Math.floor(sec)) * 100);
    return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}.${ms.toString().padStart(2, "0")}`;
  };

  // Define steps for progress visualization
  const pipelineSteps = [
    { key: "ingesting", label: "Ingesting Video & Splitting" },
    { key: "stemming", label: "Vocal Stem Separation" },
    { key: "transcribing", label: "Speech Transcription" },
    { key: "translating", label: "Gemini Translation" },
    { key: "synthesizing", label: "VoxCPM2 Speech Synthesis" },
    { key: "exporting", label: "BGM Mixing & Subtitle Rendering" },
    { key: "completed", label: "Pipeline Completed" }
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

  return (
    <div class="flex h-screen bg-[#0f172a] text-slate-100 overflow-hidden">
      
      {/* Sidebar - Projects Registry List */}
      <div class="w-72 bg-[#1e293b] border-r border-slate-700 flex flex-col justify-between">
        <div>
          <div class="p-6 border-b border-slate-700 flex items-center gap-3">
            <div class="bg-emerald-500 text-slate-900 p-2 rounded-lg">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </div>
            <div>
              <h1 class="text-xl font-bold tracking-tight text-white">VocalTransl8</h1>
              <p class="text-xs text-emerald-400 font-medium">Khmer Recap Pipeline</p>
            </div>
          </div>
          <div class="p-4">
            <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Project Registry</h2>
            <div class="space-y-1 overflow-y-auto max-h-[60vh] pr-1">
              <For each={projects()}>
                {(proj) => (
                  <div
                    onClick={() => setSelectedProjectId(proj.id)}
                    class={`relative group w-full text-left p-3 rounded-lg flex flex-col cursor-pointer transition-all duration-200 ${
                      selectedProjectId() === proj.id 
                        ? "bg-emerald-500/10 border-l-4 border-emerald-500 text-white font-medium" 
                        : "hover:bg-slate-800 text-slate-300"
                    }`}
                  >
                    <div class="flex items-start justify-between">
                      <span class="text-sm truncate w-40 font-semibold">{proj.name}</span>
                      <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                        {/* Cancel Button */}
                        {["pending", "ingesting", "stemming", "transcribing", "translating", "synthesizing", "exporting"].includes(proj.status) && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleCancelProject(proj.id);
                            }}
                            title="Cancel / Stop Pipeline"
                            class="p-0.5 text-slate-400 hover:text-amber-500 hover:bg-slate-700/50 rounded transition-colors"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                          </button>
                        )}
                        {/* Delete Button */}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteProject(proj.id);
                          }}
                          title="Delete Project"
                          class="p-0.5 text-slate-400 hover:text-rose-500 hover:bg-slate-700/50 rounded transition-colors"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    </div>
                    <div class="flex items-center justify-between w-full mt-1.5">
                      <span class="text-xs text-slate-400">{proj.genre_mode === "anime_recap" ? "Anime Recap" : "Drama Recap"}</span>
                      <span class={`text-[10px] px-1.5 py-0.5 rounded-full font-bold uppercase ${
                        proj.status === "completed" ? "bg-emerald-500/20 text-emerald-400" :
                        proj.status === "failed" ? "bg-rose-500/20 text-rose-400" :
                        proj.status === "cancelled" ? "bg-slate-600/30 text-slate-400" :
                        "bg-amber-500/20 text-amber-400 animate-pulse"
                      }`}>{proj.status}</span>
                    </div>
                  </div>
                )}
              </For>
            </div>
          </div>
        </div>

        <div class="p-4 border-t border-slate-700 bg-slate-900 text-center">
          <p class="text-[11px] text-slate-500">MSI Pulse 15 Laptop Hardware Node</p>
          <div class="flex items-center justify-center gap-1.5 mt-1">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
            <span class="text-xs text-slate-400">8GB VRAM Optimizer Active</span>
          </div>
        </div>
      </div>

      {/* Main Core Dashboard Grid */}
      <div class="flex-1 flex flex-col overflow-hidden">
        
        <div class="p-6 border-b border-slate-800 bg-[#1e293b]/50 overflow-y-auto max-h-[45vh]">
          <div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
            
            {/* Source Ingestion Tabs */}
            <div class="bg-slate-900/60 border border-slate-700 rounded-xl p-5 shadow-2xl">
              <h2 class="text-md font-bold mb-4 flex items-center gap-2 text-white">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                </svg>
                Launch New Translation Pipeline
              </h2>
              <form onSubmit={handleStartPipeline} class="space-y-4">
                
                {/* Tabs selection */}
                <div class="flex bg-slate-800 p-1 rounded-lg border border-slate-700">
                  <button
                    type="button"
                    onClick={() => setActiveTab("url")}
                    class={`flex-1 text-center py-2 text-sm rounded-md transition-all font-medium ${
                      activeTab() === "url" ? "bg-emerald-500 text-slate-900 font-bold" : "text-slate-400 hover:text-white"
                    }`}
                  >
                    Remote Stream URL
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("local")}
                    class={`flex-1 text-center py-2 text-sm rounded-md transition-all font-medium ${
                      activeTab() === "local" ? "bg-emerald-500 text-slate-900 font-bold" : "text-slate-400 hover:text-white"
                    }`}
                  >
                    Drag & Drop Upload
                  </button>
                </div>

                <Show when={activeTab() === "url"}>
                  <div class="space-y-1">
                    <label class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Video Stream Web URL</label>
                    <input
                      type="url"
                      placeholder="e.g. YouTube, TikTok, Direct MP4 link"
                      value={videoUrl()}
                      onInput={(e) => setVideoUrl(e.target.value)}
                      class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                </Show>

                <Show when={activeTab() === "local"}>
                  <div class="space-y-1">
                    <label class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Upload Local Media</label>
                    <div class="border-2 border-dashed border-slate-700 hover:border-emerald-500 rounded-lg p-6 text-center cursor-pointer transition-all duration-300 bg-slate-800/40">
                      <input
                        type="file"
                        accept="video/*"
                        onChange={handleFileChange}
                        class="hidden"
                        id="fileUploadInput"
                      />
                      <label for="fileUploadInput" class="cursor-pointer">
                        <svg xmlns="http://www.w3.org/2000/svg" class="mx-auto h-8 w-8 text-slate-400 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                        </svg>
                        <span class="text-sm font-semibold block text-slate-200">
                          {localFile() ? localFile().name : "Choose file or drag here"}
                        </span>
                        <span class="text-xs text-slate-500 mt-1 block">Supports up to 2GB MP4, MKV, AVI</span>
                      </label>
                    </div>
                  </div>
                </Show>

                {/* Configuration Options */}
                <div class="grid grid-cols-2 gap-4">
                  <div class="space-y-1">
                    <label class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Target Language</label>
                    <select
                      value={targetLang()}
                      onChange={(e) => setTargetLang(e.target.value)}
                      class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                    >
                      <option value="km">Khmer (default)</option>
                      <option value="en">English</option>
                      <option value="es">Spanish</option>
                      <option value="zh">Chinese</option>
                      <option value="vi">Vietnamese</option>
                    </select>
                  </div>
                  <div class="space-y-1">
                    <label class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Genre Setting</label>
                    <select
                      value={genreMode()}
                      onChange={(e) => setGenreMode(e.target.value)}
                      class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                    >
                      <option value="anime_recap">Anime Mode (Fast/Punchy)</option>
                      <option value="drama_recap">Drama Mode (Dramatic/Steady)</option>
                    </select>
                  </div>
                </div>

                <div class="flex items-center justify-between pt-2">
                  <div class="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="shortsCheckbox"
                      checked={generateShorts()}
                      onChange={(e) => setGenerateShorts(e.target.checked)}
                      class="w-4 h-4 text-emerald-500 border-slate-700 rounded focus:ring-emerald-500 bg-slate-800"
                    />
                    <label for="shortsCheckbox" class="text-sm text-slate-300 select-none">Generate TikTok/Shorts (9:16)</label>
                  </div>
                  <button
                    type="submit"
                    disabled={isSubmitting()}
                    class="bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 text-slate-900 font-bold px-5 py-2.5 rounded-lg shadow-lg hover:shadow-emerald-500/10 flex items-center gap-2 text-sm transition-all duration-300"
                  >
                    {isSubmitting() ? "Starting..." : "Begin Pipeline"}
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                      <path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd" />
                    </svg>
                  </button>
                </div>
              </form>
            </div>

            {/* Panel A: Media Player Preview */}
            <div class="bg-slate-900/60 border border-slate-700 rounded-xl p-5 shadow-2xl flex flex-col justify-between">
              <div>
                <h2 class="text-md font-bold mb-4 flex items-center gap-2 text-white">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Panel A: Media Player Preview
                </h2>
                
                <Show
                  when={selectedProjectId() && projectDetails()}
                  fallback={
                    <div class="bg-slate-950/80 rounded-lg aspect-video flex flex-col items-center justify-center text-slate-500 border border-slate-800 h-44">
                      <p class="text-xs">Select or start a project to preview</p>
                    </div>
                  }
                >
                  <div class="relative rounded-lg overflow-hidden aspect-video bg-black border border-slate-800 mb-4 h-44 flex items-center justify-center">
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
                  
                  <div class="flex items-center justify-between gap-2">
                    <div class="flex bg-slate-800 p-1 rounded-lg border border-slate-700">
                      <button
                        type="button"
                        onClick={() => setPreviewMode("original")}
                        class={`px-3 py-1.5 text-xs rounded transition-all font-semibold ${
                          previewMode() === "original" ? "bg-slate-700 text-white font-bold" : "text-slate-400 hover:text-white"
                        }`}
                      >
                        Original
                      </button>
                      <button
                        type="button"
                        disabled={projectDetails()?.project.status !== "completed"}
                        onClick={() => setPreviewMode("dubbed")}
                        class={`px-3 py-1.5 text-xs rounded transition-all font-semibold ${
                          previewMode() === "dubbed" ? "bg-emerald-500 text-slate-950 font-bold" : "text-slate-400 hover:text-white disabled:opacity-50"
                        }`}
                      >
                        Khmer Dubbed
                      </button>
                    </div>
                    
                    <span class="text-[11px] text-slate-400 font-medium">
                      Audio: <span class="text-white font-bold capitalize">{previewMode()}</span>
                    </span>
                  </div>
                </Show>
              </div>
            </div>

            {/* Real-time Pipeline Progress Tracker */}
            <div class="bg-slate-900/60 border border-slate-700 rounded-xl p-5 shadow-2xl flex flex-col justify-between">
              <div>
                <h2 class="text-md font-bold mb-3.5 flex items-center justify-between text-white">
                  <span class="flex items-center gap-2">
                    <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping"></span>
                    Worker Cluster Status
                  </span>
                  <span class="text-emerald-400 font-mono text-sm">{pipelineState().progress}%</span>
                </h2>
                
                <div class="w-full bg-slate-800 rounded-full h-2.5 mb-6 overflow-hidden border border-slate-700">
                  <div
                    class="bg-emerald-500 h-2.5 rounded-full transition-all duration-500"
                    style={{ width: `${pipelineState().progress}%` }}
                  ></div>
                </div>

                <div class="space-y-3.5">
                  <For each={pipelineSteps}>
                    {(step) => {
                      const status = getStepStatus(step.key);
                      return (
                        <div class="flex items-center justify-between text-xs sm:text-sm">
                          <div class="flex items-center gap-3">
                            <span class={`w-5 h-5 rounded-full flex items-center justify-center font-bold text-[10px] ${
                              status === "completed" ? "bg-emerald-500 text-slate-900" :
                              status === "active" ? "bg-amber-500 text-slate-900 animate-pulse" :
                              status === "failed" ? "bg-rose-500 text-white" :
                              "bg-slate-800 text-slate-500 border border-slate-700"
                            }`}>
                              {status === "completed" ? "✓" : "!"}
                            </span>
                            <span class={`font-medium ${
                              status === "active" ? "text-amber-400" :
                              status === "completed" ? "text-slate-200" :
                              status === "failed" ? "text-rose-400" :
                              "text-slate-500"
                            }`}>{step.label}</span>
                          </div>
                          <span class={`text-[10px] font-bold uppercase tracking-wider ${
                            status === "completed" ? "text-emerald-400" :
                            status === "active" ? "text-amber-400" :
                            status === "failed" ? "text-rose-400" :
                            "text-slate-600"
                          }`}>{status}</span>
                        </div>
                      );
                    }}
                  </For>
                </div>
              </div>

              <div class="grid grid-cols-2 gap-4 mt-6 pt-4 border-t border-slate-800 text-xs text-slate-400 font-semibold">
                <div class="flex justify-between items-center bg-slate-800/40 p-2.5 rounded-lg border border-slate-800">
                  <span>60s Video Chunks:</span>
                  <span class="text-white font-mono">{pipelineState().chunks.completed} / {pipelineState().chunks.total}</span>
                </div>
                <div class="flex justify-between items-center bg-slate-800/40 p-2.5 rounded-lg border border-slate-800">
                  <span>Subtitle Lines Dubbed:</span>
                  <span class="text-white font-mono">{pipelineState().segments.completed} / {pipelineState().segments.total}</span>
                </div>
              </div>

            </div>

          </div>
        </div>

        {/* Interactive Translation Edit Grid */}
        <div class="flex-1 flex flex-col min-h-0 bg-[#0f172a] border-t border-slate-800">
          <div class="px-6 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/40">
            <div>
              <h2 class="text-lg font-bold text-white">Interactive Segment Script Workspace</h2>
              <p class="text-xs text-slate-400">Review transcription, customize Khmer translation overrides, and trigger selective node audio updates.</p>
            </div>
            <div class="bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-lg text-xs flex gap-4 text-slate-300 font-medium">
              <span>Selected Project ID: <span class="font-mono text-white text-xs">{selectedProjectId() ? selectedProjectId().substring(0, 8) : "None"}</span></span>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto p-6">
            <Show
              when={projectDetails() && projectDetails().segments.length > 0}
              fallback={
                <div class="flex flex-col items-center justify-center h-full text-slate-500 py-12">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mb-3 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
                  </svg>
                  <p class="text-sm font-semibold">No transcript segments found.</p>
                  <p class="text-xs text-slate-600 mt-1">Start a new pipeline or select a registry item to inspect logs.</p>
                </div>
              }
            >
              <div class="w-full border border-slate-800 rounded-xl overflow-hidden shadow-xl bg-slate-900/40">
                <table class="w-full text-left border-collapse text-xs sm:text-sm">
                  <thead>
                    <tr class="bg-slate-800 text-slate-300 font-semibold uppercase tracking-wider text-xs border-b border-slate-700">
                      <th class="p-4 w-28">Timestamp</th>
                      <th class="p-4 w-28">Speaker</th>
                      <th class="p-4">Original Translation</th>
                      <th class="p-4">Khmer Dubbing Script</th>
                      <th class="p-4 w-44 text-center">Execution Control</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-slate-800">
                    <For each={projectDetails()?.segments}>
                      {(seg) => (
                        <tr class="hover:bg-slate-800/40 transition-colors duration-150">
                          <td class="p-4 font-mono text-emerald-400 font-semibold whitespace-nowrap">
                            {formatTimeStr(seg.start_time)} <br/>
                            <span class="text-slate-500 font-normal">→ {formatTimeStr(seg.end_time)}</span>
                          </td>
                          <td class="p-4 whitespace-nowrap">
                            <select
                              value={seg.speaker_id?.toLowerCase() || "male"}
                              onChange={(e) => handleUpdateSegmentSpeaker(seg.id, e.target.value)}
                              class="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-300 text-xs font-semibold focus:outline-none focus:border-emerald-500 hover:border-slate-600 transition-colors cursor-pointer"
                            >
                              <option value="male">Male Voice</option>
                              <option value="female">Female Voice</option>
                              <option value="kid">Kid Voice</option>
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
                              class="w-full bg-slate-900 border border-slate-700 hover:border-slate-600 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 rounded-lg p-2 text-slate-100 text-xs sm:text-sm resize-none focus:outline-none transition-all duration-200"
                              placeholder="Type Khmer translation here..."
                            />
                          </td>
                          <td class="p-4 text-center">
                            <div class="flex flex-col items-center gap-2">
                              <span class={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                                seg.status === "synthesized" ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/20" :
                                seg.status === "translated" ? "bg-amber-500/20 text-amber-400 border border-amber-500/20 animate-pulse" :
                                seg.status === "failed" ? "bg-rose-500/20 text-rose-400 border border-rose-500/20" :
                                "bg-slate-700/20 text-slate-400 border border-slate-700/20"
                              }`}>{seg.status}</span>
                              <button
                                onClick={() => handleReRenderSegment(seg.id)}
                                class="bg-slate-800 hover:bg-emerald-500/10 hover:text-emerald-400 border border-slate-700 hover:border-emerald-500 text-slate-300 px-3 py-1.5 rounded-md text-xs font-semibold flex items-center gap-1 transition-all duration-200"
                              >
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                                  <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 110 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.005a1 1 0 01.737.824 5.002 5.002 0 009.254 1.671H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd" />
                                </svg>
                                Render Segment
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
          <div class="p-6 border-t border-slate-800 bg-[#1e293b]/70 flex flex-col gap-6">
            
            {/* Visual Thumbnail Score Carousel */}
            <div>
              <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider mb-3">AI Vision Scored Thumbnails (Top Engagement Scenes)</h3>
              <div class="flex gap-4 overflow-x-auto pb-2 scrollbar-thin">
                <For each={projectDetails()?.thumbnails}>
                  {(thumb) => (
                    <div class="relative w-48 bg-slate-900 border border-slate-700 rounded-lg overflow-hidden flex-shrink-0 group">
                      <img
                        src={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/thumbnail/${thumb.filename}`}
                        alt={`Scored: ${thumb.score}`}
                        class="w-full h-28 object-cover group-hover:scale-105 transition-transform duration-300"
                      />
                      <div class="absolute top-2 left-2 bg-emerald-500 text-slate-955 text-[10px] font-bold px-1.5 py-0.5 rounded shadow">
                        ★ {thumb.score.toFixed(1)}
                      </div>
                      <div class="absolute bottom-2 right-2 bg-black/70 text-slate-300 text-[10px] font-mono px-1.5 py-0.5 rounded">
                        {formatTimeStr(thumb.timestamp)}
                      </div>
                      <div class="p-2 text-center">
                        <a
                          href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/thumbnail/${thumb.filename}`}
                          download
                          class="text-xs text-emerald-400 hover:text-emerald-300 font-bold block"
                        >
                          Download Thumbnail
                        </a>
                      </div>
                    </div>
                  )}
                </For>
              </div>
            </div>

            {/* Final Export Download Anchors */}
            <div class="flex flex-col sm:flex-row items-center justify-between gap-4 border-t border-slate-800 pt-4">
              <div class="flex items-center gap-2">
                <span class="w-3 h-3 rounded-full bg-emerald-500"></span>
                <span class="text-sm text-slate-300 font-semibold">Khmer Dubbed Production Assets Ready for Publishing!</span>
              </div>
              <div class="flex flex-wrap gap-3">
                <a
                  href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/video/16_9`}
                  target="_blank"
                  class="bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold px-5 py-2.5 rounded-lg shadow-lg hover:shadow-emerald-500/10 flex items-center gap-2 text-sm transition-all duration-300"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download Video (16:9)
                </a>

                <Show when={projectDetails()?.project.generate_shorts}>
                  <a
                    href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/video/9_16`}
                    target="_blank"
                    class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-100 font-bold px-5 py-2.5 rounded-lg flex items-center gap-2 text-sm transition-all duration-300"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
                    </svg>
                    Download Shorts (9:16)
                  </a>
                </Show>

                <a
                  href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/audio/mp3`}
                  target="_blank"
                  class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-100 font-bold px-5 py-2.5 rounded-lg flex items-center gap-2 text-sm transition-all duration-300"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                  </svg>
                  Export MP3
                </a>

                <a
                  href={`${httpProtocol}${API_HOST}/api/downloads/${selectedProjectId()}/subtitles/srt`}
                  target="_blank"
                  class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-100 font-bold px-5 py-2.5 rounded-lg flex items-center gap-2 text-sm transition-all duration-300"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
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
