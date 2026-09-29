"""
Median redirect latency: FastAPI origin vs the Cloudflare Worker (KV cache hit).

    python bench/latency.py --origin https://xxxx.trycloudflare.com \
        --worker https://url-shortener-edge.<you>.workers.dev

Creates one short link, warms the Worker so its KV holds it, then times
100 redirects against each and prints the medians. Both go over HTTPS with
keep-alive, so the comparison is "edge answers" vs "edge -> tunnel -> your app".
"""
import argparse
import statistics
import time

import httpx


def time_redirects(client, url, n):
    samples = []
    cache_states = set()
    for _ in range(n):
        t0 = time.perf_counter()
        r = client.get(url)
        samples.append((time.perf_counter() - t0) * 1000)
        if r.status_code != 302:
            raise SystemExit(f"{url} returned {r.status_code}, expected 302")
        cache_states.add(r.headers.get("x-edge-cache", "-"))
    return samples, cache_states


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", required=True, help="public URL of the FastAPI backend (tunnel)")
    ap.add_argument("--worker", required=True, help="deployed Worker URL")
    ap.add_argument("-n", type=int, default=100)
    a = ap.parse_args()
    origin, worker = a.origin.rstrip("/"), a.worker.rstrip("/")

    with httpx.Client(timeout=20, follow_redirects=False, http2=False) as c:
        r = c.post(f"{origin}/shorten", json={"long_url": f"https://example.com/latency/{time.time_ns()}"})
        r.raise_for_status()
        code = r.json()["short_code"]

        # Warm up connections and put the link in KV (first Worker hit is a MISS).
        for _ in range(5):
            c.get(f"{origin}/{code}")
            c.get(f"{worker}/{code}")
        time.sleep(2)

        o, _ = time_redirects(c, f"{origin}/{code}", a.n)
        w, states = time_redirects(c, f"{worker}/{code}", a.n)

    print(f"short code: {code}   requests each: {a.n}")
    print(f"origin (FastAPI via tunnel)  median {statistics.median(o):6.1f} ms   p90 {statistics.quantiles(o, n=10)[-1]:6.1f} ms")
    print(f"worker (KV)                  median {statistics.median(w):6.1f} ms   p90 {statistics.quantiles(w, n=10)[-1]:6.1f} ms")
    print(f"worker cache states seen: {sorted(states)}  (want only HIT)")


if __name__ == "__main__":
    main()
