import os
import random
from locust import FastHttpUser, task, between, constant_throughput
from locust.contrib.fasthttp import LocustUserAgent

# Never follow redirects: we're measuring our 302, not example.com.
# (Locust's allow_redirects=False is a no-op with newer geventhttpclient
# because of an attribute-name mismatch, so turn following off directly.)
LocustUserAgent.redirect_response_codes = frozenset()
LocustUserAgent.redirect_resonse_codes = frozenset()

# FIXED_RATE_PER_USER=2 makes each simulated user send exactly 2 requests/s,
# so total RPS = users x 2 and stays flat for the whole run.
_fixed = os.getenv("FIXED_RATE_PER_USER")


class URLShortenerUser(FastHttpUser):
    # FastHttpUser: much lighter on CPU than HttpUser, so one Locust process
    # can generate more load.
    wait_time = constant_throughput(float(_fixed)) if _fixed else between(0.1, 0.5)
    known_codes = []

    def on_start(self):
        # Seed a few short codes at the start of each simulated user's
        # session so redirect load has real codes to hit, not 404s.
        for _ in range(3):
            self._shorten()

    def _shorten(self):
        long_url = f"https://example.com/page/{random.randint(1, 10_000_000)}"
        with self.client.post(
            "/shorten",
            json={"long_url": long_url},
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                code = resp.json()["short_code"]
                URLShortenerUser.known_codes.append(code)
            else:
                # 429 counts as a failure too: the stack must run with
                # RATE_LIMIT_ENABLED=false, or the numbers mean nothing.
                resp.failure(f"unexpected status {resp.status_code}")

    @task(1)
    def shorten(self):
        self._shorten()

    @task(10)
    def redirect(self):
        if not URLShortenerUser.known_codes:
            return
        code = random.choice(URLShortenerUser.known_codes)
        with self.client.get(
            f"/{code}",
            name="/{short_code}",
            allow_redirects=False,
            catch_response=True,
        ) as resp:
            if resp.status_code == 302:
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(3)
    def inspect(self):
        if not URLShortenerUser.known_codes:
            return
        code = random.choice(URLShortenerUser.known_codes)
        self.client.get(f"/inspect/{code}", name="/inspect/{short_code}")
