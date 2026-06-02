from datetime import datetime
from typing import Any, Dict, List, Optional

from .base_database import BaseDatabase

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None  # type: ignore

_ALLOWED_CONTENT_COLUMNS = {
    "transcript_text", "summary_text", "quiz_text",
    "study_notes_text", "detailed_notes_text", "flash_cards_text", "tags_text",
}

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transcripts (
    video_id        TEXT PRIMARY KEY,
    transcript_text TEXT,
    title           TEXT,
    channel_name    TEXT,
    thumbnail_url   TEXT,
    thumbnail_blob  BYTEA,
    load_timestamp  TEXT,
    summary_text    TEXT,
    quiz_text       TEXT,
    study_notes_text    TEXT,
    detailed_notes_text TEXT,
    flash_cards_text    TEXT,
    tags_text       TEXT,
    hidden          INTEGER DEFAULT 0,
    archived        INTEGER DEFAULT 0,
    rating          INTEGER DEFAULT 0,
    description     TEXT
);

CREATE TABLE IF NOT EXISTS api_requests (
    id                  SERIAL PRIMARY KEY,
    user_id             TEXT,
    video_id            TEXT,
    template_type       TEXT,
    tokens_used         INTEGER,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    cost                FLOAT,
    is_cached           INTEGER DEFAULT 0,
    user_agent          TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id                TEXT PRIMARY KEY,
    total_api_calls        INTEGER DEFAULT 0,
    total_tokens_used      INTEGER DEFAULT 0,
    total_prompt_tokens    INTEGER DEFAULT 0,
    total_completion_tokens INTEGER DEFAULT 0,
    total_cost             FLOAT DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS flash_cards (
    id       SERIAL PRIMARY KEY,
    video_id TEXT,
    front    TEXT,
    back     TEXT
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id         SERIAL PRIMARY KEY,
    video_id   TEXT,
    study_date DATE
);

CREATE TABLE IF NOT EXISTS playlists (
    id          SERIAL PRIMARY KEY,
    name        TEXT,
    playlist_id TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS playlist_videos (
    id          SERIAL PRIMARY KEY,
    playlist_id INTEGER REFERENCES playlists(id),
    video_id    TEXT,
    s_no        INTEGER,
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (playlist_id, video_id)
);

CREATE TABLE IF NOT EXISTS followed_channels (
    id                   SERIAL PRIMARY KEY,
    channel_id           TEXT UNIQUE,
    channel_name         TEXT,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_fetched_video_id TEXT,
    last_fetched_at      TEXT,
    playlist_id          INTEGER
);

CREATE OR REPLACE VIEW daily_activity AS
    SELECT DATE(load_timestamp::timestamp) AS activity_date, COUNT(*) AS video_count
    FROM transcripts
    GROUP BY activity_date;
"""


class PostgresDatabase(BaseDatabase):
    def __init__(self, dsn: str):
        if psycopg2 is None:
            raise RuntimeError(
                "psycopg2 is not installed. Run: pip install psycopg2-binary"
            )
        self.dsn = dsn
        self._init_db()

    def _connect(self):
        conn = psycopg2.connect(self.dsn)
        conn.autocommit = False
        return conn

    def _init_db(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_SQL)
            conn.commit()

    # ------------------------------------------------------------------
    # Transcripts
    # ------------------------------------------------------------------

    def get_transcript(self, video_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM transcripts WHERE video_id = %s", (video_id,))
                row = cur.fetchone()
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO transcripts
                        (video_id, transcript_text, title, channel_name, thumbnail_url, thumbnail_blob, description, load_timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (video_id) DO UPDATE SET
                        transcript_text = CASE WHEN EXCLUDED.transcript_text <> '' THEN EXCLUDED.transcript_text
                                               ELSE transcripts.transcript_text END,
                        title           = COALESCE(EXCLUDED.title,         transcripts.title),
                        channel_name    = COALESCE(EXCLUDED.channel_name,  transcripts.channel_name),
                        thumbnail_url   = COALESCE(EXCLUDED.thumbnail_url, transcripts.thumbnail_url),
                        thumbnail_blob  = COALESCE(EXCLUDED.thumbnail_blob,transcripts.thumbnail_blob),
                        description     = COALESCE(EXCLUDED.description,   transcripts.description),
                        load_timestamp  = EXCLUDED.load_timestamp
                    """,
                    (video_id, transcript_text, title, channel_name, thumbnail_url,
                     thumbnail_blob, description, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
            conn.commit()

    def update_metadata(
        self,
        video_id: str,
        title: str,
        channel_name: str,
        thumbnail_url: str,
        thumbnail_blob: bytes,
        description: str = None,
    ):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE transcripts
                    SET title = %s, channel_name = %s, thumbnail_url = %s, thumbnail_blob = %s,
                        description = COALESCE(%s, description)
                    WHERE video_id = %s
                    """,
                    (title, channel_name, thumbnail_url, thumbnail_blob, description, video_id),
                )
            conn.commit()

    def update_content(self, video_id: str, column_name: str, content: str):
        if column_name not in _ALLOWED_CONTENT_COLUMNS:
            raise ValueError(f"Column '{column_name}' is not an allowed content column.")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE transcripts SET {column_name} = %s WHERE video_id = %s",
                    (content, video_id),
                )
            conn.commit()

    def update_rating(self, video_id: str, rating: int):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE transcripts SET rating = %s WHERE video_id = %s",
                    (rating, video_id),
                )
            conn.commit()

    def get_all_videos(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT video_id, title, channel_name, thumbnail_url, tags_text, load_timestamp, rating
                    FROM transcripts
                    WHERE (hidden = 0 OR hidden IS NULL)
                    AND   (archived = 0 OR archived IS NULL)
                    ORDER BY load_timestamp DESC
                    """
                )
                return [dict(r) for r in cur.fetchall()]

    def get_thumbnail(self, video_id: str) -> Optional[bytes]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT thumbnail_blob FROM transcripts WHERE video_id = %s", (video_id,)
                )
                row = cur.fetchone()
                return row[0] if row else None

    # ------------------------------------------------------------------
    # API logging
    # ------------------------------------------------------------------

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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO api_requests
                        (user_id, video_id, template_type, tokens_used, prompt_tokens,
                         completion_tokens, cost, is_cached, user_agent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, video_id, template_type, tokens, prompt_tokens,
                     completion_tokens, cost, 1 if is_cached else 0, user_agent),
                )
                cur.execute(
                    """
                    INSERT INTO users (user_id, total_api_calls, total_tokens_used,
                                       total_prompt_tokens, total_completion_tokens, total_cost)
                    VALUES (%s, 0, 0, 0, 0, 0.0)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (user_id,),
                )
                cur.execute(
                    """
                    UPDATE users
                    SET total_api_calls         = total_api_calls + 1,
                        total_tokens_used       = total_tokens_used + %s,
                        total_prompt_tokens     = total_prompt_tokens + %s,
                        total_completion_tokens = total_completion_tokens + %s,
                        total_cost              = total_cost + %s
                    WHERE user_id = %s
                    """,
                    (tokens, prompt_tokens, completion_tokens, cost, user_id),
                )
            conn.commit()

    def get_cached_token_usage(self, video_id: str, template_type: str) -> Dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tokens_used, prompt_tokens, completion_tokens, cost
                    FROM api_requests
                    WHERE video_id = %s AND template_type = %s AND is_cached = 0
                    ORDER BY id ASC LIMIT 1
                    """,
                    (video_id, template_type),
                )
                row = cur.fetchone()
                if row:
                    return {"tokens": row[0], "prompt_tokens": row[1],
                            "completion_tokens": row[2], "cost": row[3]}
                return {"tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}

    # ------------------------------------------------------------------
    # Flash cards
    # ------------------------------------------------------------------

    def save_flash_cards(self, video_id: str, cards: List[Dict[str, str]]):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM flash_cards WHERE video_id = %s", (video_id,))
                for card in cards:
                    cur.execute(
                        "INSERT INTO flash_cards (video_id, front, back) VALUES (%s, %s, %s)",
                        (video_id, card["front"], card["back"]),
                    )
            conn.commit()

    def get_flash_cards(self, video_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT front, back FROM flash_cards WHERE video_id = %s", (video_id,)
                )
                return [dict(r) for r in cur.fetchall()]

    def get_videos_with_flashcards(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT DISTINCT t.video_id, t.title, t.thumbnail_url, t.channel_name,
                           (SELECT COUNT(*) FROM flash_cards fc WHERE fc.video_id = t.video_id) AS card_count
                    FROM transcripts t
                    JOIN flash_cards fc ON t.video_id = fc.video_id
                    ORDER BY t.load_timestamp DESC
                    """
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Study sessions
    # ------------------------------------------------------------------

    def log_study_session(self, video_id: str):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO study_sessions (video_id, study_date) VALUES (%s, CURRENT_DATE)",
                    (video_id,),
                )
            conn.commit()

    def get_study_activity(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT study_date AS activity_date,
                           COUNT(*) AS video_count,
                           STRING_AGG(video_id, ',') AS video_ids
                    FROM study_sessions
                    GROUP BY activity_date
                    ORDER BY activity_date DESC
                    """
                )
                return [dict(r) for r in cur.fetchall()]

    def get_daily_activity(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT activity_date, video_count FROM daily_activity")
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    def create_playlist(self, name: str, playlist_id: Optional[str] = None) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO playlists (name, playlist_id) VALUES (%s, %s) RETURNING id",
                    (name, playlist_id),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
            return new_id

    def get_playlists(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT p.id, p.name, p.playlist_id, p.created_at,
                           (SELECT COUNT(*) FROM playlist_videos pv WHERE pv.playlist_id = p.id) AS video_count,
                           (SELECT STRING_AGG(DISTINCT t.channel_name, ',')
                            FROM playlist_videos pv2
                            JOIN transcripts t ON pv2.video_id = t.video_id
                            WHERE pv2.playlist_id = p.id
                              AND t.channel_name IS NOT NULL AND t.channel_name <> ''
                           ) AS channel_names
                    FROM playlists p
                    ORDER BY p.created_at DESC
                    """
                )
                return [dict(r) for r in cur.fetchall()]

    def add_video_to_playlist(self, playlist_id: int, video_id: str):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(s_no), 0) FROM playlist_videos WHERE playlist_id = %s",
                    (playlist_id,),
                )
                max_s_no = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO playlist_videos (playlist_id, video_id, s_no)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (playlist_id, video_id) DO NOTHING
                    """,
                    (playlist_id, video_id, max_s_no + 1),
                )
            conn.commit()

    def get_playlist_videos(self, playlist_id: int) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT t.video_id, t.title, t.thumbnail_url, t.channel_name,
                           t.tags_text, pv.s_no, pv.added_at
                    FROM playlist_videos pv
                    JOIN transcripts t ON pv.video_id = t.video_id
                    WHERE pv.playlist_id = %s
                    ORDER BY pv.s_no ASC
                    """,
                    (playlist_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    def rename_playlist(self, playlist_id: int, new_name: str):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE playlists SET name = %s WHERE id = %s", (new_name, playlist_id)
                )
            conn.commit()

    def delete_playlist(self, playlist_id: int):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM playlist_videos WHERE playlist_id = %s", (playlist_id,)
                )
                cur.execute("DELETE FROM playlists WHERE id = %s", (playlist_id,))
            conn.commit()

    def get_all_transcripts_raw(self):
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM transcripts")
                return [dict(r) for r in cur.fetchall()]

    def update_column(self, video_id: str, column_name: str, value):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE transcripts SET {column_name} = %s WHERE video_id = %s",
                    (value, video_id),
                )
            conn.commit()

    # ------------------------------------------------------------------
    # Followed channels
    # ------------------------------------------------------------------

    def add_followed_channel(
        self, channel_id: str, channel_name: str, playlist_id: Optional[int] = None
    ) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO followed_channels (channel_id, channel_name, playlist_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (channel_id) DO NOTHING
                    """,
                    (channel_id, channel_name, playlist_id),
                )
                cur.execute(
                    "SELECT id FROM followed_channels WHERE channel_id = %s", (channel_id,)
                )
                row = cur.fetchone()
            conn.commit()
            return row[0] if row else -1

    def remove_followed_channel(self, channel_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM followed_channels WHERE channel_id = %s", (channel_id,)
                )
            conn.commit()

    def list_followed_channels(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, channel_id, channel_name, created_at,
                           last_fetched_video_id, last_fetched_at, playlist_id
                    FROM followed_channels
                    """
                )
                return [dict(r) for r in cur.fetchall()]

    def update_last_fetched(self, channel_id: str, video_id: str, timestamp: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE followed_channels
                    SET last_fetched_video_id = %s, last_fetched_at = %s
                    WHERE channel_id = %s
                    """,
                    (video_id, timestamp, channel_id),
                )
            conn.commit()

    def get_playlist_id_for_channel(self, channel_id: str) -> Optional[int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT playlist_id FROM followed_channels WHERE channel_id = %s",
                    (channel_id,),
                )
                row = cur.fetchone()
                return row[0] if row and row[0] is not None else None

    def add_video_to_channel_playlist(self, channel_id: str, video_id: str) -> None:
        playlist_id = self.get_playlist_id_for_channel(channel_id)
        if playlist_id is None:
            raise ValueError(f"No playlist linked to channel {channel_id}")
        self.add_video_to_playlist(playlist_id, video_id)
