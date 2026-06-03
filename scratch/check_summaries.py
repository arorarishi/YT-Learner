import sqlite3
import os

db_path = r"d:\Work\ML\Projects\yt_summary\yt_summarizer_v2\transcripts.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("SELECT video_id, summary_text FROM transcripts WHERE summary_text IS NOT NULL AND summary_text != '' ORDER BY load_timestamp DESC LIMIT 3")
rows = cursor.fetchall()

print(f"Found {len(rows)} recent summaries.")
for row in rows:
    print(f"\n--- Video ID: {row['video_id']} ---")
    print(row['summary_text'][:500])

conn.close()
