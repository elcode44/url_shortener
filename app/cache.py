# app/cache.py
from cachetools import TTLCache

# Holds up to 1000 entries, each expires after 1 hour (3600 seconds)
cache = TTLCache(maxsize=1000, ttl=3600)

def get_from_cache(key: str) -> str | None:
    """Return the cached value, or None if missing/expired"""
    return cache.get(key)

def set_in_cache(key: str, value: str) -> None:
    """Store a value in the cache"""
    cache[key] = value

def remove_from_cache(key: str) -> None:
    """Remove a key from the cache (e.g. if the URL is deleted from DB)"""
    cache.pop(key, None)

def cache_size() -> int:
    """Useful for debugging / admin endpoint"""
    return len(cache)