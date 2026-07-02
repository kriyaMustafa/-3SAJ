import sqlite3

def main():
    conn = sqlite3.connect('data/pipeline.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, segment_index, start_time, end_time, original_text, translated_text
        FROM segments 
        WHERE project_id = '9918d1bf-e8fd-46a3-afbd-56fa47b70c2f'
        ORDER BY segment_index ASC
        LIMIT 25
    """)
    rows = cursor.fetchall()
    print("id | index | start | end | original_text_snippet | translated_text_snippet")
    print("-" * 100)
    for r in rows:
        orig = r[4][:50].replace('\n', ' ')
        tran = r[5][:50].replace('\n', ' ') if r[5] else 'None'
        print(f"{r[0]} | {r[1]} | {r[2]:.1f} | {r[3]:.1f} | {orig} | {tran}")
    conn.close()

if __name__ == '__main__':
    main()
