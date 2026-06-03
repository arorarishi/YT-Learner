import sqlite3
import json

conn = sqlite3.connect('transcripts.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute('SELECT * FROM playlists')
rows = cursor.fetchall()
with open('scratch/db_output.txt', 'w', encoding='utf-8') as f:
    f.write("Playlists Table Rows:\n")
    for r in rows:
        f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
conn.close()
print("Done, output saved to scratch/db_output.txt")
