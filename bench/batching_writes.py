"""
Counts how many Postgres writes a fixed number of clicks causes.

Run it once with the app started with ANALYTICS_BATCHING=true (plus worker.py
running) and once with ANALYTICS_BATCHING=false, then compare.

    python bench/batching_writes.py --base http://localhost:8001 \
        --dsn postgresql://postgres:password@localhost:5432/url_shortener

Needs the pg_stat_statements extension (docker-compose.yml preloads it).
"""
import argparse
import asyncio
import random
import time

import httpx
import psycopg2


def pg(dsn, sql):
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall() if cur.description else None
    conn.close()
    return rows


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--dsn", default="postgresql://postgres:password@localhost:5432/url_shortener")
    ap.add_argument("--clicks", type=int, default=10_000)
    ap.add_argument("--links", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--settle", type=int, default=15, help="seconds to wait for the flush worker")
    a = ap.parse_args()

    pg(a.dsn, "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;")

    async with httpx.AsyncClient(base_url=a.base, timeout=30) as c:
        codes = []
        for i in range(a.links):
            r = await c.post("/shorten", json={"long_url": f"https://example.com/bench/{time.time_ns()}/{i}"})
            r.raise_for_status()
            codes.append(r.json()["short_code"])

        code_list = "'" + "','".join(codes) + "'"
        pg(a.dsn, "SELECT pg_stat_statements_reset();")

        # Zipf-ish popularity: a few links get most of the clicks, like real traffic.
        weights = [1 / (i + 1) for i in range(len(codes))]
        targets = random.choices(codes, weights=weights, k=a.clicks)
        sem = asyncio.Semaphore(a.concurrency)
        failures = 0

        async def click(code):
            nonlocal failures
            async with sem:
                r = await c.get(f"/{code}")
                if r.status_code != 302:
                    failures += 1

        t0 = time.time()
        await asyncio.gather(*(click(t) for t in targets))
        elapsed = time.time() - t0

    await asyncio.sleep(a.settle)  # let the batch worker flush

    writes = pg(a.dsn, """
        SELECT coalesce(sum(calls), 0), coalesce(sum(rows), 0)
        FROM pg_stat_statements
        WHERE query ~* '^\\s*UPDATE urls';
    """)[0]
    total_hits = pg(a.dsn, f"SELECT coalesce(sum(hit_count),0) FROM urls WHERE short_code IN ({code_list});")[0][0]

    print(f"clicks sent:            {a.clicks} over {elapsed:.1f}s ({failures} failed)")
    print(f"UPDATE statements:      {writes[0]}")
    print(f"rows written:           {writes[1]}")
    print(f"hit_count total in DB:  {total_hits}  (should equal clicks sent)")


if __name__ == "__main__":
    asyncio.run(main())
