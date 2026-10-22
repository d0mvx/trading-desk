#!/usr/bin/env python3
"""Rug-pattern skip rules (USER ORDER Dominic 2026-10-21 19:34 + 19:37; tightening only). Used by meme.py Judge and newpairs.py.

rule 7 · first candle (launch pump):  pump.fun coin's FIRST 1-minute candle from launch (swap-api.pump.fun candles, USD).
    skip if  first-candle high/open - 1 >= R7_MIN_PCT  AND  (high1 - open1) / (ATH so far - open1) >= R7_MIN_SHARE
    -> the whole move was one launch candle (bundled/sniped launch, often curve bought out in minute 1), no organic growth after.
    Calibrated 2026-10-21 on 46 real + 180 shadow closed main-sleeve trades (in-sample!): blocked real avg -14.3%/trade vs kept -2.6%.
    newpairs (2-15 min old curve coins, the first candle is naturally most of the rise): skip if first candle >= NP_R7_MIN_PCT.
rule 8 · bot-wash pattern: last W8 (120) 1-second candles (pump.fun 1s candles) of the pool, either
    micro-wash : alternation >= 0.65 AND body-size CV <= 0.70 AND p5-p95 close band <= 3% AND efficiency (|net|/sum|bodies|) <= 0.15
    sawtooth   : trades every second (density >= 0.95) AND >= 15 regular drops (red > 1.5%, CV of drop sizes <= 0.30)
                 AND lag-1 return autocorrelation <= -0.15 AND efficiency <= 0.10   (KIMCHI/The Yellow Bull pattern)
Data: keyless pump.fun swap-api (not the GeckoTerminal budget), cached in scan/rugpattern_cache.json
(launch candle permanent, 1m 60 s, 1s 20 s), <= MAX_CALLS_PER_RUN network calls per process run.
rule 9 · anti-chase (USER ORDER Dominic 2026-10-22 21:44, tightening only): from the same pump.fun 1m candles, price now vs
    close 15 min ago >= +R9_MAX_RUN15 -> skip (vertical run-up = buying the top of the hype).  Main sleeve also:
    young pool (< R9_YOUNG_N60 active 1m candles in the last 60 min) AND price vs 30 min ago >= +R9_YOUNG_MAX_RUN30 -> skip.
rule 10 · dump candle: any 1m candle in the last 10 min with open->close <= -R10_MAX_RED1M -> skip (rug/dev-dump visible on chart).
    Calibrated 2026-10-22 on epoch-2 trades (67 real main + 203 shadow main + 264 shadow control, GT 1m candles, in-sample!),
    see CHANGELOG_research.md 2026-10-22 "rule 9/10".
Missing data: rule 7 -> newpairs SKIP ('no first-candle data'), main sleeve ALLOW + log; rule 8/9/10 -> ALLOW + log (both)."""
import os, json, time, fcntl, statistics as st, requests

DESK = os.path.expanduser("~/.desk")
CACHE = f"{DESK}/scan/rugpattern_cache.json"; LOCK = f"{DESK}/scan/.rugpattern.lock"
URL = "https://swap-api.pump.fun/v2/coins/{}/candles"
UA = {"User-Agent": "Mozilla/5.0 (desk-meme/1.0)", "Accept": "application/json"}
# ---- rule 7 ----
R7_MIN_PCT = 10.0          # first 1m candle open->high >= +1000%
R7_MIN_SHARE = 0.50        # ... and >= 50% of the rise from launch open to the ATH so far
NP_R7_MIN_PCT = 1.50       # newpairs: first 1m candle open->high >= +150%  (see CHANGELOG 2026-10-21 for calibration)
# ---- rule 9 / 10 (USER ORDER 2026-10-22 21:44) ----
R9_MAX_RUN15 = 1.0         # price now vs close 15 min ago >= +100% -> skip (chase)
R9_YOUNG_N60 = 25          # "young": fewer than 25 active 1m candles in the last 60 min ...
R9_YOUNG_MAX_RUN30 = 1.0   # ... AND price vs 30 min ago >= +100% -> skip (main sleeve only)
R10_MAX_RED1M = 0.20       # a 1m candle in the last R10_WIN_S with open->close <= -20% -> skip (dump candle)
R10_WIN_S = 600
NP_R9_MAX_RUN15 = 1.0      # newpairs (2-15 min old curve coins): same run-up / dump-candle limits, no "young" rule (all are young)
NP_R10_MAX_RED1M = 0.20
LAUNCH_MATCH = 0.02        # first 1m candle open must equal the first 1h candle open (= launch price) within 2%
try:   # 2026-10-22 SELF-LEARN (USER ORDER): learner_overrides.json may adjust allowlisted thresholds above (bounded, gated, kill switch)
    import sys as _sys; _sys.path.insert(0, DESK if "DESK" in globals() else os.path.expanduser("~/.desk"))
    import learner as _learner; _learner.apply("rugpattern", globals())
except Exception: pass
# ---- rule 8 ----
W8 = 120; W8_MAX_AGE_S = 3600; W8_LAST_MAX_S = 300   # window = last 120 1s candles within 1 h; last candle <= 5 min old
MW_ALT, MW_CVB, MW_BAND, MW_ER = 0.65, 0.70, 0.03, 0.15
ST_DENS, ST_NRED, ST_RED_MIN, ST_CVRED, ST_AC1, ST_ER = 0.95, 15, 0.015, 0.30, -0.15, 0.10
# ---- plumbing ----
TTL_1M, TTL_1S, KEEP_S = 60, 20, 7 * 86400
MAX_CALLS_PER_RUN = 20; TIMEOUT = 6
_calls = [0]
_M1 = {}   # per-process memo mint -> (fetched_at, 1m candles): rule 9/10 reuse rule 7's fetch (no extra call)

class NoData(RuntimeError): pass
class Budget(NoData): pass   # per-run call budget used up -> caller must NOT treat as "allowed"

def _load():
    try: return json.load(open(CACHE))
    except (FileNotFoundError, ValueError): return {}

def _save(upd):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(LOCK, "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        c = _load(); now = time.time()
        for m, v in upd.items(): c.setdefault(m, {}).update(v)
        c = {m: v for m, v in c.items() if now - v.get("seen", now) < KEEP_S}
        tmp = CACHE + ".tmp"; json.dump(c, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, CACHE)

def candles(mint, interval, limit=1000, fetch=None):
    """[(t_s, o, h, l, c, v)] ascending. Raises NoData."""
    if fetch: raw = fetch(mint, interval, limit)
    else:
        if _calls[0] >= MAX_CALLS_PER_RUN: raise Budget("rugpattern call budget for this run used")
        _calls[0] += 1
        try:
            r = requests.get(URL.format(mint), params={"interval": interval, "limit": limit, "currency": "USD", "createdTs": 1}, headers=UA, timeout=TIMEOUT)
            if r.status_code != 200: raise NoData(f"pump.fun candles HTTP {r.status_code}")
            raw = r.json()
        except NoData: raise
        except Exception as e: raise NoData(f"pump.fun candles {type(e).__name__}")
    if not isinstance(raw, list): raise NoData("pump.fun candles: bad payload")
    out = []
    for x in raw:
        try: out.append((x["timestamp"] / 1000, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x.get("volume") or 0)))
        except (TypeError, ValueError, KeyError): pass
    out.sort()
    if not out: raise NoData(f"no {interval} candles")
    return out

# ---------------- rule 7 ----------------
def first_candle_metrics(m1, launch_open):
    """m1: 1m candles (ascending). Returns dict or None if the launch minute is not in the 1m history."""
    if not m1 or not launch_open or abs(m1[0][1] / launch_open - 1) > LAUNCH_MATCH: return None
    t0, o, h, l, c, v = m1[0]
    ath = max(x[2] for x in m1)
    return {"t0": t0, "o": o, "h1": h, "f1_pct": h / o - 1, "share": (h - o) / (ath - o) if ath > o else 1.0, "ath": ath,
            "vol_share": v / (sum(x[5] for x in m1) or 1)}

def rule7(mint, newpairs=False, fetch=None, cache=None, upd=None):
    """Returns (fail_text or None, info). Raises NoData when the launch candle cannot be determined."""
    now = time.time(); e = (cache or {}).get(mint, {})
    fc = e.get("fc"); m1_at = e.get("m1_at", 0)
    if fc and now - m1_at < TTL_1M: met = fc
    else:
        launch_open = e.get("launch_open")
        if not launch_open:
            launch_open = candles(mint, "1h", fetch=fetch)[0][1]
        m1 = candles(mint, "1m", fetch=fetch)
        if fetch is None: _M1[mint] = (time.time(), m1)
        met = first_candle_metrics(m1, launch_open)
        if met is None:
            if upd is not None: upd[mint] = {"launch_open": launch_open, "seen": now}
            raise NoData("launch minute not in 1m history (coin older than ~1000 active minutes)")
        if fc:   # launch candle is immutable; only the ATH (share) moves
            met = dict(fc, ath=max(fc["ath"], met["ath"]), share=(fc["h1"] - fc["o"]) / (max(fc["ath"], met["ath"]) - fc["o"]) if max(fc["ath"], met["ath"]) > fc["o"] else 1.0)
        if upd is not None: upd[mint] = {"launch_open": launch_open, "fc": met, "m1_at": now, "seen": now}
    p, sh = met["f1_pct"], met["share"]
    if newpairs:
        bad = p >= NP_R7_MIN_PCT
        txt = f"rule 7 · first candle +{p*100:.0f}% (rug pattern; newpairs max +{NP_R7_MIN_PCT*100:.0f}%)"
    else:
        bad = p >= R7_MIN_PCT and sh >= R7_MIN_SHARE
        txt = f"rule 7 · first candle +{p*100:.0f}% = {sh:.0%} of rise to ATH (rug pattern; max +{R7_MIN_PCT*100:.0f}% & {R7_MIN_SHARE:.0%})"
    return (txt if bad else None), met

# ---------------- rule 9 / 10 ----------------
def chase_metrics(m1, now):
    """m1: 1m candles (ascending, only candles that started before `now`). run15/run30 = last close vs the close
    of the last candle that started <= 15/30 min ago (launch open if none); n60 = active minutes in the last hour;
    red10 = biggest open->close drop of one 1m candle in the last R10_WIN_S seconds."""
    m1 = [x for x in m1 if x[0] <= now]
    if not m1: return None
    px = m1[-1][4]
    def close_at(sec):
        c = [x for x in m1 if x[0] <= now - sec]
        return c[-1][4] if c else m1[0][1]
    def run(sec):
        b = close_at(sec); return px / b - 1 if b > 0 else 0.0
    w = [x for x in m1 if x[0] >= now - R10_WIN_S]
    return {"run15": run(900), "run30": run(1800), "n60": sum(1 for x in m1 if x[0] >= now - 3600),
            "red10": max([(x[1] - x[4]) / x[1] for x in w if x[1] > 0] or [0.0]), "px": px}

def chase_verdict(m, newpairs=False):
    if not m: return None
    lim = NP_R9_MAX_RUN15 if newpairs else R9_MAX_RUN15
    if m["run15"] >= lim:
        return f"rule 9 · chase: +{m['run15']*100:.0f}% in 15 min (vertical run-up; max +{lim*100:.0f}%)"
    if not newpairs and m["n60"] < R9_YOUNG_N60 and m["run30"] >= R9_YOUNG_MAX_RUN30:
        return f"rule 9 · chase: young pool ({m['n60']} active min/1h < {R9_YOUNG_N60}) +{m['run30']*100:.0f}% in 30 min (max +{R9_YOUNG_MAX_RUN30*100:.0f}%)"
    red = NP_R10_MAX_RED1M if newpairs else R10_MAX_RED1M
    if m["red10"] >= red:
        return f"rule 10 · dump candle: -{m['red10']*100:.0f}% in one 1m candle within {R10_WIN_S//60} min (max -{red*100:.0f}%)"
    return None

def rule9(mint, newpairs=False, fetch=None, cache=None, upd=None, now=None):
    """rule 9 (chase) + rule 10 (dump candle). Returns (fail_text or None, metrics). Raises NoData/Budget."""
    now = now or time.time(); e = (cache or {}).get(mint, {})
    mm = _M1.get(mint) if fetch is None else None
    if mm and time.time() - mm[0] < TTL_1M: met = chase_metrics(mm[1], now)
    elif e.get("r9") and now - e.get("r9_at", 0) < TTL_1M: met = e["r9"]
    else:
        m1 = candles(mint, "1m", fetch=fetch)
        if fetch is None: _M1[mint] = (time.time(), m1)
        met = chase_metrics(m1, now)
    if met is None: raise NoData("no 1m candles before now")
    if upd is not None: upd.setdefault(mint, {}).update({"r9": met, "r9_at": now, "seen": now})
    return chase_verdict(met, newpairs), met

# ---------------- rule 8 ----------------
def wash_features(w):
    if len(w) < W8: return None
    w = w[-W8:]; span = w[-1][0] - w[0][0] + 1
    b = [x[4] - x[1] for x in w]; nz = [v for v in b if v != 0]
    sg = [1 if v > 0 else -1 for v in nz]
    alt = sum(1 for a, q in zip(sg, sg[1:]) if a != q) / max(1, len(sg) - 1)
    bod = [abs(v) / x[1] for v, x in zip(b, w) if v != 0 and x[1] > 0]
    cvb = st.pstdev(bod) / st.mean(bod) if len(bod) >= 10 and st.mean(bod) > 0 else 9.0
    tot = sum(abs(v) for v in b); er = abs(w[-1][4] - w[0][1]) / tot if tot else 1.0
    cl = sorted(x[4] for x in w); med = st.median(cl)
    band = (cl[int(.95 * len(cl)) - 1] - cl[int(.05 * len(cl))]) / med if med else 9.0
    reds = [-v / x[1] for v, x in zip(b, w) if v < 0 and x[1] > 0 and -v / x[1] > ST_RED_MIN]
    cvred = st.pstdev(reds) / st.mean(reds) if len(reds) >= 5 else 9.0
    r = [v / x[1] for v, x in zip(b, w) if x[1] > 0]; mu = st.mean(r); den = sum((x - mu) ** 2 for x in r)
    ac1 = sum((r[i] - mu) * (r[i + 1] - mu) for i in range(len(r) - 1)) / den if den else 0.0
    return {"dens": len(w) / span, "alt": alt, "cvb": cvb, "er": er, "band": band, "nred": len(reds), "cvred": cvred, "ac1": ac1}

def wash_verdict(f):
    if not f: return None
    if f["alt"] >= MW_ALT and f["cvb"] <= MW_CVB and f["band"] <= MW_BAND and f["er"] <= MW_ER:
        return f"rule 8 · bot-wash pattern (micro-wash: alt {f['alt']:.2f}, size CV {f['cvb']:.2f}, band {f['band']*100:.1f}%, 1s x{W8})"
    if (f["dens"] >= ST_DENS and f["nred"] >= ST_NRED and f["cvred"] <= ST_CVRED and f["ac1"] <= ST_AC1 and f["er"] <= ST_ER):
        return f"rule 8 · bot-wash pattern (sawtooth: {f['nred']} regular drops CV {f['cvred']:.2f}, autocorr {f['ac1']:.2f}, drift {f['er']:.2f}, 1s x{W8})"
    return None

def rule8(mint, fetch=None, cache=None, upd=None, now=None):
    """Returns (fail_text or None, features or None). Raises NoData if the 1s history can't be fetched."""
    now = now or time.time(); e = (cache or {}).get(mint, {})
    if e.get("w8") is not None and now - e.get("w8_at", 0) < TTL_1S:
        return e["w8"].get("v"), e["w8"].get("f")
    s1 = [x for x in candles(mint, "1s", limit=300, fetch=fetch) if now - x[0] <= W8_MAX_AGE_S]
    f = wash_features(s1) if s1 and now - s1[-1][0] <= W8_LAST_MAX_S else None
    v = wash_verdict(f)
    if upd is not None: upd.setdefault(mint, {}).update({"w8": {"v": v, "f": f}, "w8_at": now, "seen": now})
    return v, f

# ---------------- entry point ----------------
def check(mint, newpairs=False, fetch=None, save=True):
    """Returns (fails, notes). fails = skip reasons (rule 7 / 9 / 10 / 8 texts, or 'no first-candle data' for newpairs);
    notes = data-unavailable messages that were ALLOWED (to be logged by the caller)."""
    cache = _load() if save else {}; upd = {}; fails, notes = [], []
    try:
        t7, _ = rule7(mint, newpairs=newpairs, fetch=fetch, cache=cache, upd=upd)
        if t7: fails.append(t7)
    except Budget as e:
        fails.append(f"not judged: rule 7/8 not checked ({e}) -> no buy this run")
    except NoData as e:
        if newpairs: fails.append(f"rule 7 · no first-candle data ({e})")
        else: notes.append(f"rule 7 n/a ({e}) -> allowed")
    try:
        t9, _ = rule9(mint, newpairs=newpairs, fetch=fetch, cache=cache, upd=upd)
        if t9: fails.append(t9)
    except Budget as e:
        if not any(x.startswith("not judged") for x in fails): fails.append(f"not judged: rule 9/10 not checked ({e}) -> no buy this run")
    except NoData as e:
        notes.append(f"rule 9/10 n/a ({e}) -> allowed")
    try:
        t8, _ = rule8(mint, fetch=fetch, cache=cache, upd=upd)
        if t8: fails.append(t8)
    except Budget as e:
        if not any(x.startswith("not judged") for x in fails): fails.append(f"not judged: rule 8 not checked ({e}) -> no buy this run")
    except NoData as e:
        notes.append(f"rule 8 n/a ({e}) -> allowed")
    if save and upd:
        try: _save(upd)
        except Exception: pass
    return fails, notes
