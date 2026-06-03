import io
import csv
import os
import re
import time
import traceback
import yaml
import requests
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional, List, Dict, Any

import yt_dlp
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
from dotenv import load_dotenv
from .db.factory import get_db
from .core.scheduler import scheduler
from .core.utils import extract_channel_id, fetch_latest_video_id
from .models.playlist_models import PlaylistCreate, PlaylistVideoAdd, PlaylistImportRequest, PlaylistRename
from .models.schemas import SummarizeRequest, SummarizeResponse, FollowChannelRequest, VideoRatingRequest

# Load environment variables (explicit path)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# Initialize FastAPI app
app = FastAPI(title="YouTube Summarizer via DeepSeek")

# Read API key from environment
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY")
if not DEEPINFRA_API_KEY:
    raise RuntimeError(
        "DEEPINFRA_API_KEY is missing or empty in .env. Please add a valid DeepInfra API key."
    )

client = AsyncOpenAI(
    api_key=DEEPINFRA_API_KEY,
    base_url="https://api.deepinfra.com/v1/openai"
)

MODEL_NAME = "deepseek-ai/DeepSeek-V3"

db = get_db()

# Load Prompt Templates dynamically from prompts/ directory
PROMPT_TEMPLATES = {}
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

if os.path.exists(PROMPTS_DIR):
    for filename in os.listdir(PROMPTS_DIR):
        if filename.endswith(".yaml"):
            try:
                with open(os.path.join(PROMPTS_DIR, filename), "r") as f:
                    template_data = yaml.safe_load(f)
                    template_name = filename.replace(".yaml", "")
                    if isinstance(template_data, dict) and "prompt" in template_data:
                        PROMPT_TEMPLATES[template_name] = template_data["prompt"].strip()
                        print(f"INFO: Loaded prompt template: {template_name} (v{template_data.get('version', '1.0')})")
                    else:
                        f.seek(0)
                        PROMPT_TEMPLATES[template_name] = f.read().strip()
                        print(f"INFO: Loaded plain prompt template: {template_name}")
            except Exception as e:
                print(f"Warning: Could not load prompt {filename}: {e}")
else:
    print(f"Warning: Prompts directory not found at {PROMPTS_DIR}")

if not PROMPT_TEMPLATES:
    PROMPT_TEMPLATES = {"summary": "You are an expert summarizer. Please provide a comprehensive summary."}


def _strip_tags_instruction(prompt: str) -> str:
    idx = prompt.find("At the very end of your response, provide")
    if idx != -1:
        return prompt[:idx].rstrip()
    return prompt


async def summarize_in_chunks(transcript: str, template: str, model_name: str, template_type: str, max_chunk_chars: int = 50000):
    lines = transcript.split('\n')
    chunks = []
    current_chunk = []
    current_length = 0

    for line in lines:
        if current_length + len(line) > max_chunk_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = current_chunk[-3:] if len(current_chunk) > 3 else []
            current_length = sum(len(l) for l in current_chunk)

        current_chunk.append(line)
        current_length += len(line)

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    print(f"DEBUG: Processing {len(chunks)} chunks for {template_type}...")

    template_no_tags = _strip_tags_instruction(template)

    # Process a maximum of 5 chunks simultaneously to prevent rate limits
    sem = asyncio.Semaphore(5)

    async def process_chunk(i: int, chunk: str):
        async with sem:
            print(f"DEBUG: Summarizing chunk {i+1}/{len(chunks)}...")
            is_last = (i == len(chunks) - 1)
            active_template = template if is_last else template_no_tags
            chunk_info = f"\n\n(Note: This is segment {i+1} of {len(chunks)} of the video transcript.)"
            chunk_prompt = f"{active_template}{chunk_info}\n\nTranscript Segment:\n{chunk}"

            try:
                _t0 = time.perf_counter()
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that summarizes video transcripts accurately and clearly."},
                        {"role": "user", "content": chunk_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=3000 if template_type == "detailed_notes" else 1500
                )
                print(f"LATENCY [LLM/{template_type} chunk {i+1}/{len(chunks)}]: {time.perf_counter()-_t0:.2f}s")
                chunk_summary = response.choices[0].message.content
                p_tokens = response.usage.prompt_tokens if response.usage else 0
                c_tokens = response.usage.completion_tokens if response.usage else 0
                cost = getattr(response.usage, 'estimated_cost', 0.0) if response.usage else 0.0
                
                return i, chunk_summary, p_tokens, c_tokens, cost
            except Exception as e:
                if hasattr(e, "response") and e.response is not None:
                    try:
                        err_data = await e.response.json()
                    except Exception:
                        err_data = {"error": {"message": str(e)}}
                    if err_data.get("error", {}).get("code") == "invalid_api_key":
                        raise HTTPException(
                            status_code=401,
                            detail="Invalid DeepInfra API key. Please verify the key in .env."
                        )
                raise

    tasks = [process_chunk(i, chunk) for i, chunk in enumerate(chunks)]
    results = await asyncio.gather(*tasks)
    
    # Sort results by the original index to preserve narrative order
    results.sort(key=lambda x: x[0])
    
    summaries = [r[1] for r in results]
    total_prompt_tokens = sum(r[2] for r in results)
    total_completion_tokens = sum(r[3] for r in results)
    total_cost = sum(r[4] for r in results)

    if len(chunks) > 1:
        combined_header = f"# Combined {template_type.replace('_', ' ').title()}\n\n"
        final_summary = combined_header + "\n\n---\n\n".join(summaries)
    else:
        final_summary = summaries[0]

    return final_summary, total_prompt_tokens, total_completion_tokens, total_cost


class Video:
    def __init__(self, video_id: str):
        self.video_id = video_id

    @classmethod
    def from_url(cls, url: str) -> "Video":
        video_id = cls.extract_id(url)
        return cls(video_id)

    @staticmethod
    def extract_id(url: str) -> str:
        pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        raise ValueError("Invalid YouTube URL")

    def generate_transcript(self) -> Optional[str]:
        try:
            _t0 = time.perf_counter()
            transcript_list = YouTubeTranscriptApi().list(self.video_id)
            transcript = list(transcript_list)[0]
            transcript_data = transcript.fetch()
            print(f"LATENCY [YouTubeTranscriptApi.fetch/{self.video_id}]: {time.perf_counter()-_t0:.2f}s")

            def format_time(seconds: float) -> str:
                h = int(seconds // 3600)
                m = int((seconds % 3600) // 60)
                s = int(seconds % 60)
                if h > 0:
                    return f"[{h:02d}:{m:02d}:{s:02d}]"
                return f"[{m:02d}:{s:02d}]"

            MIN_CHUNK_SECONDS = 25
            MAX_CHUNK_SECONDS = 30
            SENTENCE_ENDS = ('.', '!', '?')

            transcript_lines = []
            chunk_start = None
            chunk_texts = []
            last_text = ""

            for t in transcript_data:
                clean_text = t.text.replace('\n', ' ').strip()
                if not clean_text:
                    continue

                if chunk_start is None:
                    chunk_start = t.start
                    chunk_texts = [clean_text]
                    last_text = clean_text
                    continue

                elapsed = t.start - chunk_start
                is_sentence_break = (
                    any(last_text.endswith(e) for e in SENTENCE_ENDS)
                    and clean_text[0].isupper()
                )

                if elapsed >= MAX_CHUNK_SECONDS or (elapsed >= MIN_CHUNK_SECONDS and is_sentence_break):
                    transcript_lines.append(f"{format_time(chunk_start)} {' '.join(chunk_texts)}")
                    chunk_start = t.start
                    chunk_texts = [clean_text]
                else:
                    chunk_texts.append(clean_text)
                last_text = clean_text

            if chunk_texts:
                transcript_lines.append(f"{format_time(chunk_start)} {' '.join(chunk_texts)}")

            return "\n".join(transcript_lines)
        except Exception:
            return None

    def fetch_metadata(self, url: str) -> Dict[str, Any]:
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            _t0 = time.perf_counter()
            response = requests.get(url, headers=headers, timeout=10)
            print(f"LATENCY [HTTP/page-scrape {self.video_id}]: {time.perf_counter()-_t0:.2f}s")
            soup = BeautifulSoup(response.text, 'html.parser')

            title_meta = soup.find('meta', property='og:title')
            title = title_meta['content'] if title_meta else None

            img_meta = soup.find('meta', property='og:image')
            thumbnail_url = img_meta['content'] if img_meta else None

            channel_link = soup.find('link', itemprop='name')
            channel = channel_link['content'] if channel_link else None

            thumbnail_blob = None
            if thumbnail_url:
                try:
                    _t1 = time.perf_counter()
                    img_response = requests.get(thumbnail_url, timeout=5)
                    print(f"LATENCY [HTTP/thumbnail {self.video_id}]: {time.perf_counter()-_t1:.2f}s")
                    if img_response.status_code == 200:
                        thumbnail_blob = img_response.content
                except Exception:
                    pass

            description = self._fetch_description()

            return {
                "title": title,
                "channel": channel,
                "thumbnail_url": thumbnail_url,
                "thumbnail_blob": thumbnail_blob,
                "description": description,
            }
        except Exception:
            return {"title": None, "channel": None, "thumbnail_url": None, "thumbnail_blob": None, "description": None}

    def _fetch_description(self) -> str:
        try:
            from yt_dlp import YoutubeDL
            opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
            _t0 = time.perf_counter()
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={self.video_id}", download=False
                )
            print(f"LATENCY [yt-dlp/description {self.video_id}]: {time.perf_counter()-_t0:.2f}s")
            return info.get("description") or ""
        except Exception:
            return ""

    @staticmethod
    def parse_flash_cards(text: str) -> List[Dict[str, str]]:
        cards = []
        pattern = r"\*\*Front:\*\*\s*(.*?)\s*\*\*Back:\*\*\s*(.*?)(?=\n\*\*Front:|$)"
        matches = re.findall(pattern, text, re.DOTALL)

        for front, back in matches:
            back_clean = re.sub(r"\[TAGS\].*$", "", back, flags=re.IGNORECASE | re.DOTALL).strip()
            cards.append({"front": front.strip(), "back": back_clean})

        if not cards:
            current_card = {}
            for line in text.split('\n'):
                if "Front:" in line:
                    if current_card.get('front') and current_card.get('back'):
                        cards.append(current_card)
                        current_card = {}
                    current_card['front'] = line.split('Front:', 1)[1].strip().replace('**', '')
                elif "Back:" in line:
                    current_card['back'] = line.split('Back:', 1)[1].strip().replace('**', '')
            if current_card.get('front') and current_card.get('back'):
                cards.append(current_card)

        return cards

    async def summarize(self, template_type: str, user_id: str, request_url: str, user_agent: str) -> Dict[str, Any]:
        row_dict = db.get_transcript(self.video_id)

        title, channel, thumbnail_url, thumbnail_blob, description = None, None, None, None, None

        if row_dict:
            transcript_text = row_dict.get('transcript_text')
            title = row_dict.get('title')
            channel = row_dict.get('channel_name')
            thumbnail_url = row_dict.get('thumbnail_url')
            thumbnail_blob = row_dict.get('thumbnail_blob')
            description = row_dict.get('description')
        else:
            transcript_text = None

        if not title or not channel or channel == "Unknown Channel" or not thumbnail_url or not thumbnail_blob or description is None:
            print(f"DEBUG: Fetching metadata for {self.video_id}...")
            meta = self.fetch_metadata(request_url)
            title = title or meta["title"]
            channel = channel or meta["channel"]
            thumbnail_url = thumbnail_url or meta["thumbnail_url"]
            thumbnail_blob = thumbnail_blob or meta["thumbnail_blob"]
            description = description if description is not None else meta.get("description")
            if title and row_dict:
                db.update_metadata(self.video_id, title, channel, thumbnail_url, thumbnail_blob, description)

        if not transcript_text:
            print(f"DEBUG: Fetching fresh transcript for {self.video_id}...")
            transcript_text = self.generate_transcript()
            if not transcript_text:
                raise HTTPException(status_code=404, detail="Transcript not available for this video.")

            if row_dict:
                db.update_content(self.video_id, "transcript_text", transcript_text)
            else:
                db.save_transcript_metadata(self.video_id, transcript_text, title, channel, thumbnail_url, thumbnail_blob, description)
                row_dict = {"video_id": self.video_id, "transcript_text": transcript_text}

        template_col_map = {
            "summary": "summary_text",
            "quiz": "quiz_text",
            "study_notes": "study_notes_text",
            "detailed_notes": "detailed_notes_text",
            "flash_cards": "flash_cards_text",
            "tags": "tags_text"
        }

        col_name = template_col_map.get(template_type)
        if col_name and row_dict.get(col_name) and row_dict.get(col_name).strip() != "":
            print(f"CACHE HIT: Found {template_type} for {self.video_id}")
            usage = db.get_cached_token_usage(self.video_id, template_type)
            db.log_api_request(
                user_id, self.video_id, template_type,
                usage["tokens"], usage["prompt_tokens"], usage["completion_tokens"], usage["cost"],
                True, user_agent
            )
            return {
                "summary": row_dict[col_name],
                "video_id": self.video_id,
                "title": title,
                "channel_name": channel,
                "thumbnail_url": thumbnail_url,
                "transcript": transcript_text,
                "tags": row_dict.get('tags_text')
            }

        print(f"INFO: Generating fresh {template_type} for {self.video_id}...")

        MAX_SINGLE_PASS_CHARS = 50_000
        template = PROMPT_TEMPLATES.get(template_type, PROMPT_TEMPLATES.get("summary", "Please summarize:"))

        if len(transcript_text) > MAX_SINGLE_PASS_CHARS:
            summary, prompt_tokens, completion_tokens, cost = await summarize_in_chunks(
                transcript_text, template, MODEL_NAME, template_type, MAX_SINGLE_PASS_CHARS
            )
            tokens_used = prompt_tokens + completion_tokens
        else:
            prompt = f"{template}\n\nTranscript:\n{transcript_text}"
            _t0 = time.perf_counter()
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes video transcripts accurately and clearly."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=3000 if template_type == "detailed_notes" else 1500
            )
            print(f"LATENCY [LLM/{template_type} single-pass {self.video_id}]: {time.perf_counter()-_t0:.2f}s")
            summary = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0
            cost = getattr(response.usage, 'estimated_cost', 0.0) if response.usage else 0.0

        tags = None
        if "[TAGS]:" in summary:
            parts = summary.split("[TAGS]:")
            summary = parts[0].strip()
            tags = parts[1].strip()

        col_name = template_col_map.get(template_type)
        if col_name:
            db.update_content(self.video_id, col_name, summary)

        if template_type == "flash_cards":
            cards = self.parse_flash_cards(summary)
            if cards:
                db.save_flash_cards(self.video_id, cards)

        if tags:
            db.update_content(self.video_id, "tags_text", tags)
        elif not tags and template_type == "tags":
            tags = summary
            db.update_content(self.video_id, "tags_text", tags)

        db.log_api_request(
            user_id, self.video_id, template_type,
            tokens_used, prompt_tokens, completion_tokens, cost,
            False, user_agent
        )

        return {
            "summary": summary,
            "video_id": self.video_id,
            "title": title,
            "channel_name": channel,
            "thumbnail_url": thumbnail_url,
            "transcript": transcript_text,
            "tags": tags
        }

    def update_rating(self, rating: int):
        db.update_rating(self.video_id, rating)


class Playlist:
    def __init__(self, playlist_id: Optional[int] = None):
        self.playlist_id = playlist_id

    @classmethod
    def create(cls, name: str, youtube_playlist_id: Optional[str] = None) -> "Playlist":
        playlist_id = db.create_playlist(name, youtube_playlist_id)
        return cls(playlist_id)

    @staticmethod
    def import_from_url(url: str) -> Dict[str, Any]:
        ydl_opts = {
            'extract_flat': 'in_playlist',
            'quiet': True,
            'no_warnings': True,
            'dump_single_json': True,
        }
        _t0 = time.perf_counter()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        print(f"LATENCY [yt-dlp/playlist-import {url}]: {time.perf_counter()-_t0:.2f}s")

        if 'entries' not in info:
            raise ValueError("Invalid playlist URL or unable to extract videos.")

        playlist_title = info.get('title', 'Imported Playlist')
        yt_playlist_id = info.get('id')
        playlist = Playlist.create(playlist_title, yt_playlist_id)

        imported_count = 0
        for entry in info.get('entries', []):
            if not entry:
                continue
            video_id = entry.get('id')
            if not video_id:
                continue

            existing = db.get_transcript(video_id)
            if not existing:
                title = entry.get('title', 'Untitled Video')
                channel = entry.get('channel') or entry.get('uploader') or 'Unknown Channel'
                thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                db.save_transcript_metadata(video_id, "", title, channel, thumbnail_url, None)

            playlist.add_video(video_id)
            imported_count += 1

        return {"playlist_id": playlist.playlist_id, "name": playlist_title, "imported_count": imported_count}

    def get_videos(self) -> List[Dict[str, Any]]:
        return db.get_playlist_videos(self.playlist_id)

    def add_video(self, video_id: str):
        db.add_video_to_playlist(self.playlist_id, video_id)

    def rename(self, new_name: str):
        db.rename_playlist(self.playlist_id, new_name)

    def delete(self):
        db.delete_playlist(self.playlist_id)


@app.get("/api/videos")
async def list_videos():
    try:
        return db.get_all_videos()
    except Exception as e:
        print(f"Error fetching videos: {e}")
        return []

@app.get("/api/thumbnail/{video_id}")
async def get_thumbnail(video_id: str):
    blob = db.get_thumbnail(video_id)
    if blob:
        return Response(content=blob, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Thumbnail not found")

@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_video(payload: SummarizeRequest, req: Request):
    try:
        video = Video.from_url(payload.url)
        user_agent = req.headers.get("user-agent", "Unknown")
        result = await video.summarize(payload.template_type, payload.user_id, payload.url, user_agent)
        return SummarizeResponse(**result)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    except Exception as e:
        print(f"Error processing video: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing video: {str(e)}")

@app.get("/")
async def index(v: Optional[str] = None):
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

@app.get("/details")
async def video_details(v: Optional[str] = None):
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "details.html"))

@app.get("/api/video/{video_id}/transcript")
async def get_video_transcript_only(video_id: str, url: Optional[str] = None):
    video = Video(video_id)
    db_video = db.get_transcript(video_id)
    if db_video and db_video.get('transcript_text'):
        return {"transcript": db_video['transcript_text']}

    if not url:
        raise HTTPException(status_code=400, detail="URL required for fresh transcript fetch")

    transcript_text = video.generate_transcript()
    if not transcript_text:
        raise HTTPException(status_code=404, detail="Transcript not available")

    meta = video.fetch_metadata(url)
    db.save_transcript_metadata(video_id, transcript_text, meta['title'], meta['channel'], meta['thumbnail_url'], meta['thumbnail_blob'], meta.get('description'))
    return {"transcript": transcript_text}

@app.get("/api/video/{video_id}")
async def get_video_details(video_id: str):
    print(f"DEBUG: Fetching details for video_id: '{video_id}'")
    video = db.get_transcript(video_id)
    if video:
        if 'thumbnail_blob' in video:
            del video['thumbnail_blob']
        return video
    raise HTTPException(status_code=404, detail="Video not found in library")

@app.get("/api/video/{video_id}/flashcards")
async def get_flashcards(video_id: str):
    cards = db.get_flash_cards(video_id)
    if not cards:
        video = db.get_transcript(video_id)
        if video and video.get('flash_cards_text'):
            cards = Video.parse_flash_cards(video['flash_cards_text'])
            if cards:
                db.save_flash_cards(video_id, cards)
    return cards

@app.get("/library")
async def library():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "library.html"))

@app.get("/revise")
async def revise_flashcards(v: str):
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "flashcards.html"))

@app.get("/revision")
async def revision_dashboard():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "revision.html"))

@app.get("/api/revision/stats")
async def get_revision_stats():
    return db.get_videos_with_flashcards()

@app.post("/api/video/{video_id}/study")
async def log_video_study_session(video_id: str):
    try:
        db.log_study_session(video_id)
        return {"status": "success", "message": "Study session logged successfully"}
    except Exception as e:
        print(f"Error logging study session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/revision/activity")
async def get_study_activity_route():
    try:
        return db.get_study_activity()
    except Exception as e:
        print(f"Error fetching study activity: {e}")
        return []

@app.get("/api/video/{video_id}/export/anki")
async def export_anki(video_id: str):
    video = db.get_transcript(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    cards = db.get_flash_cards(video_id)
    if not cards and video.get('flash_cards_text'):
        cards = Video.parse_flash_cards(video['flash_cards_text'])
        if cards:
            db.save_flash_cards(video_id, cards)

    if not cards:
        raise HTTPException(status_code=404, detail="No flashcards found for this video")

    title = video.get('title', 'flashcards')
    safe_title = re.sub(r'[^a-z0-9]', '_', title.lower())

    output = io.StringIO()
    writer = csv.writer(output)
    for card in cards:
        writer.writerow([card['front'], card['back'], title])
    content = output.getvalue()
    output.close()

    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={safe_title}_anki.csv"}
    )

@app.get("/api/activity")
async def get_activity():
    try:
        return db.get_daily_activity()
    except Exception as e:
        print(f"Error fetching activity: {e}")
        return []

@app.get("/playlists")
async def playlists_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "playlists.html"))

@app.get("/api/playlists")
async def get_playlists():
    return db.get_playlists()

@app.post("/api/playlists")
async def create_playlist_route(payload: PlaylistCreate):
    playlist = Playlist.create(payload.name)
    return {"id": playlist.playlist_id, "name": payload.name}

@app.post("/api/playlists/import")
async def import_playlist_route(payload: PlaylistImportRequest):
    try:
        res = Playlist.import_from_url(payload.url)
        return {"status": "success", **res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error importing playlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
def start_scheduler():
    if not scheduler.running:
        scheduler.start()

@app.post("/api/follow_channel")
async def follow_channel(payload: FollowChannelRequest):
    channel_id = extract_channel_id(payload.channel)
    playlist_name = payload.name or channel_id
    playlist_id = db.create_playlist(playlist_name)
    db.add_followed_channel(channel_id, playlist_name, playlist_id)
    latest_vid = fetch_latest_video_id(channel_id)
    if latest_vid:
        db.add_video_to_channel_playlist(channel_id, latest_vid)
        db.update_last_fetched(channel_id, latest_vid, datetime.utcnow().isoformat())
    return {"status": "followed", "channel_id": channel_id, "playlist_id": playlist_id, "latest_video": latest_vid}

@app.get("/api/playlists/{playlist_id}/videos")
async def get_playlist_videos_route(playlist_id: int):
    return Playlist(playlist_id).get_videos()

@app.post("/api/playlists/{playlist_id}/videos")
async def add_video_to_playlist_route(playlist_id: int, payload: PlaylistVideoAdd):
    Playlist(playlist_id).add_video(payload.video_id)
    return {"status": "success"}

@app.put("/api/playlists/{playlist_id}")
async def rename_playlist_route(playlist_id: int, payload: PlaylistRename):
    Playlist(playlist_id).rename(payload.name)
    return {"status": "success", "name": payload.name}

@app.delete("/api/playlists/{playlist_id}")
async def delete_playlist_route(playlist_id: int):
    Playlist(playlist_id).delete()
    return {"status": "success"}

@app.post("/api/video/{video_id}/rating")
async def update_video_rating_route(video_id: str, payload: VideoRatingRequest):
    if payload.rating < 0 or payload.rating > 3:
        raise HTTPException(status_code=400, detail="Rating must be between 0 and 3")
    Video(video_id).update_rating(payload.rating)
    return {"status": "success", "rating": payload.rating}

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
