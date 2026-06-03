from typing import Any, Dict, List, Optional

from ..db.base_database import BaseDatabase
from .ai import AIService
from .youtube_video import YouTubeVideo


class VideoProcessor:
    TEMPLATE_COLUMN_MAP = {
        "summary": "summary_text",
        "quiz": "quiz_text",
        "study_notes": "study_notes_text",
        "detailed_notes": "detailed_notes_text",
        "flash_cards": "flash_cards_text",
        "tags": "tags_text",
    }

    def __init__(
        self,
        db: BaseDatabase,
        ai_service: AIService,
        prompt_templates: Dict[str, str],
        max_single_pass_chars: int = 50000,
    ):
        self.db = db
        self.ai = ai_service
        self.prompt_templates = prompt_templates
        self.max_single_pass_chars = max_single_pass_chars

    def _ensure_metadata(self, video: YouTubeVideo, request_url: str, row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        title = row.get("title") if row else None
        channel_name = row.get("channel_name") if row else None
        thumbnail_url = row.get("thumbnail_url") if row else None
        thumbnail_blob = row.get("thumbnail_blob") if row else None
        description = row.get("description") if row else None

        if not title or not channel_name or channel_name == "Unknown Channel" or not thumbnail_url or not thumbnail_blob or not description:
            meta = video.fetch_metadata(request_url)
            title = title or meta.get("title")
            channel_name = channel_name or meta.get("channel")
            thumbnail_url = thumbnail_url or meta.get("thumbnail_url")
            thumbnail_blob = thumbnail_blob or meta.get("thumbnail_blob")
            description = description or meta.get("description")

            if row:
                self.db.update_metadata(video.video_id, title, channel_name, thumbnail_url, thumbnail_blob, description)

        return {
            "title": title,
            "channel_name": channel_name,
            "thumbnail_url": thumbnail_url,
            "thumbnail_blob": thumbnail_blob,
            "description": description,
        }

    def _ensure_transcript(self, video: YouTubeVideo, row: Optional[Dict[str, Any]], request_url: str) -> Optional[str]:
        transcript_text = row.get("transcript_text") if row else None
        if transcript_text:
            return transcript_text

        transcript_text = video.generate_transcript()
        if not transcript_text:
            return None

        if row:
            self.db.update_content(video.video_id, "transcript_text", transcript_text)
        else:
            meta = video.fetch_metadata(request_url)
            self.db.save_transcript_metadata(
                video.video_id,
                transcript_text,
                meta.get("title"),
                meta.get("channel"),
                meta.get("thumbnail_url"),
                meta.get("thumbnail_blob"),
                meta.get("description"),
            )

        return transcript_text

    def _build_cached_response(
        self,
        row: Dict[str, Any],
        template_type: str,
        video: YouTubeVideo,
        user_id: str,
        user_agent: str,
    ) -> Optional[Dict[str, Any]]:
        col_name = self.TEMPLATE_COLUMN_MAP.get(template_type)
        if not col_name:
            return None

        existing = row.get(col_name) if row else None
        if not existing or not existing.strip():
            return None

        usage = self.db.get_cached_token_usage(video.video_id, template_type)
        self.db.log_api_request(
            user_id,
            video.video_id,
            template_type,
            usage["tokens"],
            usage["prompt_tokens"],
            usage["completion_tokens"],
            usage["cost"],
            True,
            user_agent,
        )

        return {
            "summary": existing,
            "video_id": video.video_id,
            "title": row.get("title"),
            "channel_name": row.get("channel_name"),
            "thumbnail_url": row.get("thumbnail_url"),
            "transcript": row.get("transcript_text"),
            "tags": row.get("tags_text"),
        }

    def _save_response_content(self, video: YouTubeVideo, template_type: str, summary: str, tags: Optional[str]):
        col_name = self.TEMPLATE_COLUMN_MAP.get(template_type)
        if col_name:
            self.db.update_content(video.video_id, col_name, summary)

        if tags:
            self.db.update_content(video.video_id, "tags_text", tags)
        elif template_type == "tags":
            self.db.update_content(video.video_id, "tags_text", summary)

        if template_type == "flash_cards":
            cards = YouTubeVideo.parse_flash_cards(summary)
            if cards:
                self.db.save_flash_cards(video.video_id, cards)

    def _parse_tags(self, summary: str) -> Optional[str]:
        if "[TAGS]:" not in summary:
            return None
        return summary.split("[TAGS]:", 1)[1].strip()

    async def summarize_url(
        self,
        url: str,
        template_type: str,
        user_id: str,
        user_agent: str,
    ) -> Dict[str, Any]:
        video = YouTubeVideo.from_url(url)
        row = self.db.get_transcript(video.video_id) or {}

        metadata = self._ensure_metadata(video, url, row)
        transcript_text = self._ensure_transcript(video, row, url)
        if not transcript_text:
            raise RuntimeError("Transcript not available for this video.")

        cached = self._build_cached_response(row, template_type, video, user_id, user_agent)
        if cached:
            return cached

        template = self.prompt_templates.get(template_type, self.prompt_templates.get("summary", "Please summarize:"))
        summary, prompt_tokens, completion_tokens, cost = await self.ai.summarize_transcript(
            transcript_text,
            template,
            template_type,
            self.max_single_pass_chars,
        )

        tags = self._parse_tags(summary)
        if tags:
            summary = summary.split("[TAGS]:", 1)[0].strip()

        self._save_response_content(video, template_type, summary, tags)

        self.db.log_api_request(
            user_id,
            video.video_id,
            template_type,
            prompt_tokens + completion_tokens,
            prompt_tokens,
            completion_tokens,
            cost,
            False,
            user_agent,
        )

        return {
            "summary": summary,
            "video_id": video.video_id,
            "title": metadata.get("title"),
            "channel_name": metadata.get("channel_name"),
            "thumbnail_url": metadata.get("thumbnail_url"),
            "transcript": transcript_text,
            "tags": tags,
        }

    def get_or_fetch_transcript(self, video_id: str, url: Optional[str]) -> Optional[str]:
        row = self.db.get_transcript(video_id)
        if row and row.get("transcript_text"):
            return row["transcript_text"]

        if not url:
            return None

        video = YouTubeVideo(video_id)
        transcript = video.generate_transcript()
        if not transcript:
            return None

        meta = video.fetch_metadata(url)
        if row:
            self.db.update_content(video_id, "transcript_text", transcript)
            if meta.get("title") or meta.get("channel") or meta.get("thumbnail_url"):
                self.db.update_metadata(
                    video_id,
                    meta.get("title"),
                    meta.get("channel"),
                    meta.get("thumbnail_url"),
                    meta.get("thumbnail_blob"),
                )
        else:
            self.db.save_transcript_metadata(
                video_id,
                transcript,
                meta.get("title"),
                meta.get("channel"),
                meta.get("thumbnail_url"),
                meta.get("thumbnail_blob"),
                meta.get("description"),
            )

        return transcript

    def get_flashcards(self, video_id: str) -> List[Dict[str, str]]:
        cards = self.db.get_flash_cards(video_id)
        if cards:
            return cards

        row = self.db.get_transcript(video_id)
        if row and row.get("flash_cards_text"):
            cards = YouTubeVideo.parse_flash_cards(row["flash_cards_text"])
            if cards:
                self.db.save_flash_cards(video_id, cards)
        return cards
