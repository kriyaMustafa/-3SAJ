import os
import re

filepath = r"C:\Users\3SAJ\AppData\Roaming\Code\User\History\66c5cf81\hvWP.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

# A very simple regex-based JSX parser to find unclosed tags
# We will strip out strings and comments first to be accurate
text = re.sub(r'//.*', '', text)
text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
text = re.sub(r'`[^`]*`', '', text, flags=re.DOTALL)
text = re.sub(r'"[^"]*"', '', text)
text = re.sub(r"'[^']*'", '', text)

# Find all tags
tags = re.findall(r'</?[a-zA-Z0-9]+(?:[^>]*?)?>', text)

stack = []
for tag in tags:
    if tag.endswith('/>'):
        continue
    m_close = re.match(r'</([a-zA-Z0-9]+)', tag)
    if m_close:
        name = m_close.group(1)
        if stack and stack[-1] == name:
            stack.pop()
        else:
            print(f"Mismatched close: {name}, expected {stack[-1] if stack else 'Nothing'}")
    else:
        m_open = re.match(r'<([a-zA-Z0-9]+)', tag)
        if m_open:
            name = m_open.group(1)
            stack.append(name)

print("Unclosed tags:", stack)
