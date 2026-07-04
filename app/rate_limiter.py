import os
import time
from fastapi import HTTPException, Request
from app.cache import r

# Requests allowed per window, per IP, per endpoint
LIMITS = {
    "shorten": (20, 60),   # 20 requests / 60 seconds
    "redirect": (60, 60),  # redirects are read-heavy, allow more
}

# Set RATE_LIMIT_ENABLED=false during load testing -- a per-IP limiter
# can't be load-tested meaningfully when every simulated user shares
# one machine's IP. Leave it unset/true for normal use.
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"


def _client_ip(request: Request) -> str:
    # Respect a reverse proxy's forwarded header (Nginx, once you add it in
    # Step 5) but fall back to the direct connecting IP for local dev.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, bucket: str) -> None:
    """
    Sliding-window rate limit using a Redis sorted set.

    Each request's timestamp is added as a member of a ZSET keyed by
    IP + bucket. Members older than the window are trimmed on every
    call, so ZCARD always reflects "requests in the last N seconds" --
    no fixed-window boundary bursting.
    """
    if not RATE_LIMIT_ENABLED:
        return

    limit, window_seconds = LIMITS[bucket]
    ip = _client_ip(request)
    key = f"ratelimit:{bucket}:{ip}"

    now = time.time()
    window_start = now - window_seconds

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)   # drop expired entries
    pipe.zadd(key, {str(now): now})               # record this request
    pipe.zcard(key)                                # count requests in window
    pipe.expire(key, window_seconds)               # let Redis clean up idle keys
    _, _, count, _ = pipe.execute()

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per {window_seconds}s",
        )