"""GeckoTerminal client with a cross-process rate limit (<= 9 calls / rolling 60s; public limit is 10/min).
Optional deadline (epoch s): a call that would have to wait/retry past it raises instead (keeps 1-min scans < 60s)."""
import os, time, json, fcntl, requests
GT = "https://api.geckoterminal.com/api/v2"
HDR = {"Accept": "application/json;version=20230302", "User-Agent": "desk-meme/1.0"}
STATE = os.path.expanduser("~/.desk/.gt_calls")
LIMIT, WINDOW = 9, 60.0

class Budget(RuntimeError): pass

def _acquire(deadline=None):
    while True:
        with open(STATE, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try: calls = [float(x) for x in f.read().split()]
            except ValueError: calls = []
            now = time.time(); calls = [c for c in calls if now - c < WINDOW]
            if len(calls) < LIMIT:
                calls.append(now); f.seek(0); f.truncate(); f.write(" ".join(f"{c:.3f}" for c in calls)); return
            wait = WINDOW - (now - calls[0]) + 0.2
        wait = max(0.5, wait)
        if deadline and time.time() + wait > deadline: raise Budget(f"GT budget: would wait {wait:.0f}s past deadline")
        time.sleep(wait)

def get(path, params=None, deadline=None):
    for attempt in range(3):
        _acquire(deadline)
        r = requests.get(GT + path, params=params, headers=HDR, timeout=12)
        if r.status_code == 429:
            if deadline and time.time() + 20 > deadline: raise RuntimeError(f"GeckoTerminal 429 on {path} (no retry: deadline)")
            time.sleep(20); continue
        r.raise_for_status(); return r.json()
    raise RuntimeError(f"GeckoTerminal 429 on {path}")
