import os

filepath = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

lines = text.split("\n")

open_braces = 0
for i in range(817):
    line = lines[i]
    # Simple count - ignores comments/strings but usually good enough
    # Let's clean out strings and single line comments for better accuracy
    import re
    cleaned = re.sub(r'//.*', '', line)
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned)
    open_braces += cleaned.count('{')
    open_braces -= cleaned.count('}')
    if open_braces == 0 and i > 5:
        print(f"Braces hit 0 at line {i+1}!")

print(f"Total open braces before line 818: {open_braces}")
