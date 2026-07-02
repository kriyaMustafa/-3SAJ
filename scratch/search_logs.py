import os

def main():
    brain_dir = r"C:\Users\3SAJ\.gemini\antigravity-cli\brain"
    print(f"Scanning {brain_dir} via os.walk...")
    
    matches = []
    file_count = 0
    for root, dirs, files in os.walk(brain_dir):
        for file in files:
            if file == "transcript.jsonl" or file.endswith(".jsonl"):
                file_count += 1
                f_path = os.path.join(root, file)
                try:
                    with open(f_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if "ធុញ" in line or "រឿងៅ" in line or "រឿង" in line and "ធុញ" in line:
                                matches.append((f_path, line_num, line))
                except Exception as e:
                    pass
                    
    print(f"Scanned {file_count} jsonl files. Found {len(matches)} matches.")
    # Sort matches so we see the newest or most relevant ones
    for m in matches[:10]:
        print(f"File: {m[0]}:{m[1]}")
        snippet = m[2][:300].strip()
        print(f"  Snippet: {snippet}")
        print("-" * 80)

if __name__ == '__main__':
    main()
