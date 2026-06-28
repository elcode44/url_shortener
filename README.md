# URL Shortener

A FastAPI service that turns long URLs into short codes, stores them in PostgreSQL, and redirects visitors to the original link. Includes a Redis cache for fast lookups and basic analytics (hit counts).

## Features

- **Shorten URLs** — deterministic 6-character codes generated from the long URL
- **Redirect** — `GET /{short_code}` returns a 302 redirect to the original URL
- **Inspect** — view URL metadata without triggering a redirect
- **Caching** — Redis TTL cache (1-hour expiry) to reduce database reads
- **Analytics** — hit count incremented on each redirect (not on shorten or inspect)
- **Auto docs** — interactive API docs at `/docs`

## Project Structure

```
URL_shortner/
├── main.py              # FastAPI app entry point
├── Dockerfile           # App container image
├── docker-compose.yml   # App + PostgreSQL + Redis
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables for local dev (not committed)
├── app/
│   ├── routes.py        # HTTP endpoints
│   ├── shortener.py     # URL hashing, shorten/lookup logic
│   ├── cache.py         # Redis cache helpers
│   └── models.py        # Pydantic request/response models
├── db/
│   └── database.py      # PostgreSQL connection and queries
└── tests/
    └── test_shortener.py
```

## Prerequisites

- **Docker Desktop** (recommended — runs the full stack)
- **Python 3.11+** and **pip** (only needed for local development without Docker)

## Quick Start (Docker Compose)

This is the easiest way to run the app, PostgreSQL, and Redis together.

### 1. Start the stack

```powershell
cd c:\projects_faang\URL_shortner
docker compose up --build
```

Wait until you see:

```text
url_shortener_app  | Server started — docs at http://localhost:8000/docs
url_shortener_app  | INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2. Open the API docs

In your browser, go to:

**http://localhost:8000/docs**

Use `localhost` or `127.0.0.1` — **not** `http://0.0.0.0:8000`. The `0.0.0.0` address in the Uvicorn log is the bind address inside the container (listen on all interfaces). It is not a URL you open in a browser.

There is no homepage at `/`. If you visit `http://localhost:8000/` you will get `{"detail":"Not Found"}` — that is expected. Use `/docs` or the API endpoints below.

### 3. Stop the stack

Press `Ctrl+C` in the terminal, then:

```powershell
docker compose down
```

To also remove the PostgreSQL data volume:

```powershell
docker compose down -v
```

### What Docker Compose runs

| Service  | Container name      | Host port |
|----------|---------------------|-----------|
| FastAPI  | `url_shortener_app` | 8000      |
| Postgres | `postgres`          | 5432      |
| Redis    | `redis`             | 6379      |

Environment variables for the app container are set in `docker-compose.yml` — no `.env` file is required for Docker Compose.

## Local Development (without Docker for the app)

Use this if you want hot reload with `uvicorn --reload`. You still need PostgreSQL and Redis running (Docker is fine for those).

### 1. Install dependencies

```powershell
cd c:\projects_faang\URL_shortner
pip install -r requirements.txt
```

### 2. Start PostgreSQL and Redis

With Docker Compose (app service only is optional — or start postgres + redis manually):

```powershell
docker compose up postgres redis -d
```

Or start an existing postgres container:

```powershell
docker start postgres
```

You also need Redis on port `6379`. The compose file starts it as container `redis`.

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/url_shortener
REDIS_URL=redis://localhost:6379
```

| Variable       | Description                          |
|----------------|--------------------------------------|
| `DATABASE_URL` | PostgreSQL connection string         |
| `REDIS_URL`    | Redis connection string              |

The default values match the Docker Compose services: user `postgres`, password `password`, database `url_shortener`.

The `urls` table is created automatically on first startup — no manual migration needed.

### 4. Run the app

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

If port 8000 is unavailable, use another port (e.g. `8001`).

Once running:

- **API docs:** http://localhost:8000/docs
- **Try it:** shorten a URL via the docs UI or the examples below

## API Endpoints

### `POST /shorten`

Create a short code for a long URL. The same long URL always produces the same short code.

**Request:**

```json
{
  "long_url": "https://example.com/some/very/long/path"
}
```

**Response (200):**

```json
{
  "short_code": "e6gYNz",
  "short_url": "http://localhost:8000/e6gYNz",
  "long_url": "https://example.com/some/very/long/path",
  "created_at": "2026-06-27T15:20:10"
}
```

**Example (PowerShell):**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/shorten" `
  -Method POST `
  -Body '{"long_url": "https://example.com"}' `
  -ContentType "application/json"
```

**Errors:**

| Status | When |
|--------|------|
| 409    | Hash collision — short code already maps to a different URL |
| 422    | Invalid URL in request body |
| 500    | Database or server error |

---

### `GET /{short_code}`

Redirect to the original URL.

**Response:** `302 Found` with `Location` header set to the long URL.

**Example:**

Open `http://localhost:8000/e6gYNz` in a browser — you will be redirected to the original URL.

**Errors:**

| Status | When |
|--------|------|
| 404    | Short code not found |

---

### `GET /inspect/{short_code}`

Return URL metadata without redirecting or incrementing the hit count.

**Response (200):**

```json
{
  "short_code": "e6gYNz",
  "long_url": "https://example.com/some/very/long/path",
  "hit_count": 3,
  "created_at": "2026-06-27T15:20:10"
}
```

**Example:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/inspect/e6gYNz"
```

## How It Works

### Short code generation

1. The long URL is hashed with MD5.
2. The hash is base64-encoded and truncated to 6 URL-safe characters.
3. The same input URL always produces the same short code (deterministic).

### Request flow — shorten

```
Client → POST /shorten
       → Check Redis cache
       → Check PostgreSQL (find_url — no hit count change)
       → Insert if new
       → Store in cache
       → Return short code + metadata
```

### Request flow — redirect

```
Client → GET /{short_code}
       → Check Redis cache
       → PostgreSQL lookup (get_url — increments hit_count)
       → Store in cache
       → 302 redirect to long URL
```

### Caching

- **Backend:** Redis
- **TTL:** 1 hour per entry (default)
- Cache survives app restarts when using Docker Compose (Redis runs as its own container)

### Database schema

Table: `urls`

| Column       | Type         | Description                    |
|--------------|--------------|--------------------------------|
| `short_code` | VARCHAR(10)  | Primary key                    |
| `long_url`   | TEXT         | Original URL                   |
| `created_at` | TIMESTAMP    | When the link was created      |
| `hit_count`  | INTEGER      | Number of redirects served     |
| `expires_at` | TIMESTAMP    | Optional expiry (unused by default) |

## Troubleshooting

### Browser shows an error for `http://0.0.0.0:8000`

Use **http://localhost:8000/docs** instead. `0.0.0.0` is only the server bind address inside the container.

### `GET /` returns 404 in the terminal logs

That is normal — there is no root route. Open `/docs` or call an API endpoint.

### Mixed log lines from postgres and the app

Docker Compose prints logs from all services together. Lines like `write=... sync=...` come from PostgreSQL checkpoint activity, not from your app failing.

### `Connection refused` on port 5432

PostgreSQL is not running. With Docker Compose:

```powershell
docker compose up postgres -d
```

Or start an existing container:

```powershell
docker start postgres
```

### `connection to server at "localhost" ... failed`

- Confirm containers are up: `docker compose ps`
- Confirm `.env` has the correct `DATABASE_URL` (local dev only)
- Wait a few seconds after startup — Postgres needs a moment to initialize

### Redis connection errors (local dev)

Ensure Redis is running on port `6379` and `REDIS_URL=redis://localhost:6379` is set in `.env`. With Docker Compose, Redis starts automatically.

### Port 8000 already in use

Stop the other process or use a different port:

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

Then use `http://localhost:8001` in API calls and the browser.

### Short code not found after restart

Data persists in PostgreSQL across app restarts when using the `pgdata` Docker volume. If you ran `docker compose down -v`, the database data is removed. Shorten URLs again after recreating the stack.

## Tech Stack

| Component     | Technology        |
|---------------|-------------------|
| Web framework | FastAPI           |
| Server        | Uvicorn           |
| Database      | PostgreSQL 16     |
| Cache         | Redis             |
| DB driver     | psycopg2          |
| Validation    | Pydantic          |
| Config        | python-dotenv     |
| Containers    | Docker Compose    |
