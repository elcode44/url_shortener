# app/cache.py
import redis
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
r = redis.from_url(REDIS_URL, decode_responses=True)

def get_from_cache(key: str) -> str | None:
    return r.get(key)

def set_in_cache(key: str, value: str, ttl: int = 3600) -> None:
    r.set(key, value, ex=ttl)

def remove_from_cache(key: str) -> None:
    r.delete(key)