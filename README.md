# URL Shortener

A FastAPI service that turns long URLs into short codes, stores them in PostgreSQL, and redirects visitors to the original link. Includes an in-memory cache for fast lookups and basic analytics (hit counts).

## Features

- **Shorten URLs** — deterministic 6-character codes generated from the long URL
- **Redirect** — `GET /{short_code}` returns a 302 redirect to the original URL
- **Inspect** — view URL metadata without triggering a redirect
- **Caching** — in-memory TTL cache (1000 entries, 1-hour expiry) to reduce database reads
- **Analytics** — hit count incremented on each redirect (not on shorten or inspect)
- **Auto docs** — interactive API docs at `/docs`

## Project Structure

```
URL_shortner/
├── main.py              # FastAPI app entry point
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (not committed — create from example below)
├── app/
│   ├── routes.py        # HTTP endpoints
│   ├── shortener.py     # URL hashing, shorten/lookup logic
│   ├── cache.py         # In-memory TTL cache
│   └── models.py        # Pydantic request/response models
├── db/
│   └── database.py      # PostgreSQL connection and queries
└── tests/
    └── test_shortener.py
```

## Prerequisites

- **Python 3.11+**
- **Docker Desktop (Running)** (for PostgreSQL)
- **pip**

## Setup

### 1. Clone and install dependencies

```powershell
cd c:\projects_faang\URL_shortner
pip install -r requirements.txt
```

### 2. Start PostgreSQL with Docker

If you already have a container named `postgres`:

```powershell
docker start postgres
```

If you need to create it for the first time:

```powershell
docker run -d `
  --name postgres `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=url_shortener `
  -p 5432:5432 `
  postgres
```

Verify it is running:

```powershell
docker ps --filter name=postgres
```

You should see the container **Up** with port `5432` mapped to the host.

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/url_shortener
```

| Variable       | Description                                      |
|----------------|--------------------------------------------------|
| `DATABASE_URL` | PostgreSQL connection string                     |

The default values match the Docker command above: user `postgres`, password `password`, database `url_shortener`, port `5432`.

The `urls` table is created automatically on first startup — no manual migration needed.

## Running the App

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

If port 8000 is unavailable on your machine, use another port (e.g. `8001`).

Once running:

- **API docs:** http://localhost:8000/docs
- **Health check:** shorten a URL via the docs UI or curl (see below)

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
       → Check in-memory cache
       → Check PostgreSQL (find_url — no hit count change)
       → Insert if new
       → Store in cache
       → Return short code + metadata
```

### Request flow — redirect

```
Client → GET /{short_code}
       → Check in-memory cache
       → PostgreSQL lookup (get_url — increments hit_count)
       → Store in cache
       → 302 redirect to long URL
```

### Caching

- **Library:** `cachetools.TTLCache`
- **Capacity:** 1000 entries
- **TTL:** 1 hour per entry
- Cache is in-process only — it resets when the server restarts

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

### `Connection refused` on port 5432

PostgreSQL is not running. Start it:

```powershell
docker start postgres
```

### `connection to server at "localhost" ... failed`

- Confirm the container is up: `docker ps`
- Confirm `.env` has the correct `DATABASE_URL`
- Wait a few seconds after `docker start` — Postgres needs a moment to initialize

### Port 8000 already in use / access denied

Use a different port:

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

Then use `http://localhost:8001` in API calls and browser.

### Short code not found after restart

Data persists in PostgreSQL across app restarts. If you removed the Docker container **without a volume**, the database data is lost. Recreate the container and shorten URLs again.

## Tech Stack

| Component   | Technology        |
|-------------|-------------------|
| Web framework | FastAPI         |
| Server        | Uvicorn         |
| Database      | PostgreSQL 18   |
| DB driver     | psycopg2        |
| Validation    | Pydantic        |
| Cache         | cachetools      |
| Config        | python-dotenv   |
