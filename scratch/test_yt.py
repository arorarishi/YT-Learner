import yt_dlp
import json

ydl_opts = {
    'extract_flat': 'in_playlist',
    'quiet': True,
    'no_warnings': True,
    'dump_single_json': True,
}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info('https://www.youtube.com/playlist?list=PL2-DAx3wIidb3G4kE1z2B_2X1nE9P4n2g', download=False)
    
if 'entries' in info and len(info['entries']) > 0:
    print("Entry keys:", list(info['entries'][0].keys()))
    print("Entry data:", json.dumps(info['entries'][0], indent=2))
else:
    print("No entries found")
