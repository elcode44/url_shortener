import random
from locust import HttpUser, task, between


class URLShortenerUser(HttpUser):
    wait_time = between(0.1, 0.5)
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
            elif resp.status_code == 429:
                resp.success()  # rate limiting working as intended, not a failure
            else:
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
            allow_redirects=False,
            catch_response=True,
        ) as resp:
            if resp.status_code in (302, 429):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(3)
    def inspect(self):
        if not URLShortenerUser.known_codes:
            return
        code = random.choice(URLShortenerUser.known_codes)
        self.client.get(f"/inspect/{code}", name="/inspect/{short_code}")
