import os
import re

filepath = r"Z:\year3\projecj video translate backup\frontend\rewrite_clean.mjs"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(r"/\\s*\\);\\s*\\}\\s*export default App;\\s*$/", r"/\s*\);\s*}\s*export default App;\s*$/")
text = text.replace(r"/<\\/div>\\s*\\n\\s*\\);\\s*\\}\\s*export default App;\\s*$/", r"/<\/div>\s*\n\s*\);\s*}\s*export default App;\s*$/")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(text)

print("Fixed regex successfully!")
