#!/usr/bin/env python3
"""SELF-LEARN (USER ORDER Dominic 2026-10-22 17:58: "der Bot soll aus seinen Fehlern lernen"). PAPER ONLY.
The meme desk learns from its OWN closed trades and adjusts ONLY an explicit allowlist of entry-filter thresholds (PARAMS).

Data   learner/journal.json (state): one record per closed real trade (epoch seeds + meme_positions.json) and per closed shadow
       trade (logs/shadow_trades.jsonl), with the entry features (recorded at entry as `feat` since 2026-10-22, older trades
       joined from the scan file of the entry minute) and the outcome (PnL %, exit reason, fast stop, rug).
Learn  every RUN_EVERY_MIN minutes or after RUN_EVERY_SELLS new closed sells (`learner.py tick`, every minute in the loop).
Gate   TIGHTEN a threshold: the trades it would newly block (pocket) >= MIN_POCKET real trades, mean PnL <= -EXP_MIN with
       mean + 1 SE < 0, worse than the kept trades, and the same on the time-ordered holdout (most recent HOLDOUT_FRAC of the
       trades; >= HOLDOUT_MIN_N pocket trades there, mean < 0 and below the kept holdout mean).
       LOOSEN: shadow trades stopped ONLY by that gate (shadow book, same fills/exits) that the looser value would admit:
       >= MIN_LOOSEN, mean >= +EXP_MIN with mean - 1 SE > 0, holdout (last HOLDOUT_FRAC) >= HOLDOUT_MIN_N with mean > 0.
       Step <= MAX_STEP (25 %) of the current value, hard floor/ceiling per parameter, max one change per parameter per
       COOLDOWN_H (24 h), max MAX_CHANGES_PER_RUN per run. Anything not in PARAMS (paper-only, the fixed 10 EUR ticket, max
       positions 6/3/8, stop-loss / take-profit / trailing structure, daily limit off, RugCheck / I-18 / security) is FORBIDDEN.
Revert after REVERT_N real trades entered after a change: if their mean PnL is below the REVERT_N trades before it -> revert.
Out    learner_overrides.json (state; applied at import by scan.py / meme.py / rugpattern.py via apply()), learner/report.json
       (bins: n, win rate, avg PnL per feature), logs/learner.log, logs/learner_changes.jsonl (box mirrors new entries into
       CHANGELOG_research.md + shared/KNOWLEDGE.md tagged SELF-LEARN: `learner.py publish`).
Kill   LEARNER_ENABLED below, env LEARNER_ENABLED=0/1 overrides it. Disabled = no learning AND no overrides applied (code values).
CLI    learner.py tick | run [--dry] [--force] | report | publish"""
import os, sys, json, math, glob, time, fcntl, datetime as dt
from zoneinfo import ZoneInfo

LEARNER_ENABLED = True
DESK = os.path.expanduser("~/.desk"); BER = ZoneInfo("Europe/Berlin"); UTC = dt.timezone.utc
OVR = f"{DESK}/learner_overrides.json"; JOURNAL = f"{DESK}/learner/journal.json"; REPORT = f"{DESK}/learner/report.json"
LOG = f"{DESK}/logs/learner.log"; CHANGES = f"{DESK}/logs/learner_changes.jsonl"; LOCK = f"{DESK}/.learner_run.lock"   # NOT .learner.lock: the cron line holds that one via flock(1)
MIN_POCKET, MIN_LOOSEN, HOLDOUT_FRAC, HOLDOUT_MIN_N = 15, 20, 0.30, 5
EXP_MIN = 0.05                     # "clearly": mean PnL per trade <= -5 % (tighten) / >= +5 % (loosen) AND 1 SE away from 0
MAX_STEP = 0.25; STEPS = (0.05, 0.10, 0.15, 0.20, 0.25)
COOLDOWN_H = 24; REVERT_N = 48; REVERT_MIN_BEFORE = 15; MAX_CHANGES_PER_RUN = 2
RUN_EVERY_MIN, RUN_EVERY_SELLS = 30, 10
FAST_STOP_MIN = 10; RUG_PCT = -0.50

def enabled():
    e = (os.environ.get("LEARNER_ENABLED") or "").strip().lower()
    if e in ("0", "false", "off", "no"): return False
    if e in ("1", "true", "on", "yes"): return True
    return LEARNER_ENABLED

# ---------------- allowlist of tunable thresholds ----------------
# kind "min": a trade is blocked if feature < value  ("ge": blocked if feature >= value, combined with a partner rule)
# kind "max": blocked if feature > value. gate = shadow category prefix ("main:gate:" + gate) for loosening evidence.
def _P(mod, path, kind, floor, ceil, feat, gate, venue=None, rnd=None, label=""):
    return {"mod": mod, "path": path, "kind": kind, "floor": floor, "ceil": ceil, "feat": feat, "gate": gate, "venue": venue, "rnd": rnd, "label": label}
PARAMS = {
    "scan.RULES.pumpswap.liq_min":          _P("scan", "RULES.pumpswap.liq_min", "min", 8_000, 60_000, "liq", "scan: liquidity <", "pumpswap", 100, "Mindest-Liquidität PumpSwap"),
    "scan.RULES.pumpswap.mcap_min":         _P("scan", "RULES.pumpswap.mcap_min", "min", 25_000, 150_000, "mcap", "scan: mcap <", "pumpswap", 1000, "Mindest-Marktkapitalisierung PumpSwap"),
    "scan.RULES.pumpswap.mcap_max":         _P("scan", "RULES.pumpswap.mcap_max", "max", 1_000_000, 8_000_000, "mcap", "scan: mcap >", "pumpswap", 10_000, "Höchst-Marktkapitalisierung PumpSwap"),
    "scan.RULES.pumpswap.vol24_min":        _P("scan", "RULES.pumpswap.vol24_min", "min", 25_000, 250_000, "vol24", "scan: 24h vol <", "pumpswap", 1000, "Mindest-24h-Volumen PumpSwap"),
    "scan.RULES.pumpswap.max_vol24_to_liq": _P("scan", "RULES.pumpswap.max_vol24_to_liq", "max", 10, 40, "vol_liq", "scan: vol/liq wash", "pumpswap", 0.5, "Max. Volumen/Liquidität (Wash) PumpSwap"),
    "scan.RULES.pumpswap.age_max_h":        _P("scan", "RULES.pumpswap.age_max_h", "max", 12, 72, "age_h", "scan: age >", "pumpswap", 0.5, "Max. Pool-Alter PumpSwap (h)"),
    "scan.RULES.pumpswap.age_min_h":        _P("scan", "RULES.pumpswap.age_min_h", "min", 0.25, 3, "age_h", "scan: age <", "pumpswap", 0.05, "Min. Pool-Alter PumpSwap (h)"),
    "scan.RULES.min_buys_h1":               _P("scan", "RULES.min_buys_h1", "min", 10, 60, "buys_h1", "scan: buys h1 <", None, 1, "Mindest-Käufe 1h"),
    "scan.RULES.min_buys_m15":              _P("scan", "RULES.min_buys_m15", "min", 2, 10, "buys_m15", "scan: buys m15 <", None, 1, "Mindest-Käufe 15 min"),
    "meme.J_MIN_BUYERS_H1":                 _P("meme", "J_MIN_BUYERS_H1", "min", 40, 250, "buyers_h1", "judge: unique buyers h1", None, 1, "Mindest-Unique-Käufer 1h"),
    "meme.J_MIN_BUYERS_PER_BUY":            _P("meme", "J_MIN_BUYERS_PER_BUY", "min", 0.20, 0.60, "buyers_per_buy", "judge: buyers/buy h1", None, 0.01, "Käufer pro Kauf (Anti-Bot)"),
    "meme.J_MIN_BS_M15":                    _P("meme", "J_MIN_BS_M15", "min", 1.0, 3.0, "bs_m15", "judge: buys/sells m15", None, 0.05, "Käufe/Verkäufe 15 min"),
    "meme.J_PC_H1.0":                       _P("meme", "J_PC_H1.0", "min", 5.0, 60.0, "pc_h1", "judge: price h1", None, 0.5, "Kursanstieg 1h – Untergrenze (%)"),
    "meme.J_PC_H1.1":                       _P("meme", "J_PC_H1.1", "max", 100.0, 300.0, "pc_h1", "judge: price h1", None, 5, "Kursanstieg 1h – Obergrenze (%)"),
    "rugpattern.R7_MIN_PCT":                _P("rugpattern", "R7_MIN_PCT", "ge", 3.0, 10.0, "f1_pct", "judge: rule 7 first candle", None, 0.1, "Regel 7: erste Kerze ab +x (1 = +100 %)"),
    "rugpattern.R7_MIN_SHARE":              _P("rugpattern", "R7_MIN_SHARE", "ge", 0.30, 0.80, "r7_share", "judge: rule 7 first candle", None, 0.01, "Regel 7: Anteil der ersten Kerze am Anstieg"),
    # 2026-10-22 USER ORDER 21:44 (anti-chase / dump candle): ceil = shipped value -> the learner can only tighten these
    "rugpattern.R9_MAX_RUN15":              _P("rugpattern", "R9_MAX_RUN15", "max", 0.60, 1.0, "run15", "judge: rule 9 chase", None, 0.05, "Regel 9: max. Anstieg 15 min (1 = +100 %)"),
    "rugpattern.R10_MAX_RED1M":             _P("rugpattern", "R10_MAX_RED1M", "max", 0.12, 0.20, "red10", "judge: rule 10 dump candle", None, 0.01, "Regel 10: max. Einbruch einer 1m-Kerze (10 min)"),
}
R7_PARTNER = {"rugpattern.R7_MIN_PCT": ("r7_share", "rugpattern.R7_MIN_SHARE"), "rugpattern.R7_MIN_SHARE": ("f1_pct", "rugpattern.R7_MIN_PCT")}
FORBIDDEN_PREFIXES = ("meme.FIXED_TICKET", "meme.TICKET_PCT", "meme.MIN_TICKET", "meme.LIQ_CAP", "meme.MAX_OPEN", "meme.TOTAL_MAX_OPEN",
                      "newpairs.MAX_OPEN", "meme.STOP_LOSS", "meme.MAIN_EXIT", "meme.TRAIL", "meme.TIME_STOP", "meme.EXIT", "newpairs.EXIT",
                      "meme.DAILY_DD", "meme.RC_", "meme.I18_", "meme.PAPER", "ALPACA", "alp_", "killswitch", "scan.COOLDOWN", "meme.JUDGE_BUDGET",
                      # USER ORDER 2026-10-24 01:24/01:25: exit regime (TP ladder, fixed post-TP stop, no trailing/lock), fast exits, check cadence
                      "meme.LOCK", "meme.TAKE_PROFIT", "meme.TP_", "meme.POST_TP", "meme.VC_", "meme.FAST_", "meme.NODATA", "meme.LIQ_PULL",
                      "meme.RISK_", "meme.VOL_MIN_AGE", "meme.regime", "newpairs.VOL_COLLAPSE", "newpairs.SAFETY", "shadow.")
BASE = {}          # parameter -> code value captured by apply() before any override

def forbidden(name):
    return name not in PARAMS or any(name.startswith(p) for p in FORBIDDEN_PREFIXES)

# ---------------- helpers ----------------
def log(m):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"{dt.datetime.now(BER):%Y-%m-%d %H:%M:%S %Z} [LEARN] {m}"
    with open(LOG, "a") as f: f.write(line + "\n")
    if sys.stdout.isatty(): print(line)   # cron appends stdout to the same LOG -> no duplicate lines

def load_json(p, d):
    try: return json.load(open(p))
    except (FileNotFoundError, ValueError): return d

def save_json(p, d):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True); tmp = p + ".tmp"
    json.dump(d, open(tmp, "w"), indent=1, default=str); os.replace(tmp, p)

def _ts(s):
    try: return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError): return None

def _get(g, path):
    cur = g
    for k in path.split("."): cur = cur[int(k)] if isinstance(cur, (list, tuple)) else cur[k]
    return cur

def _set(g, path, v):
    ks = path.split(".")
    if len(ks) == 1: g[ks[0]] = v; return
    chain = [g]
    for k in ks[:-1]: chain.append(chain[-1][int(k)] if isinstance(chain[-1], (list, tuple)) else chain[-1][k])
    parent, last = chain[-1], ks[-1]
    if isinstance(parent, tuple):
        lst = list(parent); lst[int(last)] = v; chain[-2][ks[-2]] = tuple(lst)
    elif isinstance(parent, list): parent[int(last)] = v
    else: parent[last] = v

def _round(spec, v):
    r = spec.get("rnd")
    if not r: return v
    v = round(round(v / r) * r, 6)
    return int(v) if float(r).is_integer() and float(v).is_integer() else v

def load_overrides():
    return load_json(OVR, {"version": 1, "params": {}, "changes": []})

def valid_value(name, v):
    spec = PARAMS.get(name)
    return bool(spec) and not forbidden(name) and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and spec["floor"] <= v <= spec["ceil"]

def apply(modname, g, path=None):
    """Called at import by scan.py / meme.py / rugpattern.py right after their threshold constants. Never raises."""
    try:
        for name, spec in PARAMS.items():
            if spec["mod"] == modname and name not in BASE:
                try: BASE[name] = _get(g, spec["path"])
                except Exception: pass
        if not enabled(): return {}
        ov = load_json(path or OVR, {}).get("params") or {}
        done = {}
        for name, ent in ov.items():
            spec = PARAMS.get(name)
            if not spec or spec["mod"] != modname: continue
            v = (ent or {}).get("value")
            if not valid_value(name, v): continue
            _set(g, spec["path"], v); done[name] = v
        return done
    except Exception:
        return {}

def current(name, ov=None):
    ov = ov if ov is not None else load_overrides()
    e = (ov.get("params") or {}).get(name)
    if e and valid_value(name, e.get("value")): return e["value"]
    if name in BASE: return BASE[name]
    _import_bases(); return BASE.get(name)

def _import_bases():
    """fill BASE with the code values (import of the modules runs apply(), which captures them before overriding)."""
    sys.path.insert(0, DESK)
    for m in ("scan", "rugpattern", "meme"):
        try: __import__(m)
        except Exception as e: log(f"base import {m}: {type(e).__name__} {str(e)[:80]}")

# ---------------- features ----------------
def _num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def features(c, entry_iso=None, mint=None):
    """Entry features from a scan candidate dict (full or slim). Pure apart from the rugpattern/dial file reads."""
    h1 = c.get("tx_h1") or {}; m15 = c.get("tx_m15") or {}
    liq, vol = _num(c.get("liquidity_usd")), _num(c.get("vol_h24"))
    buys, buyers = _num(h1.get("buys")), _num(h1.get("buyers"))
    b15, s15 = _num(m15.get("buys")), _num(m15.get("sells"))
    f = {"venue": c.get("venue"), "liq": liq, "mcap": _num(c.get("mcap_usd")), "vol24": vol,
         "vol_liq": (vol / liq) if vol is not None and liq else None, "age_h": _num(c.get("age_h")),
         "buys_h1": buys, "sells_h1": _num(h1.get("sells")), "buyers_h1": buyers,
         "buyers_per_buy": (buyers / buys) if buyers is not None and buys else None,
         "buys_m15": b15, "sells_m15": s15, "bs_m15": (b15 / s15 if s15 else (99.0 if b15 else 0.0)) if b15 is not None else None,
         "pc_h1": _num(c.get("pc_h1")), "pc_m5": _num(c.get("pc_m5")), "score": _num(c.get("score")),
         "wallet": (c.get("wallet") or {}).get("n") or 0, "watch": bool(c.get("watch")),
         "src": c.get("src") if isinstance(c.get("src"), list) else None}
    m = mint or c.get("base_token") or c.get("token")
    if m:
        rp = (_rugcache().get(m) or {}).get("fc") or {}
        f["f1_pct"], f["r7_share"] = _num(rp.get("f1_pct")), _num(rp.get("share"))
        r9 = (_rugcache().get(m) or {}).get("r9") or {}
        f["run15"], f["red10"] = _num(r9.get("run15")), _num(r9.get("red10"))
    if entry_iso:
        t = dt.datetime.fromisoformat(entry_iso).astimezone(BER); f["hour"] = t.hour; f["dial"] = _dial_at(t)
    return f

_RC = [None]
def _rugcache():
    if _RC[0] is None: _RC[0] = load_json(f"{DESK}/scan/rugpattern_cache.json", {})
    return _RC[0]

_DIAL = [None]
def _dial_at(t):
    if _DIAL[0] is None:
        _DIAL[0] = []
        for p in sorted(glob.glob(f"{DESK}/dial/*.json")):
            d = load_json(p, {})
            try: _DIAL[0].append((dt.datetime.fromisoformat(d["generated_at"]), (d.get("dial") or {}).get("meme")))
            except Exception: pass
    best = None
    for g, v in _DIAL[0]:
        if g <= t: best = v
    return best

_SCANS = {}
def _scan_file(key):
    if key not in _SCANS: _SCANS[key] = load_json(f"{DESK}/scan/{key}.json", None)
    return _SCANS[key]

_REJ = {}
def _rejects_day(day):
    if day not in _REJ:
        rows = {}
        try:
            for l in open(f"{DESK}/scan/rejects-{day}.jsonl"):
                if '"type":"scan"' not in l[:40]: continue
                try: r = json.loads(l)
                except ValueError: continue
                rows[str(r.get("scanned_at"))[:16]] = (r.get("passed_candidates") or []) + (r.get("rejects") or [])
        except FileNotFoundError: pass
        _REJ[day] = rows
    return _REJ[day]

def join_features(pool, token, entry_iso):
    """features from the scan of the entry minute (or up to 3 min before); slim reject rows as last resort."""
    try: t = dt.datetime.fromisoformat(entry_iso).astimezone(BER)
    except (TypeError, ValueError): return None
    for m in range(0, 4):
        k = (t - dt.timedelta(minutes=m)).strftime("%Y-%m-%d_%H%M"); d = _scan_file(k)
        if not d: continue
        c = next((c for c in d.get("candidates") or [] if c.get("pool") == pool or (token and c.get("base_token") == token)), None)
        if c: return features(c, entry_iso, token)
    for m in range(0, 4):
        tt = t - dt.timedelta(minutes=m); rows = _rejects_day(tt.date().isoformat())
        for k, lst in rows.items():
            if k == tt.strftime("%Y-%m-%dT%H:%M"):
                c = next((c for c in lst if c.get("pool") == pool), None)
                if c: return features(c, entry_iso, token)
    return None

# ---------------- journal ----------------
def _entry_type(o):
    if o.get("sleeve") == "newpairs": return "newpairs:" + str(o.get("tier") or "?")
    d = (o.get("dip") or "").lower()
    if d.startswith("dip entry"): return "dip"
    if "watch" in d: return "watchlist"
    return "direct" if not d else "other"

def _outcome(rec, parts, exit_reason, hold_min):
    cost = sum(float(p.get("cost_usd") or 0) for p in parts) or float(rec.get("cost_usd") or 0)
    pnl = sum(float(p.get("pnl") or 0) for p in parts)
    pp = pnl / cost if cost else None
    r = (exit_reason or "").lower()
    return {"cost": round(cost, 4), "pnl": round(pnl, 4), "pnl_pct": round(pp, 4) if pp is not None else None, "exit_reason": exit_reason,
            "hold_min": round(hold_min, 1) if hold_min is not None else None,
            "fast_stop": bool(r.startswith("stop-loss") and hold_min is not None and hold_min <= FAST_STOP_MIN),
            "rug": bool((pp is not None and pp <= RUG_PCT) or "rug" in r or "liquidity pull" in r)}

def real_closed():
    """[(epoch, closed records)] from the epoch seeds (archive/ on the box, learner_seed_epoch*.json in the repo) + current book."""
    out, seen = [], set()
    for p in sorted(glob.glob(f"{DESK}/archive/meme_epoch*_*.json")) + sorted(glob.glob(f"{DESK}/learner_seed_epoch*.json")):
        try: ep = int(os.path.basename(p).split("epoch")[1].split("_")[0].split(".")[0])
        except (IndexError, ValueError): continue
        if ep in seen: continue
        seen.add(ep); d = load_json(p, {}); out.append((ep, d.get("closed") or []))
    bank = load_json(f"{DESK}/bank.json", {})
    out.append((int(bank.get("epoch", len(seen) + 1)), (load_json(f"{DESK}/meme_positions.json", {}) or {}).get("closed") or []))
    return out

def n_closed_sells():
    return sum(len(cl) for _, cl in real_closed())

def build_journal(j=None):
    j = j if j is not None else load_json(JOURNAL, {"real": {}, "shadow": {}})
    j.setdefault("real", {}); j.setdefault("shadow", {})
    for ep, cl in real_closed():
        g = {}
        for t in cl: g.setdefault(f"{t.get('token')}|{t.get('entry_time')}", []).append(t)
        for key, parts in g.items():
            fin = [p for p in parts if not p.get("partial")]
            if not fin: continue
            o = fin[-1]; old = j["real"].get(key)
            et, xt = _ts(o.get("entry_time")), _ts(o.get("exit_time"))
            rec = {"epoch": ep, "exit_regime": o.get("exit_regime") or "legacy", "sleeve": o.get("sleeve", "main"), "venue": o.get("venue"), "name": o.get("name"), "token": o.get("token"),
                   "pool": o.get("pool"), "entry_time": o.get("entry_time"), "exit_time": o.get("exit_time"), "entry_type": _entry_type(o),
                   **_outcome(o, parts, o.get("exit_reason"), (xt - et) / 60 if et and xt else None)}
            feat = (old or {}).get("feat") or o.get("feat")
            if not feat and o.get("sleeve") != "newpairs": feat = join_features(o.get("pool"), o.get("token"), o.get("entry_time"))
            if o.get("sleeve") == "newpairs":
                tr = o.get("traction") or {}
                feat = {**(feat or {}), "venue": o.get("venue"), "narrative_score": o.get("narrative_score"), "buyers": tr.get("buyers"),
                        "sniper_pct": tr.get("sniper_pct"), "dev_buy_pct": tr.get("dev_buy_pct"), "hour": dt.datetime.fromisoformat(o["entry_time"]).astimezone(BER).hour}
            if feat: feat.setdefault("entry_type", rec["entry_type"])
            rec["feat"] = feat
            j["real"][key] = rec
    buys, sells = {}, {}
    try:
        for l in open(f"{DESK}/logs/shadow_trades.jsonl"):
            try: r = json.loads(l)
            except ValueError: continue
            if r.get("type") == "SHADOW_BUY": buys[r["id"]] = r
            elif r.get("type") == "SHADOW_SELL": sells.setdefault(r["id"], []).append(r)
    except FileNotFoundError: pass
    for sid, b in buys.items():
        ps = sells.get(sid) or []
        fin = [p for p in ps if not p.get("partial")]
        if not fin or sid in j["shadow"] and j["shadow"][sid].get("feat"): continue
        o = fin[-1]; et, xt = _ts(b.get("entry_time")), _ts(o.get("exit_time"))
        rec = {"cat": b.get("cat"), "exit_regime": o.get("exit_regime") or b.get("exit_regime") or "legacy", "sleeve": b.get("sleeve", "main"), "venue": b.get("venue"), "name": b.get("name"), "token": b.get("token"),
               "pool": b.get("pool"), "entry_time": b.get("entry_time"), "exit_time": o.get("exit_time"),
               **_outcome(b, ps, o.get("reason"), (xt - et) / 60 if et and xt else None)}
        rec["feat"] = b.get("feat") or (join_features(b.get("pool"), b.get("token"), b.get("entry_time")) if b.get("sleeve") != "newpairs" else None)
        j["shadow"][sid] = rec
    j["built_at"] = dt.datetime.now(BER).isoformat(timespec="seconds")
    return j

# ---------------- statistics + gate ----------------
def stats(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if not n: return {"n": 0, "mean": None, "se": None, "win": None, "sum": 0.0}
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": round(m, 4), "se": round(sd / math.sqrt(n), 4) if n > 1 else None, "win": round(sum(1 for x in xs if x > 0) / n, 3), "sum": round(sum(xs), 4)}

def blocked(name, feat, value, cur=None):
    """True if a trade with these entry features would be blocked by parameter `name` set to `value` (None feature -> False)."""
    spec = PARAMS[name]; x = (feat or {}).get(spec["feat"])
    if x is None: return False
    if spec["venue"] and (feat or {}).get("venue") != spec["venue"]: return False
    if spec["kind"] == "min": return x < value
    if spec["kind"] == "max": return x > value
    pf, pn = R7_PARTNER[name]; y = (feat or {}).get(pf)            # rule 7: both conditions must hold
    pv = (cur or {}).get(pn)
    return y is not None and pv is not None and x >= value and y >= pv

def candidates(name, v):
    """possible new values within one bounded step, (tighten list, loosen list)."""
    spec = PARAMS[name]; T, L = [], []
    for s in STEPS:
        up, dn = _round(spec, v * (1 + s)), _round(spec, v * (1 - s))
        up_ok = spec["floor"] <= up <= spec["ceil"] and up != v and abs(up - v) <= MAX_STEP * abs(v) + 1e-9
        dn_ok = spec["floor"] <= dn <= spec["ceil"] and dn != v and abs(dn - v) <= MAX_STEP * abs(v) + 1e-9
        if spec["kind"] == "min":
            if up_ok: T.append(up)
            if dn_ok: L.append(dn)
        else:                         # max / ge: a LOWER value blocks more
            if dn_ok: T.append(dn)
            if up_ok: L.append(up)
    return sorted(set(T), key=lambda x: abs(x - v)), sorted(set(L), key=lambda x: abs(x - v))

def _holdout_cut(recs):
    ts = sorted(_ts(r["entry_time"]) for r in recs if _ts(r.get("entry_time")))
    return ts[int(len(ts) * (1 - HOLDOUT_FRAC))] if ts else None

def eval_tighten(name, v, new, trades, cur):
    pop = [t for t in trades if t.get("pnl_pct") is not None and t.get("feat")]
    pocket = [t for t in pop if not blocked(name, t["feat"], v, cur) and blocked(name, t["feat"], new, cur)]
    kept = [t for t in pop if not blocked(name, t["feat"], new, cur)]
    cut = _holdout_cut(pop)
    hp = [t for t in pocket if cut and _ts(t["entry_time"]) >= cut]; hk = [t for t in kept if cut and _ts(t["entry_time"]) >= cut]
    s, sk, shp, shk = (stats([t["pnl_pct"] for t in x]) for x in (pocket, kept, hp, hk))
    why = []
    if s["n"] < MIN_POCKET: why.append(f"pocket n {s['n']} < {MIN_POCKET}")
    else:
        if s["mean"] > -EXP_MIN: why.append(f"pocket mean {s['mean']:+.1%} > -{EXP_MIN:.0%}")
        if s["se"] is None or s["mean"] + s["se"] >= 0: why.append("pocket mean + 1 SE >= 0")
        if sk["n"] and sk["mean"] is not None and s["mean"] >= sk["mean"]: why.append("pocket not worse than kept")
        if shp["n"] < HOLDOUT_MIN_N: why.append(f"holdout pocket n {shp['n']} < {HOLDOUT_MIN_N}")
        elif shp["mean"] >= 0 or (shk["n"] and shk["mean"] is not None and shp["mean"] >= shk["mean"]): why.append(f"holdout fails (pocket {shp['mean']:+.1%} vs kept {shk['mean'] if shk['mean'] is None else format(shk['mean'], '+.1%')})")
    return {"ok": not why, "why": why, "pocket": s, "kept": sk, "holdout_pocket": shp, "holdout_kept": shk, "holdout_from": _iso(cut),
            "pocket_names": [t.get("name") for t in pocket][:10]}

def eval_loosen(name, v, new, shadows, cur):
    gate = "main:gate:" + PARAMS[name]["gate"]
    pop = [t for t in shadows if (t.get("cat") or "").startswith(gate) and t.get("pnl_pct") is not None and t.get("feat")]
    would = [t for t in pop if blocked(name, t["feat"], v, cur) and not blocked(name, t["feat"], new, cur)]
    cut = _holdout_cut(would)
    hw = [t for t in would if cut and _ts(t["entry_time"]) >= cut]
    s, sh = stats([t["pnl_pct"] for t in would]), stats([t["pnl_pct"] for t in hw])
    why = []
    if s["n"] < MIN_LOOSEN: why.append(f"would-be shadow n {s['n']} < {MIN_LOOSEN}")
    else:
        if s["mean"] < EXP_MIN: why.append(f"would-be mean {s['mean']:+.1%} < +{EXP_MIN:.0%}")
        if s["se"] is None or s["mean"] - s["se"] <= 0: why.append("would-be mean - 1 SE <= 0")
        if sh["n"] < HOLDOUT_MIN_N: why.append(f"holdout n {sh['n']} < {HOLDOUT_MIN_N}")
        elif sh["mean"] <= 0: why.append(f"holdout mean {sh['mean']:+.1%} <= 0")
    return {"ok": not why, "why": why, "would_be": s, "holdout": sh, "holdout_from": _iso(cut), "gate_shadow_n": len(pop)}

def _iso(ts): return dt.datetime.fromtimestamp(ts, BER).isoformat(timespec="minutes") if ts else None

def recent_change(ov, name, now_ts):
    for c in reversed(ov.get("changes") or []):
        for k in ("at", "reverted_at"):
            if c.get("param") == name and c.get(k) and now_ts - _ts(c[k]) < COOLDOWN_H * 3600: return c
    return None

def check_reverts(ov, trades, now_ts):
    out = []
    pop = sorted([t for t in trades if t.get("pnl_pct") is not None], key=lambda t: _ts(t["entry_time"]))
    for c in ov.get("changes") or []:
        if c.get("status") != "active" or c.get("kind") == "revert": continue
        at = _ts(c["at"]); post = [t for t in pop if _ts(t["entry_time"]) > at]
        # USER ORDER 2026-10-24: never compare across exit regimes (exit_regime marker) - before/after must share one regime
        reg = (post[0].get("exit_regime") or "legacy") if post else None
        after = [t for t in post if (t.get("exit_regime") or "legacy") == reg][:REVERT_N]
        before = [t for t in pop if _ts(t["entry_time"]) <= at and (t.get("exit_regime") or "legacy") == reg][-REVERT_N:]
        if len(after) < REVERT_N or len(before) < REVERT_MIN_BEFORE: continue
        sa, sb = stats([t["pnl_pct"] for t in after]), stats([t["pnl_pct"] for t in before])
        c["revert_check"] = {"after": sa, "before": sb, "at": _iso(now_ts)}
        if sa["mean"] < sb["mean"]: out.append((c, sa, sb))
    return out

def bins_report(trades, nb=5):
    keys = ("liq", "mcap", "vol24", "vol_liq", "age_h", "buys_h1", "buyers_h1", "buyers_per_buy", "bs_m15", "pc_h1", "pc_m5", "f1_pct", "r7_share", "run15", "red10", "dial", "hour")
    rep = {}
    for k in keys:
        pts = sorted([(t["feat"][k], _ts(t["entry_time"]) or 0, t["pnl_pct"]) for t in trades if (t.get("feat") or {}).get(k) is not None and t.get("pnl_pct") is not None])
        if len(pts) < nb * 3: continue
        rows, i = [], 0
        while i < len(pts):   # ~equal-count bins that never split equal feature values (ties would bias the bins)
            j = min(len(pts), i + max(1, len(pts) // nb))
            while j < len(pts) and pts[j][0] == pts[j - 1][0]: j += 1
            seg = pts[i:j]; s = stats([p for _, _, p in seg]); rows.append({"lo": seg[0][0], "hi": seg[-1][0], **s}); i = j
        rep[k] = rows
    for k in ("entry_type", "venue"):
        g = {}
        for t in trades:
            v = (t.get("feat") or {}).get(k) or t.get(k)
            if v is not None and t.get("pnl_pct") is not None: g.setdefault(str(v), []).append(t["pnl_pct"])
        rep[k] = [{"value": v, **stats(xs)} for v, xs in sorted(g.items())]
    return rep

# ---------------- main cycle ----------------
def run(dry=False, force=False, now=None):
    now = now or dt.datetime.now(UTC); now_ts = now.timestamp()
    if not enabled() and not dry: log("disabled (LEARNER_ENABLED) -> nothing done"); return None
    _import_bases()
    j = build_journal()
    ov = load_overrides(); ov.setdefault("params", {}); ov.setdefault("changes", [])
    cur = {n: current(n, ov) for n in PARAMS}
    real = [t for t in j["real"].values() if t.get("sleeve") == "main"]
    shadows = [t for t in j["shadow"].values() if t.get("sleeve") == "main"]
    with_feat = [t for t in real if t.get("feat")]
    res = {"at": now.astimezone(BER).isoformat(timespec="seconds"), "dry": dry, "trades_real": len(j["real"]), "trades_main": len(real),
           "trades_main_with_features": len(with_feat), "shadow_trades": len(shadows), "overall": stats([t["pnl_pct"] for t in real]),
           "fast_stops": sum(1 for t in real if t.get("fast_stop")), "rugs": sum(1 for t in real if t.get("rug")),
           "by_exit_regime": {r: stats([t["pnl_pct"] for t in real if (t.get("exit_regime") or "legacy") == r]) for r in sorted({t.get("exit_regime") or "legacy" for t in real})},
           "proposals": [], "rejected": {}, "reverts": []}
    # 1) auto-revert
    for c, sa, sb in check_reverts(ov, real, now_ts):
        old, new = c["new"], c["old"]
        ent = {"id": f"L{int(now_ts)}-{c['param'].split('.')[-1]}-rev", "at": res["at"], "param": c["param"], "kind": "revert", "old": old, "new": new,
               "reverts": c["id"], "status": "active", "evidence": {"after": sa, "before": sb},
               "reason_de": f"zurückgenommen: {REVERT_N} Trades danach Ø {sa['mean']:+.1%} schlechter als {sb['n']} davor Ø {sb['mean']:+.1%}"}
        res["reverts"].append(ent)
        if not dry:
            c["status"] = "reverted"; c["reverted_at"] = res["at"]; ov["changes"].append(ent)
            if valid_value(c["param"], new) and new != BASE.get(c["param"]): ov["params"][c["param"]] = {"value": new, "change": ent["id"], "at": res["at"]}
            else: ov["params"].pop(c["param"], None)
            cur[c["param"]] = new; _record(ent)
    # 2) proposals
    props = []
    for name, spec in PARAMS.items():
        if forbidden(name): continue
        v = cur.get(name)
        if v is None: res["rejected"][name] = ["current value unknown"]; continue
        rc = recent_change(ov, name, now_ts)
        if rc and not force: res["rejected"][name] = [f"changed < {COOLDOWN_H} h ago ({rc.get('id')})"]; continue
        T, L = candidates(name, v); best = None; notes = []
        for new in T:
            e = eval_tighten(name, v, new, with_feat, cur)
            if e["ok"]:
                gain = -e["pocket"]["sum"]
                if not best or gain > best[2]: best = ("tighten", new, gain, e)
            else: notes.append(f"tighten {new}: " + "; ".join(e["why"][:2]))
        if not best:
            for new in L:
                e = eval_loosen(name, v, new, shadows, cur)
                if e["ok"]:
                    gain = e["would_be"]["sum"]
                    if not best or gain > best[2]: best = ("loosen", new, gain, e)
                else: notes.append(f"loosen {new}: " + "; ".join(e["why"][:2]))
        if best: props.append((name, v) + best)
        else: res["rejected"][name] = notes[:12] or ["no candidate value within step/floor/ceiling"]
    props.sort(key=lambda p: -p[4])
    for name, v, kind, new, gain, e in props[:MAX_CHANGES_PER_RUN]:
        spec = PARAMS[name]
        if kind == "tighten":
            s, h = e["pocket"], e["holdout_pocket"]
            rde = (f"verschärft: {s['n']} Trades im Bereich {_fmt(spec, v)}–{_fmt(spec, new)} Ø {s['mean']:+.1%} (Gewinnquote {s['win']:.0%}), "
                   f"neueste 30 %: {h['n']} Trades Ø {h['mean']:+.1%}")
        else:
            s, h = e["would_be"], e["holdout"]
            rde = (f"gelockert: {s['n']} Shadow-Trades, die nur an dieser Schwelle scheiterten, Ø {s['mean']:+.1%} (Gewinnquote {s['win']:.0%}), "
                   f"neueste 30 %: {h['n']} Ø {h['mean']:+.1%}")
        ent = {"id": f"L{int(now_ts)}-{name.split('.')[-1]}", "at": res["at"], "param": name, "label": spec["label"], "kind": kind, "old": v, "new": new,
               "status": "active", "evidence": e, "trades_analysed": len(with_feat), "reason_de": rde}
        res["proposals"].append(ent)
        if not dry:
            ov["changes"].append(ent); ov["params"][name] = {"value": new, "change": ent["id"], "at": res["at"]}; _record(ent)
    for name, v, kind, new, gain, e in props[MAX_CHANGES_PER_RUN:]:
        res["rejected"][name] = [f"{kind} {new} valid but max {MAX_CHANGES_PER_RUN} changes per run"]
    res["bins"] = bins_report(with_feat)
    res["current"] = cur; res["base"] = {n: BASE.get(n) for n in PARAMS}
    if not dry:
        ov["last_run"] = res["at"]; ov["last_run_ts"] = now_ts; ov["closed_sells_at_last_run"] = n_closed_sells()
        ov["trades_analysed"] = len(with_feat); ov["enabled"] = True
        save_json(JOURNAL, j); save_json(OVR, ov); save_json(REPORT, res)
        log(f"cycle: {len(real)} main trades ({len(with_feat)} with features), {len(shadows)} shadow; overall Ø {res['overall']['mean']:+.1%}; "
            f"changes {[(p['param'], p['old'], p['new']) for p in res['proposals']]} reverts {[(r['param'], r['old'], r['new']) for r in res['reverts']]}")
    return res

def _fmt(spec, v):
    if spec["feat"] in ("liq", "mcap", "vol24"): return f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:.0f}k"
    if spec["feat"] in ("f1_pct", "run15"): return f"+{v*100:.0f}%"
    if spec["feat"] in ("red10",): return f"-{v*100:.0f}%"
    if spec["feat"] in ("r7_share", "buyers_per_buy"): return f"{v:.2f}"
    return f"{v:g}"

def _record(ent):
    os.makedirs(os.path.dirname(CHANGES), exist_ok=True)
    slim = {k: v for k, v in ent.items() if k != "evidence"}
    ev = ent.get("evidence") or {}
    slim["evidence"] = {k: ev.get(k) for k in ("pocket", "kept", "holdout_pocket", "holdout_kept", "would_be", "holdout", "after", "before", "holdout_from") if ev.get(k) is not None}
    with open(CHANGES, "a") as f: f.write(json.dumps(slim, default=str, ensure_ascii=False) + "\n")
    log(f"SELF-LEARN {ent['kind']} {ent['param']} {ent['old']} -> {ent['new']} | {ent['reason_de']}")

def tick():
    """every minute from the loop: run when RUN_EVERY_MIN passed or RUN_EVERY_SELLS new closed sells."""
    if not enabled(): return None
    ov = load_overrides(); n = n_closed_sells()
    due = time.time() - float(ov.get("last_run_ts") or 0) >= RUN_EVERY_MIN * 60 or n - int(ov.get("closed_sells_at_last_run") or 0) >= RUN_EVERY_SELLS
    if not due: return None
    with open(LOCK, "a") as lk:
        try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return None
        return run()

def publish():
    """BOX side (after pull_state): mirror new SELF-LEARN entries into CHANGELOG_research.md + shared/KNOWLEDGE.md (flock)."""
    seen_p = f"{DESK}/.learner_published.json"; seen = set(load_json(seen_p, []))
    new = []
    try:
        for l in open(CHANGES):
            try: e = json.loads(l)
            except ValueError: continue
            if e.get("id") and e["id"] not in seen: new.append(e)
    except FileNotFoundError: return 0
    if not new: return 0
    with open(f"{DESK}/CHANGELOG_research.md", "a") as f:
        for e in new:
            f.write(f"\n## {e['at'][:16].replace('T', ' ')} — SELF-LEARN {e['kind']}: {e['param']} {e['old']} -> {e['new']} (learner.py, gate passed, no user order)\n"
                    f"- {e.get('reason_de')}\n- evidence: {json.dumps(e.get('evidence'), ensure_ascii=False)[:900]}\n"
                    f"- override in learner_overrides.json (state); auto-revert after {REVERT_N} trades if worse; kill switch LEARNER_ENABLED=0\n")
    kp = f"{DESK}/shared/KNOWLEDGE.md"
    with open(f"{DESK}/shared/.knowledge.lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        with open(kp, "a") as f:
            for e in new:
                f.write(f"{e['at'][:16].replace('T', ' ')} | Self-Learner | SELF-LEARN {e['kind']} | {e.get('label') or e['param']}: {e['old']} -> {e['new']}. {e.get('reason_de')} | learner_overrides.json, CHANGELOG_research.md | {'zurueckgenommen' if e['kind'] == 'revert' else 'aktiv'}\n")
    save_json(seen_p, sorted(seen | {e["id"] for e in new}))
    return len(new)

def cli(a):
    a = a or ["tick"]
    if a[0] == "tick": tick()
    elif a[0] == "run":
        r = run(dry="--dry" in a, force="--force" in a)
        if r is not None and "--dry" in a: print(json.dumps(r, default=str, indent=1, ensure_ascii=False))
    elif a[0] == "report": print(json.dumps(load_json(REPORT, {}), indent=1, ensure_ascii=False, default=str))
    elif a[0] == "publish": print(f"published {publish()} SELF-LEARN entr(y/ies)")
    else: print(__doc__)

if __name__ == "__main__":
    sys.path.insert(0, DESK)
    import learner as _self   # one module object: scan/meme/rugpattern import `learner`, so BASE must live there, not in __main__
    _self.cli(sys.argv[1:])
