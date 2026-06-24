import os

filepath = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

end_marker = """                                {/* Part Completion / Export Controls */}"""
idx = text.find(end_marker)

if idx == -1:
    print("Could not find end marker")
    exit(1)

text = text[:idx]

replacement = """                                {/* Part Completion / Export Controls */}
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
                      </div>
                    );
                  })()}
                </div>
        </main>
      </div>
    </div>
  );
}

export default App;
"""

with open(filepath, "w", encoding="utf-8") as f:
    f.write(text + replacement)

print("Balanced tags successfully!")
