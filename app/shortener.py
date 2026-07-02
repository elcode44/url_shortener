from app.cache import get_from_cache, set_in_cache
from app.id_allocator import RangeAllocator

_allocator: RangeAllocator | None = None


def init_allocator(db, block_size: int = 1000):
    """Call once at startup, after the Database is constructed."""
    global _allocator
    _allocator = RangeAllocator(db, block_size)


def shorten(long_url: str, db) -> str:
    if _allocator is None:
        raise RuntimeError("Allocator not initialized — call init_allocator(db) at startup")

    short_code = _allocator.next_short_code()
    db.save_url(short_code, long_url)
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