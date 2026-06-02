from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from ..db.base_database import BaseDatabase


class PlaylistManager:
    def __init__(self, db: BaseDatabase):
        self.db = db

    def create(self, name: str, youtube_playlist_id: Optional[str] = None) -> int:
        return self.db.create_playlist(name, youtube_playlist_id)

    def get_videos(self, playlist_id: int) -> List[Dict[str, Any]]:
        return self.db.get_playlist_videos(playlist_id)

    def add_video(self, playlist_id: int, video_id: str):
        self.db.add_video_to_playlist(playlist_id, video_id)

    def rename(self, playlist_id: int, new_name: str):
        self.db.rename_playlist(playlist_id, new_name)

    def delete(self, playlist_id: int):
        self.db.delete_playlist(playlist_id)

    def import_from_url(self, url: str) -> Dict[str, Any]:
        from yt_dlp import YoutubeDL

        ydl_opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "dump_single_json": True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info or "entries" not in info:
            raise ValueError("Invalid playlist URL or unable to extract videos.")

        playlist_title = info.get("title", "Imported Playlist")
        playlist_id = self.create(playlist_title, info.get("id"))
        imported_count = 0

        for entry in info.get("entries", []):
            if not entry:
                continue
            video_id = entry.get("id")
            if not video_id:
                continue

            existing = self.db.get_transcript(video_id)
            if not existing:
                title = entry.get("title", "Untitled Video")
                channel = entry.get("channel") or entry.get("uploader") or "Unknown Channel"
                thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                self.db.save_transcript_metadata(video_id, "", title, channel, thumbnail_url, None)

            self.add_video(playlist_id, video_id)
            imported_count += 1

        return {"playlist_id": playlist_id, "name": playlist_title, "imported_count": imported_count}
