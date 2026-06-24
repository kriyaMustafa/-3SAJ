import os

app_path = r"Z:\year3\projecj video translate backup\frontend\src\App.jsx"
backup_path = r"C:\Users\3SAJ\AppData\Roaming\Code\User\History\66c5cf81\ybRp.jsx"

with open(app_path, "r", encoding="utf-8") as f:
    app_text = f.read()

with open(backup_path, "r", encoding="utf-8") as f:
    backup_text = f.read()

app_text = app_text.rstrip() # Remove trailing whitespace or newlines

if app_text.endswith("playing"):
    # Find the button in the backup
    button_str = "cursor-pointer flex items-center justify-center gap-1"
    btn_idx = backup_text.rfind(button_str)
    if btn_idx != -1:
        playing_idx = backup_text.find("playing", btn_idx)
        end_idx = backup_text.find("export default App;") + len("export default App;")
        
        append_str = backup_text[playing_idx + len("playing"):end_idx] + "\n"
        
        with open(app_path, "w", encoding="utf-8") as f:
            f.write(app_text + append_str)
        print("Successfully patched App.jsx!")
    else:
        print("Button str not found in backup")
else:
    print("App.jsx doesn't end with playing. It ends with: " + app_text[-50:])
