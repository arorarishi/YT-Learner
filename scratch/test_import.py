import sys
sys.path.append('.')
import sqlite3
from database import get_db

db = get_db()
# Let's import a real, public playlist from Google Developers
from main import import_playlist, PlaylistImportRequest

# Since it's an async FastAPI route, let's call it via an async runner
import asyncio

async def test():
    req = PlaylistImportRequest(url="https://www.youtube.com/playlist?list=PLOU2XLYxmsII9tFR7z7XyI-T2s7fW927C")
    try:
        res = await import_playlist(req)
        print("Import completed successfully!")
        print("Response:", res)
        
        # Verify in DB
        conn = sqlite3.connect('transcripts.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM playlists WHERE id = ?", (res["playlist_id"],))
        playlist = dict(cursor.fetchone())
        print("\nSaved Playlist in DB:")
        print(playlist)
        
        cursor.execute("""
            SELECT t.video_id, t.title, t.channel_name 
            FROM playlist_videos pv
            JOIN transcripts t ON pv.video_id = t.video_id
            WHERE pv.playlist_id = ?
            LIMIT 3
        """, (res["playlist_id"],))
        videos = [dict(row) for row in cursor.fetchall()]
        print("\nSaved Playlist Videos in DB (first 3):")
        for v in videos:
            print(v)
            
        conn.close()
    except Exception as e:
        print("Error during test:", e)

asyncio.run(test())
