import os
import re

filepath = r"C:\Users\3SAJ\AppData\Roaming\Code\User\History\66c5cf81\hvWP.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

idx1 = text.find('{/* Part Selector Buttons */}')
idx = text.rfind('return (', 0, idx1)

text_above = text[:idx]
text_above = re.sub(r'//.*', '', text_above)
text_above = re.sub(r'/\*.*?\*/', '', text_above, flags=re.DOTALL)
text_above = re.sub(r'`[^`]*`', '', text_above, flags=re.DOTALL)
text_above = re.sub(r'"[^"]*"', '', text_above)
text_above = re.sub(r"'[^']*'", '', text_above)

tags = re.findall(r'</?[a-zA-Z0-9]+(?:[^>]*?)?>', text_above)
stack = []
for tag in tags:
    if tag.endswith('/>') or '<input' in tag or '<br' in tag or '<img' in tag or '<hr' in tag: continue
    m_close = re.match(r'</([a-zA-Z0-9]+)', tag)
    if m_close:
        name = m_close.group(1)
        if stack and stack[-1] == name: stack.pop()
    else:
        m_open = re.match(r'<([a-zA-Z0-9]+)', tag)
        if m_open:
            name = m_open.group(1)
            if name not in ['input', 'br', 'img', 'hr']:
                stack.append(name)

print("Stack above IIFE:", stack)
