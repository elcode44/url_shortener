from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.cache import get_from_cache
from app.analytics import record_hit
from app.rate_limiter import enforce_rate_limit
from app.models import ShortenRequest, ShortenResponse
from app.shortener import shorten, lookup, init_allocator
from db.database import Database
import os

BASE_URL = os.getenv("BASE_URL", "http://localhost:8001")


router = APIRouter()
db = Database(minconn=2, maxconn=10)
init_allocator(db)


@router.post("/shorten", response_model=ShortenResponse)
def shorten_url(request: ShortenRequest, http_request: Request):
    enforce_rate_limit(http_request, "shorten")

    long_url = str(request.long_url)

    try:
        short_code = shorten(long_url, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to shorten URL: {str(e)}")

    record = db.find_url(short_code)
    if not record:
        raise HTTPException(status_code=500, detail="Failed to retrieve saved URL")

    return ShortenResponse(
        short_code=short_code,
        short_url=f"{BASE_URL}/{short_code}",
        long_url=long_url,
        created_at=record.created_at,
    )


@router.get("/inspect/{short_code}")
def inspect_url(short_code: str):
    record = db.find_url(short_code)
    if record:
        return {
            "short_code": short_code,
            "long_url": record.long_url,
            "hit_count": record.hit_count,
            "created_at": record.created_at,
        }

    cached = get_from_cache(short_code)
    if cached:
        return {"short_code": short_code, "long_url": cached}

    raise HTTPException(
        status_code=404,
        detail=f"Short code '{short_code}' not found",
    )


@router.get("/{short_code}")
def redirect_to_url(short_code: str, http_request: Request):
    enforce_rate_limit(http_request, "redirect")

    long_url = lookup(short_code, db)

    if not long_url:
        raise HTTPException(
            status_code=404,
            detail=f"Short code '{short_code}' not found",
        )

    record_hit(short_code)
    return RedirectResponse(url=long_url, status_code=302)