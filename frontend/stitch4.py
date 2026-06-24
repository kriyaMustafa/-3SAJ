import os

backup_path = r'C:/Users/3SAJ/AppData/Roaming/Code/User/History/66c5cf81/ybRp.jsx'
app_path = r'Z:/year3/projecj video translate backup/frontend/src/App.jsx'

with open(backup_path, 'r', encoding='utf-8') as f:
    backup_lines = f.readlines()

with open(app_path, 'r', encoding='utf-8') as f:
    app_lines = f.readlines()

# App.jsx up to line 1374 is:
# 1373: onClick={() => playPreview(...)}
# 1374: disabled={!seg.translated_text.trim()}

# Let's keep App.jsx up to line 1374 (index 1374, so 0 to 1374)
clean_app_lines = app_lines[:1374]

# backup_lines from line 1455 (index 1454) to 1898 (index 1898)
# In backup_lines:
# 1454: disabled={!seg.translated_text.trim()}
# 1455: class={`px-2.5 py-1 ... ${
# 1456: playingPreviewId() === seg.segment_id

# Let's append backup_lines from index 1454 to 1898
# Wait, clean_app_lines already has line 1374 (index 1373) which is `disabled={!seg.translated_text.trim()}`
# So we append from index 1454
clean_app_lines.extend(backup_lines[1454:1898])

with open(app_path, 'w', encoding='utf-8') as f:
    f.writelines(clean_app_lines)

print("SUCCESS: File perfectly stitched!")
