import sqlite3

def main():
    conn = sqlite3.connect('data/pipeline.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT segment_index, original_text, translated_text
        FROM segments 
        WHERE project_id = '9918d1bf-e8fd-46a3-afbd-56fa47b70c2f'
        ORDER BY segment_index ASC
    """)
    rows = cursor.fetchall()
    with open("scratch/segments_list.txt", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"Segment {r[0]}:\n")
            f.write(f"  ENG: {r[1]}\n")
            f.write(f"  KHM: {r[2]}\n")
            f.write("="*80 + "\n")
    print(f"Wrote {len(rows)} segments to scratch/segments_list.txt")
    conn.close()

if __name__ == '__main__':
    main()
