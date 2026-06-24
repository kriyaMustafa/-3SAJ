import os
import re

filepath = r"C:\Users\3SAJ\AppData\Roaming\Code\User\History\66c5cf81\hvWP.jsx"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

def count_chars(char_open, char_close):
    # This is a naive count, but since it's just to check if we are 1 or 2 off, it helps.
    # To be strictly accurate we should strip strings, but let's just do naive first.
    return text.count(char_open) - text.count(char_close)

print("Braces {}:", count_chars('{', '}'))
print("Parens ():", count_chars('(', ')'))

# Also let's find the exact string where <main> was closed!
closes = [m.start() for m in re.finditer(r'</main>', text)]
print("</main> at index:", closes)

