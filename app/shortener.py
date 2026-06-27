import hashlib
import base64
from app.cache import get_from_cache, set_in_cache


def generate_short_code(long_url: str) -> str:
    hash_bytes = hashlib.md5(long_url.encode()).digest()
    return base64.urlsafe_b64encode(hash_bytes)[:6].decode()


def shorten(long_url: str, db) -> str:
    short_code = generate_short_code(long_url)

    cached = get_from_cache(short_code)
    if cached:
        return short_code

    existing = db.find_url(short_code)
    if not existing:
        db.save_url(short_code, long_url)
    elif existing.long_url != long_url:
        raise ValueError(
            f"Short code '{short_code}' already maps to a different URL"
        )

    set_in_cache(short_code, long_url)
    return short_code


def lookup(short_code: str, db) -> str | None:
    cached = get_from_cache(short_code)
    if cached:
        return cached

    record = db.get_url(short_code)
    if not record:
        return None

    set_in_cache(short_code, record.long_url)
    return record.long_url
