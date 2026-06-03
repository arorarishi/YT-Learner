import time
import yt_dlp
from typing import Optional

def extract_channel_id(url_or_id: str) -> str:
    """Extract a YouTube channel ID from a full URL or return the ID if already provided."""
    # If looks like an ID (no slashes), return as is
    if '/' not in url_or_id:
        return url_or_id.strip()
    # Possible URL patterns:
    # https://www.youtube.com/channel/UCxxxx
    # https://www.youtube.com/@ChannelName
    # https://www.youtube.com/c/ChannelName
    # We'll extract the part after the last '/' or after '@'
    import re
    # Try channel ID pattern
    m = re.search(r"/channel/([A-Za-z0-9_-]+)", url_or_id)
    if m:
        return m.group(1)
    # Try @handle pattern
    m = re.search(r"@([^/?]+)", url_or_id)
    if m:
        return m.group(1)
    # Try /c/ or /user/ naming – not a true ID but we can still use the name as identifier
    m = re.search(r"/c/([^/?]+)", url_or_id) or re.search(r"/user/([^/?]+)", url_or_id)
    if m:
        return m.group(1)
    # Fallback: return the whole string (may be a custom ID)
    return url_or_id.strip()

def fetch_latest_video_id(channel_id: str) -> Optional[str]:
    """Return the most recent video ID for a given channel using yt_dlp.
    Returns None if no videos are found or an error occurs.
    """
    ydl_opts = {
        "ignoreerrors": True,
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "playlist_items": "1",  # grab the latest video (first item)
    }
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    try:
        _t0 = time.perf_counter()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        print(f"LATENCY [yt-dlp/channel-latest {channel_id}]: {time.perf_counter()-_t0:.2f}s")
            # info['entries'] is a list, newest first
            if not info or 'entries' not in info or not info['entries']:
                return None
            first = info['entries'][0]
            return first.get('id')
    except Exception as e:
        print(f"Error fetching latest video for channel {channel_id}: {e}")
        return None
