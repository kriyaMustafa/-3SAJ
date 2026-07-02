import sqlite3

def main():
    conn = sqlite3.connect('data/pipeline.db')
    cursor = conn.cursor()
    
    # Query segments containing "ធុញ", "ល្អមើល", "មើល", "រឿង"
    cursor.execute("""
        SELECT segment_index, original_text, translated_text
        FROM segments 
        WHERE translated_text LIKE '%ធុញ%' 
           OR translated_text LIKE '%ល្អមើល%' 
           OR translated_text LIKE '%រឿង%'
    """)
    rows = cursor.fetchall()
    with open("scratch/search_matches.txt", "w", encoding="utf-8") as f:
        f.write(f"=== Found {len(rows)} matching segments ===\n\n")
        for r in rows:
            f.write(f"Segment {r[0]}:\n")
            f.write(f"  ENG: {r[1]}\n")
            f.write(f"  KHM: {r[2]}\n")
            f.write("="*80 + "\n")
            
    print(f"Wrote {len(rows)} matching segments to scratch/search_matches.txt")
    conn.close()

if __name__ == '__main__':
    main()
