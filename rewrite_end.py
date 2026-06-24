import os

filepath = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    lines = f.readlines()

start_idx = -1
for i, line in enumerate(lines):
    if "<For each={partSegments}>" in line:
        start_idx = i
        break

if start_idx == -1:
    print("Could not find partSegments!")
    exit(1)

replacement = """                                  <For each={partSegments}>
                                    {(seg) => {
                                      return (
                                        <div class="rounded-xl border border-white/5 bg-slate-950/40 p-4 shadow-inner mb-4">
                                            <div class="flex justify-between items-center mb-2">
                                                <div class="text-xs text-slate-300 font-mono">
                                                    [{seg.start_time.toFixed(2)}s - {seg.end_time.toFixed(2)}s] 
                                                    <span class="ml-2 text-emerald-400">Speaker: {seg.speaker_id}</span>
                                                </div>
                                            </div>
                                            <div class="text-xs text-slate-400 mb-2 italic">
                                                Original: {seg.original_text}
                                            </div>
                                            <textarea
                                              value={seg.translated_text || ""}
                                              onInput={(e) => {
                                                const newSegs = [...manualTranslationSegments()];
                                                const idx = newSegs.findIndex(s => s.segment_id === seg.segment_id);
                                                if (idx !== -1) newSegs[idx].translated_text = e.target.value;
                                                setManualTranslationSegments(newSegs);
                                              }}
                                              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-slate-200 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 transition-all outline-none"
                                              rows="2"
                                              placeholder="Khmer translation..."
                                            />
                                        </div>
                                      );
                                    }}
                                  </For>
                                </div>

                                {/* Part Completion / Export Controls */}
                                <div class="mt-4 flex flex-col sm:flex-row gap-3 pt-3 border-t border-white/5">
                                  <button
                                    type="button"
                                    onClick={() => alert("Submit all parts to backend!")}
                                    class={`flex-1 py-2 rounded-xl text-xs font-black uppercase tracking-wider transition-all duration-300 flex items-center justify-center gap-2 bg-amber-500 hover:bg-amber-400 text-slate-900 shadow-lg shadow-amber-500/20`}
                                  >
                                    Submit All Parts
                                  </button>
                                </div>
                              </div>
                            </div>
                          </div>
                        </Show>
                      </div>
                    );
                  })()}
                </div>
              </Show>
            </div>
          </Show>
        </main>
      </div>
    </div>
  );
}

export default App;
"""

lines = lines[:start_idx]
with open(filepath, "w", encoding="utf-8") as f:
    f.writelines(lines)
    f.write(replacement)

print("Rewrote end successfully!")
