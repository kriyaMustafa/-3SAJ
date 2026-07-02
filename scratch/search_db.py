import sqlite3

def main():
    conn = sqlite3.connect('data/pipeline.db')
    cursor = conn.cursor()
    
    # Search for English text containing "porcelain" or "glass"
    cursor.execute("""
        SELECT segment_index, original_text, translated_text
        FROM segments 
        WHERE original_text LIKE '%porcelain%' 
           OR original_text LIKE '%glass%'
           OR original_text LIKE '%cup%'
    """)
    rows = cursor.fetchall()
    print("=== Matches ===")
    for row in rows:
        print(f"Segment {row[0]}:")
        print(f"  ENG: {row[1]}")
        print(f"  KHM: {row[2]}")
        print("-" * 50)
        
    conn.close()

if __name__ == '__main__':
    main()
