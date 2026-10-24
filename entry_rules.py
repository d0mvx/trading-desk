"""USER ORDER 2026-10-24 13:34 (+13:37 reference dashboard): the SIX ENTRY RULES of the meme sleeve (main + new pairs), PAPER ONLY.
These are the deciding entry criteria on top of the older filters (scan rules, judge gates, rule 7-10, cooldowns, RugCheck).
  1 liquidity   pool liquidity in USD >= MIN_POOL_LIQ_USD (per venue). NOT market cap. Pump.fun bonding curves have no AMM pool:
                their 'liquidity' is derived (real SOL in the curve x SOL price) and tops out at ~$12-17k, so the $40K floor
                excludes curve coins (new-pairs sleeve). One config line per venue (MIN_POOL_LIQ_USD) changes that.
  2 volume      1h volume >= MIN_VOL_H1_USD (no dead volume). Main: DexScreener/GT 1h volume of the candidate; new pairs:
                1h volume from the pump.fun 1m candles (rugpattern, 'order rule 2').
  3 not mid-rocket   rugpattern 'order rule 3': >= R3_GREEN_RUN consecutive green 1m candles in the last R3_WIN candles AND
                price >= +R3_MIN_RUN10 vs 10 min ago (a vertical run). Stricter than rule 9 (+100% / 15 min), which stays.
  4 sells < 2x buys   by count in m5 and m15 (DexScreener fallback puts m5 in the 'm15' key). Hard floor, not learner-tunable.
  5 2 losses = out    after STREAK_LOSSES consecutive losing FINAL closes (total realized PnL of the position < 0; a TP partial
                is not a close) of main/new pairs: no new buys for PAUSE_MIN minutes, then the counter restarts. State in
                loss_streak.json (state branch). Shadow book not affected.
  6 not off a post    an X post / X news topic is research / a tag only, never a trigger: newpairs narrative score ignores X
                points (X_SCORE_ENABLED=False) and a buy must pass every on-chain gate.
All constants are USER ORDER, tighten-only; the learner (learner.py) cannot touch them (module not in PARAMS, forbidden prefix)."""
import os, json, time, fcntl, datetime as dt

DESK = os.path.expanduser("~/.desk")
MIN_POOL_LIQ_USD = {"pumpswap": 40_000.0, "bonding_curve": 40_000.0}
MIN_VOL_H1_USD = 50_000.0
MAX_SELLS_PER_BUY = 2.0
STREAK_LOSSES = 2
PAUSE_MIN = 60
X_SCORE_ENABLED = False
STREAK_FILE = f"{DESK}/loss_streak.json"; STREAK_LOCK = f"{DESK}/.loss_streak.lock"
DROP_LOG = f"{DESK}/logs/entry_rules_drops.jsonl"
PFX = "order rule"

def usd(x): return f"${x/1e3:.1f}k" if x >= 1e3 else f"${x:.0f}"

# ---------------- rule 1 / 2 / 4: pure checks ----------------
def liq_gate(venue, liq):
    lim = MIN_POOL_LIQ_USD.get(venue, max(MIN_POOL_LIQ_USD.values()))
    if liq is None: return f"{PFX} 1 · pool liquidity n/a (min {usd(lim)})"
    if liq < lim: return f"{PFX} 1 · pool liquidity {usd(liq)} < {usd(lim)}" + (" (curve, derived)" if venue == "bonding_curve" else "")
    return None

def vol_gate(vol_h1):
    if vol_h1 is None: return None
    if vol_h1 < MIN_VOL_H1_USD: return f"{PFX} 2 · dead volume: 1h volume {usd(vol_h1)} < {usd(MIN_VOL_H1_USD)}"
    return None

def bs_gate(windows):
    """windows: {'m5': {'buys','sells'}, 'm15': {...}}; sells >= MAX_SELLS_PER_BUY x buys (and sells > 0) in any window -> fail."""
    for w in ("m5", "m15"):
        t = (windows or {}).get(w)
        if not t: continue
        b, s = t.get("buys") or 0, t.get("sells") or 0
        if s > 0 and s >= MAX_SELLS_PER_BUY * b:
            return f"{PFX} 4 · sells {s} vs buys {b} in {w} ({s / b:.1f}:1)" if b else f"{PFX} 4 · sells {s} vs buys 0 in {w}"
    return None

def main_gates(c):
    """Main-sleeve candidate (scan dict). Returns (fails, notes). Rules 1, 2, 4 (rule 3 lives in rugpattern, rule 5 in paused())."""
    fails, notes = [], []
    t = liq_gate(c.get("venue"), c.get("liquidity_usd"))
    if t: fails.append(t)
    v = c.get("vol_h1")
    if v is None: notes.append("order rule 2 n/a (no 1h volume in scan data) -> allowed")
    else:
        t = vol_gate(v)
        if t: fails.append(t)
    t = bs_gate({"m5": c.get("tx_m5"), "m15": c.get("tx_m15")})
    if t: fails.append(t)
    return fails, notes

# ---------------- rule 5: loss streak ----------------
def _now(): return dt.datetime.now(dt.timezone.utc)
def _load():
    try: return json.load(open(STREAK_FILE))
    except (FileNotFoundError, ValueError): return {"streak": 0, "paused_until": None, "history": []}
def _save(s):
    tmp = STREAK_FILE + ".tmp"; json.dump(s, open(tmp, "w"), indent=1); os.replace(tmp, STREAK_FILE)

def paused(at=None):
    """Returns (until_iso, text) while the loss-streak pause is on, else None. Clears an expired pause (counter restarts)."""
    at = at or _now(); s = _load(); pu = s.get("paused_until")
    if not pu: return None
    if dt.datetime.fromisoformat(pu) > at:
        return pu, f"loss-streak pause until {dt.datetime.fromisoformat(pu).astimezone().strftime('%H:%M')} ({STREAK_LOSSES} losing closes in a row)"
    with open(STREAK_LOCK, "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX); s = _load()
        if s.get("paused_until") and dt.datetime.fromisoformat(s["paused_until"]) <= at:
            s.update(streak=0, paused_until=None, resumed_at=at.isoformat(timespec="seconds")); _save(s)
    return None

def record_close(total_pnl, name, at=None):
    """Called on every FINAL close of a main / new-pairs position with its TOTAL realized PnL. Returns the state dict."""
    at = at or _now()
    with open(STREAK_LOCK, "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX); s = _load(); pu = s.get("paused_until")
        h = s.setdefault("history", []); ent = {"t": at.isoformat(timespec="seconds"), "name": name, "pnl": round(total_pnl, 4)}
        if pu and dt.datetime.fromisoformat(pu) > at:
            ent["note"] = "closed during pause (not counted)"; h.append(ent)
        else:
            if pu: s.update(streak=0, paused_until=None)
            if total_pnl < 0:
                s["streak"] = int(s.get("streak") or 0) + 1
                if s["streak"] >= STREAK_LOSSES:
                    s["paused_until"] = (at + dt.timedelta(minutes=PAUSE_MIN)).isoformat(timespec="seconds"); ent["note"] = f"pause {PAUSE_MIN} min"
            elif total_pnl > 0: s["streak"] = 0
            h.append(ent)
        s["history"] = h[-20:]; s["last_update"] = at.isoformat(timespec="seconds"); _save(s)
    return s

def on_final_close(o, closed_row, p, reason):
    """meme.close_position hook (frac == 1.0). Total PnL = every closed row of this position (TP partials + final)."""
    if (reason or "").startswith("reset"): return None
    tot = sum(x.get("pnl") or 0 for x in p["closed"] if x.get("pool") == o.get("pool") and x.get("entry_time") == o.get("entry_time"))
    return record_close(tot, o.get("name") or "?")

# ---------------- drop log (dashboard feed) ----------------
def log_event(kind, rule, name, mint, sleeve, text, venue=None):
    """kind 'drop' | 'pass'. De-duplicated per (mint, rule, kind) for 60 min. Never raises."""
    try:
        now = time.time(); key = f"{mint}|{rule}|{kind}"
        try: tail = open(DROP_LOG).readlines()[-300:]
        except FileNotFoundError: tail = []
        for l in tail:
            try: d = json.loads(l)
            except ValueError: continue
            if d.get("key") == key and now - d.get("ts", 0) < 3600: return
        os.makedirs(os.path.dirname(DROP_LOG), exist_ok=True)
        try:
            if os.path.getsize(DROP_LOG) > 400_000:   # keep the state-branch file small: newest 2000 lines
                keep = open(DROP_LOG).readlines()[-2000:]; open(DROP_LOG, "w").writelines(keep)
        except OSError: pass
        with open(DROP_LOG, "a") as f:
            f.write(json.dumps({"ts": round(now), "t": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "key": key, "kind": kind, "rule": rule,
                                "name": (name or "?")[:30], "mint": mint, "sleeve": sleeve, "venue": venue, "text": text[:160]}) + "\n")
    except Exception: pass

def log_fails(fails, name, mint, sleeve, venue=None):
    """Writes one 'drop' per order-rule fail text; returns True if any."""
    hit = False
    for f in fails or []:
        if f.startswith(PFX):
            hit = True; log_event("drop", int(f[len(PFX) + 1]), name, mint, sleeve, f, venue)
    return hit

# ---------------- dashboard summary ----------------
RULE_LABEL = {1: "liq >= $40K", 2: "vol 1h >= $50K", 3: "not mid-rocket", 4: "sells < 2x buys", 5: "2 losses = out", 6: "not off a post"}

def dash_summary(hours=24, feed=14):
    """{'evaluated','dropped','by_rule':{n:distinct mints},'feed':[...],'pause':..., 'streak':n}. Distinct mints in the last `hours` h (the log is de-duplicated per mint+rule per 60 min)."""
    cut = time.time() - hours * 3600; ev, dr = set(), set(); by = {n: set() for n in range(1, 5)}; rows = []
    try: lines = open(DROP_LOG).readlines()
    except FileNotFoundError: lines = []
    for l in lines:
        try: d = json.loads(l)
        except ValueError: continue
        if d.get("ts", 0) < cut: continue
        ev.add(d.get("mint"))
        if d.get("kind") == "drop": dr.add(d.get("mint")); by.setdefault(d.get("rule"), set()).add(d.get("mint"))
        rows.append(d)
    s = _load()
    return {"evaluated": len(ev), "dropped": len(dr), "by_rule": {n: len(v) for n, v in by.items()}, "feed": rows[-feed:][::-1],
            "pause": paused(), "streak": int(s.get("streak") or 0), "last_closes": (s.get("history") or [])[-3:]}
