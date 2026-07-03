# app/cache.py
import os
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"

r = redis.from_url(REDIS_URL, decode_responses=True)


def get_from_cache(key: str) -> str | None:
    if not CACHE_ENABLED:
        return None
    return r.get(key)


def set_in_cache(key: str, value: str, ttl: int = 3600) -> None:
    if not CACHE_ENABLED:
        return
    r.set(key, value, ex=ttl)


def remove_from_cache(key: str) -> None:
    if not CACHE_ENABLED:
        return
    r.delete(key)