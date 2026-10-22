#!/usr/bin/env python3
"""Cadence gate for the meme pipeline (cron calls this EVERY MINUTE under flock -n). Berlin wall-clock time:
  now .. 2026-10-28 01:40 (exclusive)  every 1 min   (2026-10-20 19:5x user-approved upgrade 2: the planned switch to hourly
                                                      on 2026-10-21 01:30 is cancelled; same end as before; same GT budget/run)
  after                                stop (logs 'schedule ended' once)
DST fall-back 2026-10-25 (02:xx happens twice): the hourly phase skips a run if the previous one was < 30 real min ago.
Usage: meme_gate.py [--check] [--next]"""
import os, sys, time, datetime as dt, subprocess
from zoneinfo import ZoneInfo
BER = ZoneInfo("Europe/Berlin"); DESK = os.path.expanduser("~/.desk")
P = [(dt.datetime(2026, 10, 28, 1, 40, tzinfo=BER), 1)]   # was: 1 min until 2026-10-21 01:30, then 60 min until 2026-10-28 01:40
ANCHOR = dt.datetime(2026, 10, 20, 1, 40, tzinfo=BER)   # hourly slots on :40 (wall clock)
STAMP = f"{DESK}/.meme_last_pipeline"

def cadence(t):
    for end, step in P:
        if t < end: return step
    return None

def due(t):
    t = t.replace(second=0, microsecond=0); step = cadence(t)
    if step is None: return False
    return int((t - ANCHOR).total_seconds() // 60) % step == 0

def next_run(t):
    t = t.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    for _ in range(60 * 24 * 9):
        if cadence(t) is None: return None
        if due(t): return t
        t += dt.timedelta(minutes=1)

if __name__ == "__main__":
    t = dt.datetime.now(BER)
    if "--next" in sys.argv:
        n = next_run(t); print(f"cadence={cadence(t)}min next={n.isoformat() if n else 'ended'}"); sys.exit()
    if cadence(t) is None:
        flag = f"{DESK}/.meme_schedule_ended"
        if not os.path.exists(flag):
            open(flag, "w").write(t.isoformat())
            with open(f"{DESK}/logs/meme.log", "a") as f: f.write(f"{t:%Y-%m-%d %H:%M:%S %Z} [CHIEF] schedule ended — meme pipeline disabled\n")
        sys.exit()
    if due(t):
        if cadence(t) >= 60:
            try:
                if time.time() - float(open(STAMP).read()) < 1800: sys.exit()   # repeated wall hour (DST)
            except (FileNotFoundError, ValueError): pass
        open(STAMP, "w").write(f"{time.time():.0f}")
        sys.exit(subprocess.call([f"{DESK}/run_meme.sh", "pipeline"]))
