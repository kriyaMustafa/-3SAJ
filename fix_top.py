import os
filepath = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

bad_str = """  const [pipelineState, setPipelineState] = createSignal({
  // This component is now much smaller!
  // For a complete refactor, you would create these components in separate files.
  const ProjectList = () => {
    status: "pending","""

good_str = """  const [pipelineState, setPipelineState] = createSignal({
    status: "pending","""

if bad_str in text:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text.replace(bad_str, good_str))
    print("Fixed syntax error at top.")
else:
    print("Could not find the bad string.")
