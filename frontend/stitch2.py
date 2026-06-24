import os

backup_path = r'C:/Users/3SAJ/AppData/Roaming/Code/User/History/66c5cf81/ybRp.jsx'
app_path = r'Z:/year3/projecj video translate backup/frontend/src/App.jsx'

with open(backup_path, 'r', encoding='utf-8') as f:
    backup_lines = f.readlines()

with open(app_path, 'r', encoding='utf-8') as f:
    app_lines = f.readlines()

# The backup file has its full structure between line 1405 and 1898
# (We saw line 1404 was `class={\`px-2.5 py-1... ${`)
# Let's extract from line 1405 to 1898
backup_chunk = "".join(backup_lines[1404:1898])

# In App.jsx, the file ends at line 1376: `                                                  playing`
# Let's replace the last line with the backup chunk!
if 'playing' in app_lines[-1]:
    app_lines[-1] = backup_chunk
else:
    app_lines.append(backup_chunk)

with open(app_path, 'w', encoding='utf-8') as f:
    f.writelines(app_lines)

print("SUCCESS: Explicit chunk copied!")
