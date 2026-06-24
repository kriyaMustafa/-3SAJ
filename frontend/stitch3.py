import os

backup_path = r'C:/Users/3SAJ/AppData/Roaming/Code/User/History/66c5cf81/ybRp.jsx'
app_path = r'Z:/year3/projecj video translate backup/frontend/src/App.jsx'

with open(backup_path, 'r', encoding='utf-8') as f:
    backup_lines = f.readlines()

with open(app_path, 'r', encoding='utf-8') as f:
    app_lines = f.readlines()

# Extract from line 1456 to 1898 (index 1455 to 1898)
backup_chunk = "".join(backup_lines[1455:1898])

# We need to replace the last line of App.jsx (which is "playing") with backup_chunk
if 'playing' in app_lines[-1]:
    app_lines[-1] = backup_chunk
else:
    # Just in case there was a newline
    for i in range(len(app_lines)-1, -1, -1):
        if 'playing' in app_lines[i]:
            app_lines[i] = backup_chunk
            break

with open(app_path, 'w', encoding='utf-8') as f:
    f.writelines(app_lines)

print("SUCCESS: Exact chunk copied!")
