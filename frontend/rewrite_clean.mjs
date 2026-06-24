import fs from 'fs';
import * as parser from '@babel/parser';

let code = fs.readFileSync('Z:/year3/projecj video translate backup/frontend/src/App.jsx', 'utf-8');

const idx1 = code.indexOf('{/* Part Selector Buttons */}');
const idx = code.lastIndexOf('return (', idx1);

if (idx === -1) {
    console.log("Could not find the IIFE return!");
    process.exit(1);
}

// Slice code right before the IIFE return
code = code.substring(0, idx);

let replacement = `return (
                      <div class="space-y-4">
                        <div class="flex flex-wrap gap-2 pb-3 border-b border-slate-850/40">
                          <For each={Array.from({ length: numBatches }, (_, i) => i + 1)}>
                            {(partNum) => {
                              const startIdx = (partNum - 1) * batchSize;
                              const endIdx = Math.min(startIdx + batchSize, segs.length);
                              return (
                                <button
                                  type="button"
                                  onClick={() => setActiveBatchIndex(partNum)}
                                  class={\`px-3 py-1.5 rounded-lg text-xs font-black uppercase transition-all \${activeBatchIndex() === partNum ? "bg-amber-500 text-slate-900" : "bg-slate-800 text-slate-300"}\`}
                                >
                                  Part {partNum}
                                </button>
                              );
                            }}
                          </For>
                        </div>
                        <Show when={activeBatchSegments().length > 0}>
                           <div class="space-y-3 max-h-[50vh] overflow-y-auto pr-2 custom-scrollbar">
                              <For each={activeBatchSegments()}>
                                {(seg) => (
                                  <div class="bg-slate-900/50 p-4 rounded-xl border border-white/5">
                                    <div class="text-[10px] text-emerald-400 font-mono mb-1">[{seg.start_time.toFixed(2)}s - {seg.end_time.toFixed(2)}s] Speaker: {seg.speaker_id}</div>
                                    <div class="text-xs text-slate-400 italic mb-2">{seg.original_text}</div>
                                    <textarea
                                      value={seg.translated_text || ""}
                                      onInput={(e) => {
                                        const newSegs = [...manualTranslationSegments()];
                                        const i = newSegs.findIndex(s => s.segment_id === seg.segment_id);
                                        if (i !== -1) newSegs[i].translated_text = e.target.value;
                                        setManualTranslationSegments(newSegs);
                                      }}
                                      class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none focus:border-amber-500"
                                      rows="2"
                                      placeholder="Translate to Khmer..."
                                    />
                                  </div>
                                )}
                              </For>
                           </div>
                           <button type="button" class="w-full py-3 mt-4 bg-amber-500 hover:bg-amber-400 text-slate-900 font-black rounded-xl text-sm" onClick={() => alert("Ready to submit!")}>
                             SUBMIT TRANSLATIONS
                           </button>
                        </Show>
                      </div>
                    );
                  })()}
                </div>
              </Show>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
export default App;
`;

let testCode = code + replacement;

for (let i = 0; i < 30; i++) {
  try {
     parser.parse(testCode, { sourceType: 'module', plugins: ['jsx'] });
     console.log('SUCCESS! PERFECTLY BALANCED!');
     fs.writeFileSync('src/App.jsx', testCode);
     process.exit(0);
  } catch(e) {
     if (e.message.includes('Expected corresponding JSX closing tag for <')) {
         let match = e.message.match(/for <(.*?)>/);
         let tag = `</${match[1]}>`;
         testCode = testCode.replace(/\s*\);\s*}\s*export default App;\s*$/, `\\n${tag}\\n  );\\n}\\nexport default App;\\n`);
     } else if (e.message.includes('Unexpected token, expected "}"')) {
         testCode = testCode.replace(/\s*\);\s*}\s*export default App;\s*$/, `\\n}\\n  );\\n}\\nexport default App;\\n`);
     } else if (e.message.includes('Unexpected token')) {
         testCode = testCode.replace(/<\/div>\s*\n\s*\);\s*}\s*export default App;\s*$/, `\\n  );\\n}\\nexport default App;\\n`);
     } else {
         console.log("Failed with:", e.message);
         process.exit(1);
     }
  }
}
console.log("Failed to balance!");
