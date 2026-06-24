import os

backup_path = r'C:/Users/3SAJ/AppData/Roaming/Code/User/History/66c5cf81/ybRp.jsx'

with open(backup_path, 'r', encoding='utf-8') as f:
    backup_lines = f.readlines()

for i, line in enumerate(backup_lines):
    if 'playing' in line:
        print(f"Line {i+1}: {line.strip()}")
