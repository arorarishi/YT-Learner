from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from ..db.factory import get_db
from .utils import fetch_latest_video_id

scheduler = BackgroundScheduler()


def daily_refresh_job():
    db = get_db()
    channels = db.list_followed_channels()
    for ch in channels:
        channel_id = ch['channel_id']
        last_video = ch.get('last_fetched_video_id')
        latest_video_id = fetch_latest_video_id(channel_id)
        if not latest_video_id:
            continue
        if latest_video_id != last_video:
            try:
                db.add_video_to_channel_playlist(channel_id, latest_video_id)
                db.update_last_fetched(channel_id, latest_video_id, datetime.utcnow().isoformat())
                print(f"[Scheduler] Added new video {latest_video_id} to playlist for channel {channel_id}")
            except Exception as e:
                print(f"[Scheduler] Error adding video for channel {channel_id}: {e}")


scheduler.add_job(daily_refresh_job, 'cron', hour=2, minute=0, id='daily_refresh')
