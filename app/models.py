# app/models.py
from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional

# ── Request Models (what comes IN) ─────────────────────────

class ShortenRequest(BaseModel):
    long_url: HttpUrl

class CustomSlugRequest(BaseModel):
    long_url: HttpUrl
    custom_slug: str  # e.g. "my-link" → localhost:8000/my-link

# ── Response Models (what goes OUT) ────────────────────────

class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str
    created_at: datetime

class URLInfo(BaseModel):
    short_code: str
    long_url: str
    created_at: datetime
    hit_count: int  # how many times it's been visited

# ── DB Model (what lives in Postgres) ──────────────────────

class URLRecord(BaseModel):
    short_code: str
    long_url: str
    created_at: datetime = datetime.utcnow()
    hit_count: int = 0
    expires_at: Optional[datetime] = None  # None = never expires