import os

filepath = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

old_str = """                    const segs = manualTranslationSegments();
                    const batchSize = 10;
                    const numBatches = Math.ceil(segs.length / batchSize);
                    
                    return (
                      <div class="space-y-4">
                        {/* Part Selector Buttons */}
                        <div class="flex flex-wrap gap-2 pb-3 border-b border-slate-850/40">
                          <For each={Array.from({ length: numBatches }, (_, i) => i + 1)}>
                            {(partNum) => {
                              const startIdx = (partNum - 1) * batchSize;
                              const endIdx = Math.min(startIdx + batchSize, segs.length);
                              const isCompleted = () => segs.slice(startIdx, endIdx).every(s => s.translated_text && s.translated_text.trim());
                              return (
                                <button
                                  type="button"
                                  onClick={() => setActiveBatchIndex(partNum)}
                                  class={`px-3 py-1.5 rounded-lg text-xs font-black uppercase tracking-wider transition-all duration-200 border cursor-pointer flex items-center gap-1.5 ${
                                    activeBatchIndex() === partNum
                                      ? "bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-lg shadow-amber-500/5"
                                      : "bg-slate-950/40 text-slate-400 border-white/5 hover:bg-slate-950/60"
                                  }`}
                                >
                                  Part {partNum} ({startIdx + 1}-{endIdx})
                                  <Show when={isCompleted()}>
                                    <span class="text-emerald-400 font-extrabold text-[10px]">✓</span>
                                  </Show>
                                </button>
                              );
                            }}
                          </For>"""

new_str = """                    const segs = manualTranslationSegments();
                    const batchSize = 100;
                    const numBatches = Math.ceil(segs.length / batchSize);
                    
                    return (
                      <div class="space-y-4">
                        {/* Part Selector Buttons */}
                        <div class="flex flex-wrap gap-2 pb-3 border-b border-slate-850/40">
                          <For each={Array.from({ length: numBatches }, (_, i) => i + 1)}>
                            {(partNum) => {
                              const startIdx = (partNum - 1) * batchSize;
                              const endIdx = Math.min(startIdx + batchSize, segs.length);
                              const isCompleted = () => segs.slice(startIdx, endIdx).every(s => s.translated_text && s.translated_text.trim());
                              
                              const prevStartIdx = (partNum - 2) * batchSize;
                              const prevEndIdx = Math.min(prevStartIdx + batchSize, segs.length);
                              const isPrevCompleted = () => partNum === 1 || segs.slice(prevStartIdx, prevEndIdx).every(s => s.translated_text && s.translated_text.trim());
                              
                              const disabled = !isPrevCompleted();

                              return (
                                <button
                                  type="button"
                                  disabled={disabled}
                                  onClick={() => setActiveBatchIndex(partNum)}
                                  class={`px-3 py-1.5 rounded-lg text-xs font-black uppercase tracking-wider transition-all duration-200 border flex items-center gap-1.5 ${
                                    activeBatchIndex() === partNum
                                      ? "bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-lg shadow-amber-500/5"
                                      : disabled
                                        ? "bg-slate-900/20 text-slate-600 border-white/5 cursor-not-allowed opacity-50"
                                        : "bg-slate-950/40 text-slate-400 border-white/5 hover:bg-slate-950/60 cursor-pointer"
                                  }`}
                                >
                                  Part {partNum} ({startIdx + 1}-{endIdx})
                                  <Show when={disabled}>
                                    <span class="text-slate-600 text-[10px]">🔒</span>
                                  </Show>
                                  <Show when={isCompleted()}>
                                    <span class="text-emerald-400 font-extrabold text-[10px]">✓</span>
                                  </Show>
                                </button>
                              );
                            }}
                          </For>"""

if old_str in content:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content.replace(old_str, new_str))
    print("Success")
else:
    print("Not found")
