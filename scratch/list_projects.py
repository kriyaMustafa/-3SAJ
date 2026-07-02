import sqlite3

def main():
    conn = sqlite3.connect('data/pipeline.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, status FROM projects")
    for r in cursor.fetchall():
        print(f"Proj ID: {r[0]}, Name: {r[1]}, Status: {r[2]}")
    conn.close()

if __name__ == '__main__':
    main()
