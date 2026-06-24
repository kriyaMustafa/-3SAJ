import os
import re

filepath = r"C:\Users\3SAJ\AppData\Roaming\Code\User\History\66c5cf81\hvWP.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

def count_tags(tag_name):
    # Match open tags like <div> or <div class="...">, excluding self-closing <div />
    opens = len(re.findall(r'<' + tag_name + r'(?:\s+[^>]*)?(?<!/)>', text))
    closes = len(re.findall(r'</' + tag_name + r'\s*>', text))
    return opens - closes

print("div:", count_tags("div"))
print("Show:", count_tags("Show"))
print("For:", count_tags("For"))
print("main:", count_tags("main"))
print("button:", count_tags("button"))
print("span:", count_tags("span"))
print("svg:", count_tags("svg"))
print("path:", count_tags("path"))
print("h1:", count_tags("h1"))
print("h2:", count_tags("h2"))
print("h3:", count_tags("h3"))
print("p:", count_tags("p"))
print("label:", count_tags("label"))
print("textarea:", count_tags("textarea"))
