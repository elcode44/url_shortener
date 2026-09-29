"""
Runs the resume load tests against the Docker stack and prints the numbers.

    pip install locust
    python bench/run_load_test.py

It runs two back-to-back Locust runs at a fixed request rate:
  1. clean run  - all 3 replicas up the whole time
  2. kill run   - same load, `docker stop` on app2 partway through

Options: --users 400 --rate 2 (=> ~800 RPS), --minutes 4, --kill-at 120.
Results (CSV + summary) land in bench/results/.
"""
import argparse
import csv
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bench" / "results"


def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, **kw)


def wait_for_stack(url="http://localhost:8001/docs", timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(url, timeout=3)
            return
        except Exception:
            time.sleep(2)
    sys.exit("Stack didn't come up on :8001 - check `docker compose logs`.")


def run_locust(name, users, rate, seconds, kill_at=None):
    env = {**os.environ, "FIXED_RATE_PER_USER": str(rate)}
    prefix = OUT / name
    cmd = [
        sys.executable, "-m", "locust", "-f", "locustfile.py", "--headless",
        "--host", "http://localhost:8001",
        "-u", str(users), "-r", str(max(users // 10, 1)),
        "-t", f"{seconds}s", "--csv", str(prefix), "--csv-full-history",
        "--only-summary",
    ]
    killed = {}

    def killer():
        time.sleep(kill_at)
        cid = sh(["docker", "compose", "ps", "-q", "app2"]).stdout.strip()
        sh(["docker", "stop", cid])
        killed["at"] = time.time()
        print(f"  -> docker stop app2 at t={kill_at}s")

    if kill_at:
        threading.Thread(target=killer, daemon=True).start()
    print(f"[{name}] {users} users x {rate} req/s for {seconds}s ...")
    t_start = time.time()
    subprocess.run(cmd, cwd=ROOT, env=env)
    return prefix, t_start, killed.get("at")


def summarize(prefix, warmup, t_start=None, kill_time=None):
    rows = list(csv.DictReader(open(f"{prefix}_stats.csv")))
    agg = next(r for r in rows if r["Name"] == "Aggregated")
    reqs, fails = int(agg["Request Count"]), int(agg["Failure Count"])
    s = {
        "requests": reqs,
        "failures": fails,
        "failure_pct": 100 * fails / max(reqs, 1),
        "p50_ms": agg["50%"],
        "p99_ms": agg["99%"],
    }
    # Steady-state RPS: average of per-second samples after ramp-up.
    hist = [r for r in csv.DictReader(open(f"{prefix}_stats_history.csv")) if r["Name"] == "Aggregated"]
    t0 = int(hist[0]["Timestamp"])
    steady = [float(r["Requests/s"]) for r in hist if int(r["Timestamp"]) - t0 >= warmup]
    s["steady_rps"] = sum(steady) / max(len(steady), 1)
    if kill_time:
        before = [r for r in hist if int(r["Timestamp"]) < kill_time]
        after = [r for r in hist if int(r["Timestamp"]) >= kill_time]
        fb = int(before[-1]["Total Failure Count"]) if before else 0
        fa = int(after[-1]["Total Failure Count"]) if after else fb
        s["failures_after_kill"] = fa - fb
        rps_after = [float(r["Requests/s"]) for r in after[5:]]
        s["rps_after_kill"] = sum(rps_after) / max(len(rps_after), 1)
    return s


def show(title, s):
    print(f"\n=== {title} ===")
    print(f"steady RPS:   {s['steady_rps']:.0f}")
    print(f"requests:     {s['requests']}   failures: {s['failures']} ({s['failure_pct']:.3f}%)")
    print(f"p50: {s['p50_ms']} ms   p99: {s['p99_ms']} ms")
    if "failures_after_kill" in s:
        print(f"failures after kill: {s['failures_after_kill']}   RPS on 2 replicas: {s['rps_after_kill']:.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=400)
    ap.add_argument("--rate", type=float, default=2.0)
    ap.add_argument("--minutes", type=float, default=4)
    ap.add_argument("--kill-at", type=int, default=120)
    ap.add_argument("--skip-clean", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    seconds = int(a.minutes * 60)
    warmup = 30

    print("Starting stack (rate limiting off for load testing)...")
    env = {**os.environ, "RATE_LIMIT_ENABLED": "false"}
    r = subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT, env=env)
    if r.returncode:
        sys.exit("docker compose up failed")
    wait_for_stack()

    ncpu = sh(["docker", "info", "--format", "{{.NCPU}} CPUs, {{.MemTotal}} bytes"]).stdout.strip()
    lines = [f"machine: {platform.platform()} | {platform.processor()} | docker: {ncpu}"]

    if not a.skip_clean:
        prefix, _, _ = run_locust("clean", a.users, a.rate, seconds)
        s = summarize(prefix, warmup)
        show("CLEAN RUN", s)
        lines.append(f"clean: {s}")
        time.sleep(10)

    prefix, t_start, kill_time = run_locust("kill", a.users, a.rate, seconds, kill_at=a.kill_at)
    s = summarize(prefix, warmup, t_start, kill_time)
    show("REPLICA KILL RUN", s)
    lines.append(f"kill: {s}")

    sh(["docker", "compose", "start", "app2"])
    (OUT / "summary.txt").write_text("\n".join(lines) + "\n")
    print(f"\n{lines[0]}\nSaved to bench/results/. Paste everything above back to Claude.")


if __name__ == "__main__":
    main()
