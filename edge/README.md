# Edge redirect cache (Cloudflare Workers + KV)

A Cloudflare Worker that sits in front of the FastAPI backend and answers
redirects from Workers KV at the edge, so a popular link never has to reach
the origin.

```
Client → Cloudflare edge (Worker)
           ├─ GET /{code}, in KV  → 302 from the edge            (x-edge-cache: HIT)
           ├─ GET /{code}, not in KV → origin → store in KV → 302 (x-edge-cache: MISS)
           └─ anything else (POST /shorten, /inspect, /docs) → origin (x-edge-cache: BYPASS)
```

## Why KV

KV is replicated globally, so a link cached once is readable from every
Cloudflare location. The Cache API is per-location and would need a miss in
each region. `cacheTtl: 300` on the read also keeps hot keys in the local
edge cache, so repeat hits skip the KV lookup.

## Trade-offs (it's a prototype)

- **Clicks served from the edge aren't counted.** Only MISSes reach the
  origin, so `hit_count` undercounts popular links. A production version
  would send click events to a queue (Cloudflare Queues or Analytics Engine)
  and batch them into Postgres, the same idea as the Redis buffer.
- **Deleted or changed links stay cached** for up to `KV_TTL_SECONDS`
  (1 hour), and KV writes take up to about 60 s to reach every location.

## Deploy

You need Node 18+ and a free Cloudflare account.

```powershell
cd edge
npm install
npx wrangler login                       # opens the browser, sign in
npx wrangler kv namespace create LINKS   # copy the id it prints into wrangler.toml
```

The Worker needs a public URL for the backend. With the Docker stack running,
open a quick tunnel in another terminal (install `cloudflared` first:
`winget install Cloudflare.cloudflared`):

```powershell
cloudflared tunnel --url http://localhost:8001
```

Put the `https://….trycloudflare.com` URL it prints into `ORIGIN_URL` in
`wrangler.toml`, then:

```powershell
npx wrangler deploy     # prints https://url-shortener-edge.<you>.workers.dev
```

## Measure

```powershell
pip install httpx
python ../bench/latency.py --origin https://<tunnel>.trycloudflare.com --worker https://url-shortener-edge.<you>.workers.dev
```

It times 100 redirects against each and prints the medians.

## Local dev

```powershell
npx wrangler dev --var ORIGIN_URL:http://localhost:8001
```

Runs the Worker on `localhost:8787` with a local KV store.
