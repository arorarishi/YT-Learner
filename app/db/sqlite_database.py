import contextlib
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base_database import BaseDatabase


class SQLiteDatabase(BaseDatabase):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with contextlib.closing(sqlite3.connect(self.db_path, timeout=20)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(playlists)")
            existing_columns = [info[1] for info in cursor.fetchall()]
            if "playlist_id" not in existing_columns:
                conn.execute("ALTER TABLE playlists ADD COLUMN playlist_id TEXT")

            cursor.execute("PRAGMA table_info(transcripts)")
            existing_transcripts_columns = [info[1] for info in cursor.fetchall()]
            if "rating" not in existing_transcripts_columns:
                conn.execute("ALTER TABLE transcripts ADD COLUMN rating INTEGER DEFAULT 0")
            if "description" not in existing_transcripts_columns:
                conn.execute("ALTER TABLE transcripts ADD COLUMN description TEXT")

            conn.execute('''
                CREATE VIEW IF NOT EXISTS daily_activity AS
                SELECT DATE(load_timestamp) as activity_date, COUNT(*) as video_count
                FROM transcripts
                GROUP BY activity_date
            ''')
            conn.commit()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    def get_daily_activity(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT activity_date, video_count FROM daily_activity")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_all_videos(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT video_id, title, channel_name, thumbnail_url, tags_text, load_timestamp, rating 
                FROM transcripts 
                WHERE (hidden = 0 OR hidden = FALSE OR hidden IS NULL)
                AND (archived = 0 OR archived = FALSE OR archived IS NULL)
                ORDER BY load_timestamp DESC
            ''')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_transcript(self, video_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM transcripts WHERE video_id = ?', (video_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_transcript_metadata(
        self,
        video_id: str,
        transcript_text: str,
        title: str,
        channel_name: str,
        thumbnail_url: str,
        thumbnail_blob: bytes,
        description: str = None,
    ):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transcripts (video_id, transcript_text, title, channel_name, thumbnail_url, thumbnail_blob, description, load_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    transcript_text = CASE WHEN excluded.transcript_text != '' THEN excluded.transcript_text ELSE transcripts.transcript_text END,
                    title = COALESCE(excluded.title, transcripts.title),
                    channel_name = COALESCE(excluded.channel_name, transcripts.channel_name),
                    thumbnail_url = COALESCE(excluded.thumbnail_url, transcripts.thumbnail_url),
                    thumbnail_blob = COALESCE(excluded.thumbnail_blob, transcripts.thumbnail_blob),
                    description = COALESCE(excluded.description, transcripts.description),
                    load_timestamp = excluded.load_timestamp
            ''', (video_id, transcript_text, title, channel_name, thumbnail_url, thumbnail_blob, description, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()

    def update_metadata(self, video_id: str, title: str, channel_name: str, thumbnail_url: str, thumbnail_blob: bytes, description: str = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE transcripts
                SET title = ?, channel_name = ?, thumbnail_url = ?, thumbnail_blob = ?, description = COALESCE(?, description)
                WHERE video_id = ?
            ''', (title, channel_name, thumbnail_url, thumbnail_blob, description, video_id))
            conn.commit()

    _ALLOWED_CONTENT_COLUMNS = {
        "transcript_text", "summary_text", "quiz_text",
        "study_notes_text", "detailed_notes_text", "flash_cards_text", "tags_text",
    }

    def update_content(self, video_id: str, column_name: str, content: str):
        if column_name not in self._ALLOWED_CONTENT_COLUMNS:
            raise ValueError(f"Invalid column: {column_name}")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE transcripts SET {column_name} = ? WHERE video_id = ?', (content, video_id))
            conn.commit()

    def update_rating(self, video_id: str, rating: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE transcripts SET rating = ? WHERE video_id = ?', (rating, video_id))
            conn.commit()

    def log_api_request(
        self,
        user_id: str,
        video_id: str,
        template_type: str,
        tokens: int,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
        is_cached: bool,
        user_agent: str,
    ):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO api_requests (user_id, video_id, template_type, tokens_used, prompt_tokens, completion_tokens, cost, is_cached, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, video_id, template_type, tokens, prompt_tokens, completion_tokens, cost, 1 if is_cached else 0, user_agent))
            cursor.execute('INSERT OR IGNORE INTO users (user_id, total_api_calls, total_tokens_used, total_prompt_tokens, total_completion_tokens, total_cost) VALUES (?, 0, 0, 0, 0, 0.0)', (user_id,))
            cursor.execute('''
                UPDATE users
                SET total_api_calls = total_api_calls + 1,
                    total_tokens_used = total_tokens_used + ?,
                    total_prompt_tokens = total_prompt_tokens + ?,
                    total_completion_tokens = total_completion_tokens + ?,
                    total_cost = total_cost + ?
                WHERE user_id = ?
            ''', (tokens, prompt_tokens, completion_tokens, cost, user_id))
            conn.commit()

    def get_thumbnail(self, video_id: str) -> Optional[bytes]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT thumbnail_blob FROM transcripts WHERE video_id = ?', (video_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_cached_token_usage(self, video_id: str, template_type: str) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT tokens_used, prompt_tokens, completion_tokens, cost
                FROM api_requests
                WHERE video_id = ? AND template_type = ? AND is_cached = 0
                ORDER BY id ASC LIMIT 1
            ''', (video_id, template_type))
            orig = cursor.fetchone()
            if orig:
                return {
                    "tokens": orig[0],
                    "prompt_tokens": orig[1],
                    "completion_tokens": orig[2],
                    "cost": orig[3],
                }
            return {"tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}

    def save_flash_cards(self, video_id: str, cards: List[Dict[str, str]]):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM flash_cards WHERE video_id = ?', (video_id,))
            for card in cards:
                cursor.execute('''
                    INSERT INTO flash_cards (video_id, front, back)
                    VALUES (?, ?, ?)
                ''', (video_id, card['front'], card['back']))
            conn.commit()

    def get_flash_cards(self, video_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT front, back FROM flash_cards WHERE video_id = ?', (video_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_videos_with_flashcards(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT t.video_id, t.title, t.thumbnail_url, t.channel_name,
                       (SELECT COUNT(*) FROM flash_cards fc WHERE fc.video_id = t.video_id) as card_count
                FROM transcripts t
                JOIN flash_cards fc ON t.video_id = fc.video_id
                ORDER BY t.load_timestamp DESC
            ''')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def log_study_session(self, video_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO study_sessions (video_id, study_date)
                VALUES (?, DATE('now', 'localtime'))
            ''', (video_id,))
            conn.commit()

    def get_study_activity(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT study_date as activity_date, 
                       COUNT(*) as video_count,
                       group_concat(video_id) as video_ids
                FROM study_sessions
                GROUP BY activity_date
                ORDER BY activity_date DESC
            ''')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def create_playlist(self, name: str, playlist_id: Optional[str] = None) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO playlists (name, playlist_id) VALUES (?, ?)', (name, playlist_id))
            conn.commit()
            return cursor.lastrowid

    def get_playlists(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.id, p.name, p.playlist_id, p.created_at,
                       (SELECT COUNT(*) FROM playlist_videos pv WHERE pv.playlist_id = p.id) as video_count,
                       (SELECT GROUP_CONCAT(DISTINCT t.channel_name)
                        FROM playlist_videos pv2
                        JOIN transcripts t ON pv2.video_id = t.video_id
                        WHERE pv2.playlist_id = p.id AND t.channel_name IS NOT NULL AND t.channel_name != ''
                       ) as channel_names
                FROM playlists p
                ORDER BY p.created_at DESC
            ''')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def add_video_to_playlist(self, playlist_id: int, video_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COALESCE(MAX(s_no), 0) FROM playlist_videos WHERE playlist_id = ?', (playlist_id,))
            max_s_no = cursor.fetchone()[0]
            try:
                cursor.execute('''
                    INSERT INTO playlist_videos (playlist_id, video_id, s_no)
                    VALUES (?, ?, ?)
                ''', (playlist_id, video_id, max_s_no + 1))
                conn.commit()
            except sqlite3.IntegrityError:
                pass

    def add_followed_channel(self, channel_id: str, channel_name: str, playlist_id: Optional[int] = None) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO followed_channels (channel_id, channel_name, playlist_id) VALUES (?, ?, ?)', (channel_id, channel_name, playlist_id))
            conn.commit()
            cursor.execute('SELECT id FROM followed_channels WHERE channel_id = ?', (channel_id,))
            row = cursor.fetchone()
            return row[0] if row else -1

    def remove_followed_channel(self, channel_id: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM followed_channels WHERE channel_id = ?', (channel_id,))
            conn.commit()

    def list_followed_channels(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, channel_id, channel_name, created_at, last_fetched_video_id, last_fetched_at, playlist_id FROM followed_channels')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def update_last_fetched(self, channel_id: str, video_id: str, timestamp: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE followed_channels
                SET last_fetched_video_id = ?, last_fetched_at = ?
                WHERE channel_id = ?
            ''', (video_id, timestamp, channel_id))
            conn.commit()

    def get_playlist_id_for_channel(self, channel_id: str) -> Optional[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT playlist_id FROM followed_channels WHERE channel_id = ?', (channel_id,))
            row = cursor.fetchone()
            return row[0] if row and row[0] is not None else None

    def add_video_to_channel_playlist(self, channel_id: str, video_id: str) -> None:
        playlist_id = self.get_playlist_id_for_channel(channel_id)
        if playlist_id is None:
            raise ValueError(f"No playlist linked to channel {channel_id}")
        self.add_video_to_playlist(playlist_id, video_id)

    def get_playlist_videos(self, playlist_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.video_id, t.title, t.thumbnail_url, t.channel_name, t.tags_text, pv.s_no, pv.added_at
                FROM playlist_videos pv
                JOIN transcripts t ON pv.video_id = t.video_id
                WHERE pv.playlist_id = ?
                ORDER BY pv.s_no ASC
            ''', (playlist_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def rename_playlist(self, playlist_id: int, new_name: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE playlists SET name = ? WHERE id = ?', (new_name, playlist_id))
            conn.commit()

    def delete_playlist(self, playlist_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM playlist_videos WHERE playlist_id = ?', (playlist_id,))
            cursor.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))
            conn.commit()

    def get_all_transcripts_raw(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM transcripts')
            return [dict(row) for row in cursor.fetchall()]

    def update_column(self, video_id: str, column_name: str, value):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE transcripts SET {column_name} = ? WHERE video_id = ?', (value, video_id))
            conn.commit()
