#!/usr/bin/env python3
"""Mini-cron for the GitHub runner: runs gh/crontab.gh exactly like the box's cron (Europe/Berlin wall clock, one bash
process per due line at each minute boundary, overlap allowed - the lines carry their own flock/timeout), plus:
  * state commit to branch `state` every --commit-every minutes (background, never blocks the minute tick)
  * handover: --handover-cmd runs once, --handover-before minutes before the planned end (dispatches the next run, which
    waits in the workflow's concurrency group until this one is gone)
  * graceful end at --end-epoch / --max-minutes, moved EARLIER if it would fall into a protected trading window
    (15:45 NY stocks+trend, 20:05 NY crypto, 07:30 NY lists, 06:00 NY dial) so no scheduled order is lost in a handover
  * SIGTERM/SIGINT -> stop starting jobs, wait for running ones (--grace s), final state commit
Dry-run: --iterations N (minute ticks) --exclude REGEX (skip matching lines) [no --push]."""
import os, re, sys, time, signal, argparse, threading, subprocess, datetime as dt
from zoneinfo import ZoneInfo
BER, NY = ZoneInfo("Europe/Berlin"), ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
PROTECT = [  # (NY weekdays 1..7, HH:MM centre, minutes before, minutes after)
    ("12345", "15:45", 12, 8), ("1234567", "20:05", 12, 8), ("12345", "07:30", 10, 5), ("1234567", "06:00", 10, 5)]

LOGFILE = None
def log(m):
    line = f"{dt.datetime.now(BER):%Y-%m-%d %H:%M:%S %Z} [LOOP] {m}"; print(line, flush=True)
    if LOGFILE:
        try:
            with open(LOGFILE, "a") as f: f.write(line + "\n")
        except OSError: pass

def field_match(spec, v, lo, hi):
    for part in spec.split(","):
        step = 1
        if "/" in part: part, step = part.split("/"); step = int(step)
        if part == "*": a, b = lo, hi
        elif "-" in part: a, b = map(int, part.split("-"))
        else: a = b = int(part)
        if a <= v <= b and (v - a) % step == 0: return True
    return False

def cron_due(fields, t):
    mi, ho, dom, mon, dow = fields
    if not (field_match(mi, t.minute, 0, 59) and field_match(ho, t.hour, 0, 23) and field_match(mon, t.month, 1, 12)): return False
    d1 = field_match(dom, t.day, 1, 31); wd = t.isoweekday() % 7   # cron: 0=Sun
    d2 = field_match(dow, wd, 0, 7) or (wd == 0 and field_match(dow, 7, 0, 7))
    if dom != "*" and dow != "*": return d1 or d2
    return d1 and d2

def parse_crontab(path):
    env, jobs = {}, []
    for raw in open(path):
        l = raw.strip()
        if not l or l.startswith("#"): continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", l)
        if m: env[m.group(1)] = m.group(2); continue
        p = l.split(None, 5)
        jobs.append((p[:5], p[5]))
    return env, jobs

def protected_end(end):
    """Move `end` earlier until it is outside every protected window (checked in NY time)."""
    for _ in range(20):
        hit = None
        for days, hm, before, after in PROTECT:
            e = end.astimezone(NY); h, m = map(int, hm.split(":"))
            c = e.replace(hour=h, minute=m, second=0, microsecond=0)
            if str(c.isoweekday()) in days and c - dt.timedelta(minutes=before) <= e <= c + dt.timedelta(minutes=after):
                hit = c - dt.timedelta(minutes=before + 1)
        if not hit: return end
        end = hit.astimezone(BER)
    return end

class Loop:
    def __init__(s, a):
        s.a = a; s.env_add, s.jobs = parse_crontab(a.crontab)
        s.jobs = [(f, c) for f, c in s.jobs if not any(re.search(x, c) for x in a.exclude)]
        s.procs = []; s.stop = False; s.commit_lock = threading.Lock(); s.handed_over = False
        now = dt.datetime.now(BER)
        end = dt.datetime.fromtimestamp(a.end_epoch, BER) if a.end_epoch else now + dt.timedelta(minutes=a.max_minutes)
        s.end = protected_end(end)
        signal.signal(signal.SIGTERM, s.on_signal); signal.signal(signal.SIGINT, s.on_signal)
        log(f"{len(s.jobs)} cron line(s) active, {len(a.exclude)} exclude pattern(s); planned end {s.end:%Y-%m-%d %H:%M %Z}"
            + (f" (moved from {end:%H:%M} out of a protected window)" if s.end != end else ""))

    def on_signal(s, sig, _f):
        log(f"signal {sig} -> graceful stop"); s.stop = True

    def env(s):
        e = dict(os.environ); e.update({k: os.path.expandvars(v) for k, v in s.env_add.items() if k != "SHELL"})
        e.setdefault("TZ", "Europe/Berlin"); return e

    def spawn(s, cmd):
        p = subprocess.Popen(["/bin/bash", "-c", cmd], env=s.env(), cwd=os.path.expanduser("~"), start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        s.procs.append((p, cmd, time.time()))

    def reap(s):
        alive = []
        for p, cmd, t0 in s.procs:
            rc = p.poll()
            if rc is None: alive.append((p, cmd, t0))
            elif rc != 0: log(f"exit {rc} after {time.time() - t0:.0f}s: {cmd[:110]}")
        s.procs = alive

    def state_commit(s, final=False):
        if not s.a.state_worktree: return
        if not s.commit_lock.acquire(blocking=final): log("state commit still running, skip"); return
        try:
            py, ss, wt = sys.executable, os.path.join(HERE, "state_sync.py"), s.a.state_worktree
            subprocess.run([py, ss, "export", os.path.expanduser("~/.desk"), wt], timeout=240)
            msg = f"state {dt.datetime.now(BER):%Y-%m-%d %H:%M %Z}" + (" (final)" if final else "")
            subprocess.run([py, ss, "commit", wt, "-m", msg] + (["--push"] if s.a.push else []), timeout=300)
        except Exception as e: log(f"state commit error {type(e).__name__}: {e}")
        finally: s.commit_lock.release()

    def run(s):
        ticks = 0
        while not s.stop:
            now = time.time(); nxt = (int(now) // 60 + 1) * 60
            while time.time() < nxt and not s.stop: time.sleep(min(1.0, nxt - time.time()))
            if s.stop: break
            t = dt.datetime.fromtimestamp(nxt, BER)
            if t >= s.end: log("planned end reached"); break
            due = [c for f, c in s.jobs if cron_due(f, t)]
            for c in due: s.spawn(c)
            s.reap(); ticks += 1
            log(f"tick {t:%H:%M}: started {len(due)}, running {len(s.procs)}")
            if s.a.commit_every and t.minute % s.a.commit_every == s.a.commit_offset:
                threading.Thread(target=s.state_commit, daemon=True).start()
            if s.a.handover_cmd and not s.handed_over and t >= s.end - dt.timedelta(minutes=s.a.handover_before):
                s.handed_over = True; r = subprocess.run(["/bin/bash", "-c", s.a.handover_cmd], env=s.env())
                log(f"handover dispatched (rc={r.returncode})")
            if s.a.iterations and ticks >= s.a.iterations: log(f"{ticks} iteration(s) done"); break
        s.shutdown()

    def shutdown(s):
        t0 = time.time(); s.reap()
        if s.procs: log(f"waiting up to {s.a.grace}s for {len(s.procs)} running job(s)")
        while s.procs and time.time() - t0 < s.a.grace: time.sleep(1); s.reap()
        for p, cmd, _ in s.procs:
            log(f"SIGTERM (grace over): {cmd[:110]}")
            try: os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        time.sleep(3); s.reap()
        s.state_commit(final=True); log("loop finished")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--crontab", default=os.path.join(HERE, "crontab.gh")); ap.add_argument("--max-minutes", type=float, default=350)
    ap.add_argument("--end-epoch", type=float); ap.add_argument("--iterations", type=int, default=0)
    ap.add_argument("--exclude", action="append", default=[]); ap.add_argument("--state-worktree")
    ap.add_argument("--push", action="store_true"); ap.add_argument("--commit-every", type=int, default=5); ap.add_argument("--commit-offset", type=int, default=3)
    ap.add_argument("--handover-cmd"); ap.add_argument("--handover-before", type=float, default=12); ap.add_argument("--grace", type=int, default=150)
    ap.add_argument("--logfile", default=os.path.expanduser("~/.desk/logs/gh_loop.log"))
    _a = ap.parse_args(); LOGFILE = _a.logfile; Loop(_a).run()
