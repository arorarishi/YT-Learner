import re
import requests
from bs4 import BeautifulSoup
from typing import Any, Dict, List, Optional
from youtube_transcript_api import YouTubeTranscriptApi


def _format_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


class YouTubeVideo:
    def __init__(self, video_id: str):
        self.video_id = video_id

    @classmethod
    def from_url(cls, url: str) -> "YouTubeVideo":
        return cls(cls.extract_id(url))

    @staticmethod
    def extract_id(url: str) -> str:
        pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        raise ValueError("Invalid YouTube URL")

    def generate_transcript(self) -> Optional[str]:
        try:
            transcript_list = YouTubeTranscriptApi().list(self.video_id)
            transcript_data = transcript_list.fetch()

            transcript_lines: List[str] = []
            chunk_start = None
            chunk_texts: List[str] = []
            last_text = ""

            for entry in transcript_data:
                clean_text = entry.text.replace("\n", " ").strip()
                if not clean_text:
                    continue

                if chunk_start is None:
                    chunk_start = entry.start
                    chunk_texts = [clean_text]
                    last_text = clean_text
                    continue

                elapsed = entry.start - chunk_start
                is_sentence_break = any(last_text.endswith(c) for c in (".", "!", "?")) and clean_text[:1].isupper()

                if elapsed >= 30 or (elapsed >= 25 and is_sentence_break):
                    transcript_lines.append(f"{_format_time(chunk_start)} {' '.join(chunk_texts)}")
                    chunk_start = entry.start
                    chunk_texts = [clean_text]
                else:
                    chunk_texts.append(clean_text)

                last_text = clean_text

            if chunk_texts:
                transcript_lines.append(f"{_format_time(chunk_start)} {' '.join(chunk_texts)}")

            return "\n".join(transcript_lines)
        except Exception:
            return None

    def fetch_metadata(self, url: str) -> Dict[str, Any]:
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            title_meta = soup.find("meta", property="og:title")
            title = title_meta["content"] if title_meta else None

            image_meta = soup.find("meta", property="og:image")
            thumbnail_url = image_meta["content"] if image_meta else None

            channel_meta = soup.find("link", itemprop="name")
            channel_name = channel_meta["content"] if channel_meta else None

            thumbnail_blob = None
            if thumbnail_url:
                try:
                    image_response = requests.get(thumbnail_url, timeout=5)
                    if image_response.status_code == 200:
                        thumbnail_blob = image_response.content
                except Exception:
                    thumbnail_blob = None

            description = self._fetch_description()

            return {
                "title": title,
                "channel": channel_name,
                "thumbnail_url": thumbnail_url,
                "thumbnail_blob": thumbnail_blob,
                "description": description,
            }
        except Exception:
            return {
                "title": None,
                "channel": None,
                "thumbnail_url": None,
                "thumbnail_blob": None,
                "description": None,
            }

    def _fetch_description(self) -> str:
        try:
            from yt_dlp import YoutubeDL
            opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={self.video_id}", download=False
                )
            return info.get("description") or ""
        except Exception:
            return ""

    @staticmethod
    def parse_flash_cards(text: str) -> List[Dict[str, str]]:
        cards: List[Dict[str, str]] = []
        pattern = r"\*\*Front:\*\*\s*(.*?)\s*\*\*Back:\*\*\s*(.*?)(?=\n\*\*Front:|$)"
        matches = re.findall(pattern, text, re.DOTALL)
        for front, back in matches:
            back_clean = re.sub(r"\[TAGS\].*$", "", back, flags=re.IGNORECASE | re.DOTALL).strip()
            cards.append({"front": front.strip(), "back": back_clean})

        if cards:
            return cards

        current_card: Dict[str, str] = {}
        for line in text.split("\n"):
            if line.strip().startswith("Front:"):
                if current_card.get("front") and current_card.get("back"):
                    cards.append(current_card)
                    current_card = {}
                current_card["front"] = line.split("Front:", 1)[1].strip().replace("**", "")
            elif line.strip().startswith("Back:"):
                current_card["back"] = line.split("Back:", 1)[1].strip().replace("**", "")

        if current_card.get("front") and current_card.get("back"):
            cards.append(current_card)

        return cards
