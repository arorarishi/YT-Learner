from typing import Optional
from pydantic import BaseModel


class SummarizeRequest(BaseModel):
    url: str
    template_type: str = "summary"
    user_id: str


class SummarizeResponse(BaseModel):
    summary: str
    video_id: str
    title: Optional[str] = None
    channel_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    transcript: Optional[str] = None
    tags: Optional[str] = None


class FollowChannelRequest(BaseModel):
    channel: str
    name: Optional[str] = None


class VideoRatingRequest(BaseModel):
    rating: int
