from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseDatabase(ABC):
    @abstractmethod
    def get_transcript(self, video_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_transcript_metadata(
        self,
        video_id: str,
        transcript_text: str,
        title: str,
        channel_name: str,
        thumbnail_url: str,
        thumbnail_blob: bytes,
        description: Optional[str] = None,
    ):
        pass

    @abstractmethod
    def update_metadata(
        self,
        video_id: str,
        title: str,
        channel_name: str,
        thumbnail_url: str,
        thumbnail_blob: bytes,
        description: Optional[str] = None,
    ):
        pass

    @abstractmethod
    def update_content(self, video_id: str, column_name: str, content: str):
        pass

    @abstractmethod
    def update_rating(self, video_id: str, rating: int):
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def get_thumbnail(self, video_id: str) -> Optional[bytes]:
        pass

    @abstractmethod
    def get_cached_token_usage(self, video_id: str, template_type: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_all_videos(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_flash_cards(self, video_id: str, cards: List[Dict[str, str]]):
        pass

    @abstractmethod
    def get_flash_cards(self, video_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_videos_with_flashcards(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def create_playlist(self, name: str, playlist_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def get_playlists(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def add_video_to_playlist(self, playlist_id: int, video_id: str):
        pass

    @abstractmethod
    def get_playlist_videos(self, playlist_id: int) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def rename_playlist(self, playlist_id: int, new_name: str):
        pass

    @abstractmethod
    def delete_playlist(self, playlist_id: int):
        pass

    @abstractmethod
    def get_all_transcripts_raw(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def update_column(self, video_id: str, column_name: str, value: Any):
        pass
