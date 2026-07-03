from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from app.cache import get_from_cache
from app.analytics import record_hit
from app.models import ShortenRequest, ShortenResponse
from app.shortener import shorten, lookup, init_allocator
from db.database import Database

router = APIRouter()
db = Database()
init_allocator(db)


@router.post("/shorten", response_model=ShortenResponse)
def shorten_url(request: ShortenRequest):
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
        short_url=f"http://localhost:8000/{short_code}",
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
def redirect_to_url(short_code: str):
    long_url = lookup(short_code, db)

    if not long_url:
        raise HTTPException(
            status_code=404,
            detail=f"Short code '{short_code}' not found",
        )

    record_hit(short_code)
    return RedirectResponse(url=long_url, status_code=302)