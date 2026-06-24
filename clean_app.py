import os

app_path = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"

with open(app_path, "r", encoding="utf-8") as f:
    text = f.read()

# Strip "playing" and whitespace from the end
text = text.rstrip()
if text.endswith("playing"):
    text = text[:-len("playing")].rstrip()

# Apply 100-chunk logic
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

if old_str in text:
    text = text.replace(old_str, new_str)
    print("Chunk logic applied!")
else:
    print("Old string not found for chunk logic, maybe already applied or different.")

with open(app_path, "w", encoding="utf-8") as f:
    f.write(text)
print("Saved cleanly!")
