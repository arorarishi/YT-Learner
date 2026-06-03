import sqlite3

conn = sqlite3.connect('transcripts.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

video_id = '3RuFcW--sek'

print(f"=== Raw values for {video_id} ===")
c.execute('SELECT video_id, title, hidden, archived FROM transcripts WHERE video_id = ?', (video_id,))
r = c.fetchone()
if r:
    print(f"  title    : {r['title']}")
    print(f"  hidden   : {repr(r['hidden'])}  (type: {type(r['hidden']).__name__})")
    print(f"  archived : {repr(r['archived'])}  (type: {type(r['archived']).__name__})")
else:
    print("  NOT FOUND in transcripts table")

print()
print("=== Does it pass the library filter? ===")
c.execute("""
    SELECT video_id FROM transcripts
    WHERE video_id = ?
      AND (hidden = 0 OR hidden = FALSE OR hidden IS NULL)
      AND (archived = 0 OR archived = FALSE OR archived IS NULL)
""", (video_id,))
result = c.fetchone()
print(f"  Returned by filter: {'YES — it passes (should NOT)' if result else 'NO — correctly excluded'}")

conn.close()
