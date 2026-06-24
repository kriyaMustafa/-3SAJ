import os

backup_path = r'C:/Users/3SAJ/AppData/Roaming/Code/User/History/66c5cf81/ybRp.jsx'
app_path = r'Z:/year3/projecj video translate backup/frontend/src/App.jsx'

with open(backup_path, 'r', encoding='utf-8') as f:
    backup_code = f.read()

with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# Find the exact location of "playing" in both files
backup_playing_idx = backup_code.rfind('playing\\n')
app_playing_idx = app_code.rfind('playing')

if backup_playing_idx == -1 or app_playing_idx == -1:
    print("Could not find playing")
    exit(1)

# In backup, we want everything from the start of 'playing' to the end of the file
# except for the weird 'playing' at the very bottom
bottom_half = backup_code[backup_playing_idx:]
if bottom_half.strip().endswith('playing'):
    bottom_half = bottom_half[:bottom_half.rfind('playing')]

# Replace the 'playing' in App.jsx with bottom_half
final_code = app_code[:app_playing_idx] + bottom_half

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(final_code)

print("SUCCESS: 500 lines restored!")
