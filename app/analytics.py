import redis
from app.cache import r

PENDING_HITS_KEY = "pending_hits"


def record_hit(short_code: str) -> None:
    """
    Fire-and-forget: bump the pending hit counter for this short_code in Redis.
    O(1), no Postgres write on the request path.
    """
    r.hincrby(PENDING_HITS_KEY, short_code, 1)


def pop_pending_hits() -> dict[str, int]:
    """
    Atomically hand off all pending hits and clear them, without losing
    any hits recorded concurrently during the handoff.

    Uses RENAME (atomic in Redis) to move the live hash out of the way
    before reading it, so new hits during the flush accumulate in a
    fresh 'pending_hits' key instead of racing with this read.

    Returns {short_code: count}, or {} if nothing was pending.
    """
    flush_key = f"{PENDING_HITS_KEY}:flush"
    try:
        r.rename(PENDING_HITS_KEY, flush_key)
    except redis.exceptions.ResponseError:
        # PENDING_HITS_KEY doesn't exist yet -- nothing to flush
        return {}

    raw = r.hgetall(flush_key)
    r.delete(flush_key)
    return {k: int(v) for k, v in raw.items()}