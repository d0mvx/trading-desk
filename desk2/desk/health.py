"""Health (replaces the STEP 10 health routine, which the user forbade): exit 1 when the desk is unhealthy.
Rules: any agent heartbeat older than 2 min, or > 10 PumpPortal ws reconnects in the last hour. Used by the supervisor."""
from __future__ import annotations
import sys, datetime as dt
from . import db, util, log

L = log.get("health")
AGENTS = ("scanner", "auditor", "analyst", "executor", "risk", "main")

def check() -> list[str]:
    bad = []
    now = util.now()
    hb = {r["agent"]: r["ts"] for r in db.q("SELECT agent, ts FROM heartbeats")}
    for a in AGENTS:
        ts = hb.get(a)
        if not ts:
            bad.append(f"{a}: no heartbeat"); continue
        age = (now - util.parse(ts)).total_seconds()
        if age > 120:
            bad.append(f"{a}: heartbeat {age:.0f}s old")
    hour = util.iso(now - dt.timedelta(hours=1))
    n = (db.one("SELECT COUNT(*) n FROM events WHERE kind='ws_connect' AND ts>?", (hour,)) or {}).get("n", 0)
    if n > 10:
        bad.append(f"ws reconnects {n}/h")
    return bad

if __name__ == "__main__":
    b = check()
    if b:
        L.warning("unhealthy: %s", "; ".join(b)); db.event("unhealthy", "; ".join(b)[:200])
        print("UNHEALTHY", "; ".join(b)); sys.exit(1)
    print("OK")
