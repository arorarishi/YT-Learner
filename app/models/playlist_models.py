from typing import Optional
from pydantic import BaseModel


class PlaylistCreate(BaseModel):
    name: str


class PlaylistVideoAdd(BaseModel):
    video_id: str


class PlaylistImportRequest(BaseModel):
    url: str


class PlaylistRename(BaseModel):
    name: str
