"""
Background worker that periodically flushes buffered Redis hit-counts
into Postgres. Runs as its own container so it scales/restarts
independently of the API process.
"""
import time
import signal
import sys

from db.database import Database
from app.analytics import pop_pending_hits

FLUSH_INTERVAL_SECONDS = 10

_running = True


def _handle_shutdown(signum, frame):
    global _running
    print(f"Worker received signal {signum}, shutting down after current flush...")
    _running = False


def main():
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    db = Database()
    print(f"Analytics flush worker started (interval={FLUSH_INTERVAL_SECONDS}s)")

    while _running:
        time.sleep(FLUSH_INTERVAL_SECONDS)
        counts = pop_pending_hits()
        if counts:
            updated = db.flush_hit_counts(counts)
            print(f"Flushed {len(counts)} short codes, {updated} rows updated")

    # Final flush on graceful shutdown so we don't drop counts on redeploys
    counts = pop_pending_hits()
    if counts:
        updated = db.flush_hit_counts(counts)
        print(f"Final flush: {len(counts)} short codes, {updated} rows updated")

    db.close()
    sys.exit(0)


if __name__ == "__main__":
    main()