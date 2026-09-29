# URL Shortener

A FastAPI service that turns long URLs into short codes, stores them in PostgreSQL, and redirects visitors to the original link. Built for horizontal scale: distributed ID generation, Redis-buffered analytics, rate limiting, and load-balanced replicas behind Nginx.

## Features

- **Shorten URLs** — unique Base62-encoded short codes generated from a distributed counter (no hash collisions, safe across multiple replicas)
- **Redirect** — `GET /{short_code}` returns a 302 redirect to the original URL
- **Inspect** — view URL metadata without triggering a redirect
- **Caching** — Redis read-through cache (1-hour TTL), capped at 100MB with `allkeys-lru` eviction
- **Analytics** — hit counts are buffered in Redis on every redirect and flushed to PostgreSQL in batches every 10 seconds by a background worker, instead of writing to the database on every request
- **Rate limiting** — Redis sorted-set sliding-window limiter, per IP, on `/shorten` and `/{short_code}`
- **Horizontal scaling** — 3 FastAPI replicas behind an Nginx round-robin load balancer
- **Auto docs** — interactive API docs at `/docs`

## Architecture

```
                    ┌─────────┐
   Client ────────▶ │  Nginx  │  (round-robin load balancer)
                    └────┬────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
       ┌───────┐     ┌───────┐     ┌───────┐
       │ app1  │     │ app2  │     │ app3  │   (FastAPI, 4 Uvicorn workers each)
       └───┬───┘     └───┬───┘     └───┬───┘
           │             │             │
           └──────┬──────┴──────┬──────┘
                   ▼             ▼
              ┌─────────┐  ┌────────────┐
              │  Redis  │  │ PostgreSQL │
              └────┬────┘  └─────┬──────┘
                   │             ▲
                   ▼             │
              ┌─────────────────────┐
              │  worker.py          │  (flushes buffered hit
              │  (background flush) │   counts every 10s)
              └─────────────────────┘
```

Redis serves three separate purposes here, not just caching:

1. **URL cache** — read-through cache for `short_code → long_url` lookups
2. **Rate limiting** — sliding-window counters per IP
3. **Analytics buffering** — pending hit counts, decoupled from the request path

ID allocation lives in Postgres: each replica reserves a block of IDs from a single-row counter table (see "Short code generation").

## Project Structure

```
URL_shortner/
├── main.py                 # FastAPI app entry point
├── worker.py               # Background worker: flushes buffered hit counts to Postgres every 10s
├── locustfile.py           # Load test definitions (Locust)
├── Dockerfile              # App container image (runs Uvicorn with 4 workers)
├── docker-compose.yml      # app1/app2/app3 + Nginx + PostgreSQL + Redis + worker
├── nginx.conf              # Round-robin upstream config for the 3 app replicas
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables for local dev (not committed)
├── app/
│   ├── routes.py           # HTTP endpoints
│   ├── shortener.py        # Shorten/lookup logic (Base62 short code generation)
│   ├── id_allocator.py     # Distributed range allocator + Base62 encoding
│   ├── analytics.py        # Redis-buffered hit-count recording and flushing
│   ├── rate_limiter.py     # Sliding-window rate limiter (Redis sorted sets)
│   ├── cache.py            # Redis cache helpers
│   └── models.py           # Pydantic request/response models
├── db/
│   └── database.py         # PostgreSQL connection pool, queries, ID block allocation
└── tests/
    └── test_shortener.py
```

## Prerequisites

- **Docker Desktop** (recommended — runs the full stack)
- **Python 3.11+** and **pip** (only needed for local development without Docker, or for running load tests)

## Quick Start (Docker Compose)

This runs the full distributed stack: 3 app replicas, Nginx, PostgreSQL, Redis, and the analytics worker.

### 1. Start the stack

```powershell
cd c:\projects_faang\URL_shortner
docker compose up --build
```

Wait until all services report ready. Check status in another terminal:

```powershell
docker compose ps
```

You should see `nginx`, `app1`, `app2`, `app3`, `postgres`, `redis`, and `worker` all `Up`.

### 2. Open the API docs

**http://localhost:8001/docs**

All traffic goes through Nginx on port **8001**, which load-balances across the 3 app replicas. There is no reason to reach `app1`/`app2`/`app3` directly in normal use.

There is no homepage at `/`. Visiting `http://localhost:8001/` returns `{"detail":"Not Found"}` — that's expected. Use `/docs` or the API endpoints below.

> **Note on `/docs` and redirects:** Swagger UI's "Try it out" button uses `fetch()` in the browser, which will fail on the `GET /{short_code}` endpoint with a CORS-related error when it tries to follow the 302. This is a Swagger UI limitation, not a bug — test redirects by pasting the short URL directly into your browser's address bar, or with `curl -i`.

### 3. Stop the stack

```powershell
docker compose down
```

To also remove the PostgreSQL data volume:

```powershell
docker compose down -v
```

### What Docker Compose runs

| Service    | Container name         | Reachable at                 |
| ---------- | ---------------------- | ---------------------------- |
| Nginx      | `url_shortener_nginx`  | `localhost:8001` (host)      |
| FastAPI ×3 | `app1`, `app2`, `app3` | internal only (behind Nginx) |
| Worker     | `url_shortener_worker` | internal only                |
| Postgres   | `postgres`             | `localhost:5432`             |
| Redis      | `redis`                | `localhost:6379`             |

Environment variables are set directly in `docker-compose.yml` — no `.env` file is required for Docker Compose.

### Toggle switches (for testing / debugging)

These default to production-safe values and only need to be touched when isolating a specific piece of the stack (e.g. load testing):

| Variable             | Default | Effect when set to `false`                                        |
| -------------------- | ------- | ----------------------------------------------------------------- |
| `CACHE_ENABLED`      | `true`  | Bypasses the Redis URL cache; every lookup hits Postgres directly |
| `RATE_LIMIT_ENABLED` | `true`  | Disables the per-IP rate limiter entirely                         |
| `ANALYTICS_BATCHING` | `true`  | Writes every click straight to Postgres (only for benchmarking)   |

Example:

```powershell
$env:CACHE_ENABLED="false"
docker compose up --build
```

`app1` additionally has a direct host port mapping (`8002:8000`) so it can be load-tested in isolation, without Nginx or the other replicas, by pointing requests at `http://localhost:8002`.

## Local Development (without Docker for the app)

Use this if you want hot reload with `uvicorn --reload`. You still need PostgreSQL and Redis running (Docker is fine for those).

### 1. Install dependencies

```powershell
cd c:\projects_faang\URL_shortner
pip install -r requirements.txt
```

### 2. Start PostgreSQL and Redis only

```powershell
docker compose up postgres redis -d
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/url_shortener
REDIS_URL=redis://localhost:6379
BASE_URL=http://localhost:8000
```

The default values match the Docker Compose services: user `postgres`, password `password`, database `url_shortener`.

Tables (`urls` and `id_counter`) are created automatically on first startup — no manual migration needed.

### 4. Run the app

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

If you want buffered hit counts actually flushed to Postgres in this mode, also run the worker in a separate terminal:

```powershell
python worker.py
```

## API Endpoints

### `POST /shorten`

Create a unique short code for a long URL. Each call generates a new, unique code — calling this twice with the same URL produces two different short codes (this is a deliberate tradeoff of the distributed counter approach; see "How It Works" below).

**Request:**

```json
{
  "long_url": "https://example.com/some/very/long/path"
}
```

**Response (200):**

```json
{
  "short_code": "4a6",
  "short_url": "http://localhost:8001/4a6",
  "long_url": "https://example.com/some/very/long/path",
  "created_at": "2026-07-03T15:20:10"
}
```

**Example (PowerShell):**

```powershell
Invoke-RestMethod -Uri "http://localhost:8001/shorten" `
  -Method POST `
  -Body '{"long_url": "https://example.com"}' `
  -ContentType "application/json"
```

**Errors:**

| Status | When                                         |
| ------ | -------------------------------------------- |
| 422    | Invalid URL in request body                  |
| 429    | Rate limit exceeded (20 requests/60s per IP) |
| 500    | Database or server error                     |

---

### `GET /{short_code}`

Redirect to the original URL. Also records a hit in Redis (flushed to Postgres asynchronously — see "How It Works").

**Response:** `302 Found` with `Location` header set to the long URL.

**Errors:**

| Status | When                                         |
| ------ | -------------------------------------------- |
| 404    | Short code not found                         |
| 429    | Rate limit exceeded (60 requests/60s per IP) |

---

### `GET /inspect/{short_code}`

Return URL metadata without redirecting or incrementing the hit count.

**Response (200):**

```json
{
  "short_code": "4a6",
  "long_url": "https://example.com/some/very/long/path",
  "hit_count": 3,
  "created_at": "2026-07-03T15:20:10"
}
```

> `hit_count` is eventually consistent — it can lag up to ~10 seconds behind real traffic, since hits are buffered in Redis and flushed to Postgres in batches rather than written on every redirect. This is a deliberate tradeoff to keep the redirect path fast under load.

## How It Works

### Short code generation

1. Each replica reserves a block of IDs (default 1,000) from a shared Postgres counter in a single atomic `UPDATE ... RETURNING`.
2. IDs are handed out from that in-memory block one at a time, avoiding a database round-trip per request.
3. When a block is exhausted, the replica reserves the next one.
4. Each integer ID is Base62-encoded (`0-9`, `a-z`, `A-Z`) into the final short code.

This guarantees uniqueness across any number of replicas without coordination between them, and without the collision risk of hashing.

### Request flow — shorten

```
Client → POST /shorten
       → Rate limit check (Redis)
       → Reserve next ID from allocator (Postgres-backed block)
       → Base62-encode ID → short_code
       → Save to PostgreSQL
       → Store in Redis cache
       → Return short code + metadata
```

### Request flow — redirect

```
Client → GET /{short_code}
       → Rate limit check (Redis)
       → Check Redis cache → PostgreSQL fallback (no hit-count write here)
       → Buffer hit in Redis (HINCRBY)
       → 302 redirect to long URL

Meanwhile, every 10s:
worker.py → pop buffered hits from Redis → batch UPDATE into PostgreSQL
```

Moving the hit-count write off the request path was the single biggest throughput improvement in this project — the old design updated a row in Postgres on every redirect, which serialized all redirect traffic against the database.

### Caching

- **Backend:** Redis
- **TTL:** 1 hour per entry
- **Eviction:** capped at 100MB, `allkeys-lru` policy — least-recently-used keys are evicted once memory fills up, regardless of TTL
- Cache survives app restarts (Redis runs as its own container with its own lifecycle)

### Rate limiting

Sliding-window algorithm implemented with a Redis sorted set per IP per endpoint. Unlike a fixed window, this doesn't allow a burst of `2×limit` requests at a window boundary — the count always reflects the trailing N seconds exactly.

| Endpoint            | Limit                    |
| ------------------- | ------------------------ |
| `POST /shorten`     | 20 requests / 60s per IP |
| `GET /{short_code}` | 60 requests / 60s per IP |

### Database schema

Table: `urls`

| Column       | Type        | Description                                        |
| ------------ | ----------- | -------------------------------------------------- |
| `short_code` | VARCHAR(10) | Primary key                                        |
| `long_url`   | TEXT        | Original URL                                       |
| `created_at` | TIMESTAMP   | When the link was created                          |
| `hit_count`  | INTEGER     | Number of redirects served (eventually consistent) |
| `expires_at` | TIMESTAMP   | Optional expiry (unused by default)                |

Table: `id_counter`

| Column          | Type    | Description                                |
| --------------- | ------- | ------------------------------------------ |
| `id`            | INTEGER | Always `1` (single row, enforced by CHECK) |
| `current_value` | BIGINT  | High-water mark for allocated ID blocks    |

## Load Testing

`locustfile.py` simulates realistic traffic (weighted toward redirects, as in real-world usage) against `/shorten`, `/{short_code}`, and `/inspect/{short_code}`.

```powershell
pip install locust httpx psycopg2-binary
python bench/run_load_test.py      # clean run + replica kill, prints RPS / failures / p50 / p99
```

Or run Locust by hand:

Run distributed across multiple processes for accurate results (Locust's `--processes` flag isn't supported on native Windows, so use master/worker mode across separate terminals):

```powershell
# 3 terminals:
locust -f locustfile.py --worker --master-host=127.0.0.1

# 1 terminal (start last):
locust -f locustfile.py --master --headless -u 150 -r 15 -t 90s --host=http://localhost:8001 --csv=results
```

**Earlier results, before the connection-pool fix** (150 concurrent users, cache enabled, rate limiting disabled for testing purposes — see toggle switches above):

| Configuration                    | Failure rate | p99 latency |
| -------------------------------- | ------------ | ----------- |
| Single instance, no cache        | 0.73%        | 190ms       |
| 3 replicas + Nginx + Redis cache | **0%**       | **100ms**   |

The distributed setup eliminates failures entirely at this load and roughly halves p99 latency. Failure rates on both configurations climb sharply beyond ~225 concurrent users — that ceiling is a function of the current Postgres/Nginx connection and timeout settings (see `docker-compose.yml`'s `max_connections` and `nginx.conf`'s `proxy_*_timeout` directives), not an inherent limit of the architecture. (That ceiling turned out to be connection-pool exhaustion. See Benchmark Results below for the fix and current numbers.)

## Benchmark Results

All numbers below are from real runs, reproducible with the scripts in `bench/`.
Machine: Windows 11 laptop, Intel Core Ultra (22 threads), Docker Desktop with 8 GB.
Load tests ran with `RATE_LIMIT_ENABLED=false` (every simulated user shares one IP).

### Sustained load: 3 replicas behind Nginx

`python bench/run_load_test.py`: 400 Locust users at a fixed 2 req/s each for 4 minutes.
Traffic mix is 10 redirects : 3 inspects : 1 shorten.

| Run | Steady RPS | Requests | Failures | p50 | p99 |
| --- | --- | --- | --- | --- | --- |
| Clean (all 3 replicas up) | 801 | 188,375 | **0** | 43 ms | 160 ms |
| `docker stop app2` at t=120 s | 799 (798 after the kill) | 188,581 | 5 (0.003%) | 43 ms | 140 ms |

After the kill, the two remaining replicas absorbed the full ~800 RPS. Nginx
retries failed `GET`s on another replica (`proxy_next_upstream`), so no redirect
or inspect failed. The 5 failures were `POST /shorten` calls in flight on the
dying replica. Nginx deliberately doesn't retry `POST`, since replaying a create
could make a duplicate link.

**Bugs these tests found and fixed:**
- *Connection pool exhaustion.* Each process had a 10-connection Postgres pool but
  up to 40 request threads, and psycopg2 raises `PoolError` instead of waiting.
  An earlier 300-user run held ~900 RPS for 15 s, then collapsed to ~20% failures.
  A semaphore in `db/database.py` now makes threads wait for a free connection.
  Same load before/after on a 2-vCPU box: 1,202 failures → 0.
- *Stale upstream IPs.* Nginx resolves `app1-3` once at startup. After the app
  containers were rebuilt, it kept dialing old IPs. The runner now recreates Nginx
  with the stack, and a dead replica is abandoned after 1 s (`proxy_connect_timeout`).

### Analytics batching: Postgres writes per 10,000 clicks

`python bench/batching_writes.py`: 10,000 redirects over 100 links (Zipf-like popularity),
run once with `ANALYTICS_BATCHING=true` (Redis buffer + 10 s flush worker) and once with it off.

| Mode | UPDATE statements | Rows written | `hit_count` total |
| --- | --- | --- | --- |
| Unbatched (write per click) | 10,000 | 10,000 | 10,000 |
| Batched (Redis + worker) | 2 | 198 | 10,000 |

About **50x fewer row writes** (5,000x fewer statements), with no clicks lost.
Row count depends on how many flush windows the traffic spans (one row per active link per 10 s).
At 50 concurrent clients, the unbatched mode also failed 13% of requests from pool
exhaustion before the fix above, which is the lock/connection pressure batching avoids.

### Edge cache: Cloudflare Worker + KV

`python bench/latency.py`: median of 100 redirects from the laptop (US East), keep-alive HTTPS.
The origin is the FastAPI stack exposed through a Cloudflare quick tunnel. Every Worker
request was a KV cache HIT. See [`edge/README.md`](edge/README.md).

| Path | Median | p90 |
| --- | --- | --- |
| Origin: Cloudflare → tunnel → Nginx → FastAPI | 75.4 ms | 109.9 ms |
| Worker, KV hit (origin never contacted) | **29.1 ms** | **32.1 ms** |


## Troubleshooting

### `ModuleNotFoundError` on container startup

Check that the file it's complaining about actually exists on disk at the expected path — since the app directory is mounted as a Docker volume, a missing file on the host is missing inside the container too. `docker compose logs <service>` will show the traceback.

### 502 Bad Gateway from Nginx under load

Nginx gives up on a backend after `proxy_read_timeout` (currently 10s, set in `nginx.conf`). A 502 under heavy load usually means a backend replica was still busy past that window — check `docker compose ps` for crashed containers first, then consider whether Postgres's `max_connections` or the app's connection pool size (`db = Database(minconn=2, maxconn=10)` in `app/routes.py`) needs adjusting.

### Rate limit errors (429) during manual testing

Expected if you're sending many requests quickly from one IP. Set `RATE_LIMIT_ENABLED=false` (see toggle switches above) if you need to bypass it temporarily.

### Port 8001 already in use

Stop whatever else is bound to it, or change Nginx's host port mapping in `docker-compose.yml`.

### Short code not found after restart

Data persists in PostgreSQL across restarts via the `pgdata` Docker volume. If you ran `docker compose down -v`, the data was removed — shorten URLs again after recreating the stack.

## Tech Stack

| Component            | Technology                                                         |
| -------------------- | ------------------------------------------------------------------ |
| Web framework        | FastAPI (Uvicorn, 4 workers per replica)                           |
| Load balancer        | Nginx (round-robin)                                                |
| Database             | PostgreSQL 16                                                      |
| Cache / coordination | Redis (caching, rate limiting, analytics buffering)                |
| ID allocation        | PostgreSQL single-row counter, block reservation per replica       |
| Edge cache           | Cloudflare Workers + Workers KV (see `edge/`)                       |
| DB driver            | psycopg2 (`ThreadedConnectionPool`)                                |
| Validation           | Pydantic                                                           |
| Load testing         | Locust                                                             |
| Containers           | Docker Compose                                                     |

![Locust load test: 300 concurrent users, 0% failure rate](./screenshots/locust_300_users.png)
