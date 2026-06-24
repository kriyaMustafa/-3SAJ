import sqlite3
import json

db_path = 'data/database.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Set project status to synthesizing
cursor.execute("UPDATE projects SET status = 'synthesizing' WHERE id = '27299abd-a243-46f9-895b-eb4c11dcb130'")
conn.commit()
conn.close()
print('Status updated!')
