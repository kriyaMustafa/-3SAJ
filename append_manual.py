import os

app_path = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"
backup_path = r"C:\Users\3SAJ\AppData\Roaming\Code\User\History\66c5cf81\hvWP.jsx"

with open(backup_path, "r", encoding="utf-8") as f:
    text = f.read()

text = text.rstrip()
if text.endswith("playing"):
    append_str = """() === seg.segment_id
                                                    ? "bg-amber-500 text-slate-900 border-amber-400"
                                                    : "bg-slate-900 text-slate-300 border-white/10 hover:bg-slate-800"
                                                }`}
                                              >
                                                <Show when={playing() === seg.segment_id} fallback="▶ Play">
                                                  <span class="animate-pulse">Playing</span>
                                                </Show>
                                              </button>
                                            </div>
                                          </div>
                                        </div>
                                      );
                                    }}
                                  </For>
                                </div>

                                {/* Part Completion / Export Controls */}
                                <div class="mt-4 flex flex-col sm:flex-row gap-3 pt-3 border-t border-white/5">
                                  <button
                                    type="button"
                                    onClick={() => alert("Submit parts clicked!")}
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
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(text + append_str)
    print("Manual append successful.")
else:
    print("Does not end with playing!")
