import os
import re

filepath = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    code = f.read()

code = re.sub(
    r'const details = state\.projectDetails;\s*const details = projectDetails\(\);',
    'const details = state.projectDetails || projectDetails();',
    code
)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(code)

print("Fixed spacing duplicate!")
