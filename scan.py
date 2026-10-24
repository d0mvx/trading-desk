#!/usr/bin/env python3
"""SCAN: pump.fun ecosystem scanner (Solana only). Keyless public data:
  * GeckoTerminal /networks/solana/dexes/pump-fun/pools   (bonding-curve coins)
  * GeckoTerminal /networks/solana/dexes/pumpswap/pools   (graduated coins, PumpSwap)
  * GeckoTerminal /networks/solana/new_pools filtered to dex pump-fun/pumpswap
  * DexScreener (api.dexscreener.com) fallback if GeckoTerminal fails
  * 2026-10-20 14:5x: + extra sources (sources.py): pump.fun frontend-api-v3 feeds (live / active / curve leaders) and
    DexScreener (latest profiles, boosts, top boosts, pump search), dedup by mint, enriched via GT /pools/multi so every
    pool passes the same gates. Cooldown (meme_cooldown.json, 24h after a stop-out / losing close) is a SCAN reject.
Usage: scan.py  -> JSON to stdout, saved to ~/.desk/scan/YYYY-MM-DD_HHMM.json"""
import os, sys, json, glob, math, time, datetime as dt, requests
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.expanduser("~/.desk")); import gt
import entry_rules
from leads import lead_id   # 2026-10-20 research upgrade: lead IDs
DESK = os.path.expanduser("~/.desk"); BER = ZoneInfo("Europe/Berlin"); UTC = dt.timezone.utc
PUMP_DEXES = {"pump-fun": "bonding_curve", "pumpswap": "pumpswap"}
# Filters, per venue (documented in README):
RULES = {
    # 2026-10-20 01:5x (user-approved): PumpSwap mcap_min 60k -> 40k (fresh graduates ~$42k); bonding-curve wash cap 40x -> 100x
    "bonding_curve": {"age_min_h": 0.25, "age_max_h": 72, "mcap_min": 15_000, "mcap_max": 90_000, "vol24_min": 20_000, "liq_min": 5_000, "max_vol24_to_liq": 100},
    "pumpswap":      {"age_min_h": 0.25, "age_max_h": 72, "mcap_min": 40_000, "mcap_max": 8_000_000, "vol24_min": 40_000, "liq_min": 12_000, "max_vol24_to_liq": 40},
    # max_out 2026-10-20 14:5x: 10 -> 25 (bigger universe; Judge is cheap, RugCheck only on gate-passers, 45 s budget)
    "max_out": 60,   # USER ORDER 2026-10-24 13:57: 25 -> 60 (the six rules, not the scan, choose)
    "max_out_legacy": 25, "drop_if_sells_gt_buys_in": ["m15", "h1"],
    "quote": "SOL only (custom-pair coins dropped)", "min_buys_h1": 10, "min_buys_m15": 2,
    "curve_complete_sol": 80,          # bonding curve with >= 80 real SOL (~94% of 85) = complete/graduating -> GT data goes stale
    "stale": "reject if txns (m15+h1) and mcap unchanged for 3 consecutive scans (current = previous 2)",
    "stale_scans": 3,
}
try:   # 2026-10-22 SELF-LEARN (USER ORDER): learner_overrides.json may adjust allowlisted thresholds above (bounded, gated, kill switch)
    import learner as _learner; _learner.apply("scan", globals())
except Exception: pass
COOLDOWN_FILE = os.path.join(os.path.expanduser("~/.desk"), "meme_cooldown.json")
WATCH_FILE = os.path.join(os.path.expanduser("~/.desk"), "meme_watchlist.json")
COOLDOWN_H = 24

def load_json(path, default):
    try: return json.load(open(path))
    except (FileNotFoundError, ValueError): return default

def save_json(path, d):
    tmp = path + ".tmp"; json.dump(d, open(tmp, "w"), indent=1, default=str); os.replace(tmp, path)

def cooldown_active(at=None):
    """{key (mint or pool): entry} for cooldowns still running."""
    at = at or dt.datetime.now(UTC)
    return {k: v for k, v in load_json(COOLDOWN_FILE, {}).items() if dt.datetime.fromisoformat(v["until"]) > at}

def cooldown_add(keys, name, reason, at=None, minutes=None):
    """minutes=None -> COOLDOWN_H hours. A shorter new cooldown never shortens a longer running one (until = max)."""
    at = at or dt.datetime.now(UTC); d = cooldown_active(at)
    until = (at + (dt.timedelta(minutes=minutes) if minutes is not None else dt.timedelta(hours=COOLDOWN_H))).isoformat(timespec="seconds")
    for k in keys:
        if not k: continue
        if k in d and dt.datetime.fromisoformat(d[k]["until"]) >= dt.datetime.fromisoformat(until): continue
        d[k] = {"until": until, "name": name, "reason": reason[:120], "set_at": at.isoformat(timespec="seconds")}
    save_json(COOLDOWN_FILE, d)
    return until

def watchlist_active(at=None):
    at = at or dt.datetime.now(UTC)
    return {k: v for k, v in load_json(WATCH_FILE, {}).items() if dt.datetime.fromisoformat(v["expires_at"]) > at}

FP_FILE = os.path.join(os.path.expanduser("~/.desk"), "scan", "fingerprints.json")

def log(line):
    os.makedirs(f"{DESK}/logs", exist_ok=True)
    with open(f"{DESK}/logs/meme.log", "a") as f: f.write(f"{dt.datetime.now(BER):%Y-%m-%d %H:%M:%S %Z} {line}\n")
    print(line, file=sys.stderr)

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

# pump.fun bonding curve (constant product on virtual reserves):
#   initial virtual SOL 30, virtual tokens 1.073B, total supply 1B, invariant k = 30 * 1.073e9
#   price_SOL = vSOL / vTOK  ->  vSOL = sqrt(k * price_SOL);  real_SOL = vSOL - 30  (graduation ~85 real SOL)
#   LIQUIDITY (bonding curve) := real_SOL * SOL_USD  -- one-sided: the SOL actually in the curve that sellers can
#   take out. Used for the $5k filter, the 2%-of-liquidity ticket cap and display ('~' = derived). Slippage uses the
#   same curve state: impact = notional / (vSOL * SOL_USD) with vSOL = real_SOL + 30.
#   Derived from price (no extra API calls); if price is missing, from mcap/1e9. GeckoTerminal reserve_in_usd is
#   kept as gt_reserve_usd for reference only (often 0/null on pump.fun curve pools).
BC_VSOL0, BC_VTOK0 = 30.0, 1_073_000_000.0
BC_K = BC_VSOL0 * BC_VTOK0
SOL_FALLBACK = [None]

def curve_state(price_usd, sol_usd, mcap_usd=None):
    if not sol_usd: return None
    if not price_usd and mcap_usd: price_usd = mcap_usd / 1e9
    if not price_usd: return None
    vsol = math.sqrt(BC_K * price_usd / sol_usd)
    real = max(0.0, vsol - BC_VSOL0)
    return {"virtual_sol": round(vsol, 4), "real_sol": round(real, 4), "sol_usd": sol_usd,
            "virtual_tokens": round(BC_K / vsol), "progress_pct": round(min(100.0, real / 85.0 * 100), 1),
            "suspect": real > 90,   # beyond graduation -> data mismatch
            "complete": real >= 80}  # curve complete / graduating: pool migrates to PumpSwap, GT curve stats freeze

def evaluate(p, now):
    a = p["attributes"]; rel = p.get("relationships", {}); dex = rel.get("dex", {}).get("data", {}).get("id")
    venue = PUMP_DEXES.get(dex)
    if not venue: return None, ["not pump.fun/pumpswap"]
    R = RULES[venue]; why = []
    age_h = (now - dt.datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
    vol = num((a.get("volume_usd") or {}).get("h24")) or 0
    mcap = num(a.get("market_cap_usd")) or num(a.get("fdv_usd"))
    gt_liq = num(a.get("reserve_in_usd")); liq = gt_liq or 0; liq_derived = False; curve = None
    qt0 = rel.get("quote_token", {}).get("data", {}).get("id", "")
    sol_quoted = (not qt0) or qt0 == "solana_So11111111111111111111111111111111111111112"
    if venue == "bonding_curve" and sol_quoted:   # curve formula only valid for SOL-paired curves
        curve = curve_state(num(a.get("base_token_price_usd")), num(a.get("quote_token_price_usd")) or SOL_FALLBACK[0], mcap)
        if curve:   # one definition for all bonding-curve pools: real SOL in curve x SOL price (derived)
            liq, liq_derived = curve["real_sol"] * curve["sol_usd"], True
    tx = a.get("transactions") or {}; pc = a.get("price_change_percentage") or {}
    def usd(x): return "n/a" if x is None else (f"${x/1e6:.2f}M" if x >= 1e6 else f"${x/1e3:.1f}k" if x >= 1e3 else f"${x:.0f}")
    def hrs(h): return f"{h*60:.0f}m" if h < 1 else f"{h:.1f}h"
    fails = []   # (summary key, exact text)
    if age_h < R["age_min_h"]: fails.append(("age < 15m", f"age {hrs(age_h)} < {hrs(R['age_min_h'])}"))
    if age_h > R["age_max_h"]: fails.append(("age > 72h", f"age {hrs(age_h)} > {hrs(R['age_max_h'])}"))
    if liq < R["liq_min"]: fails.append((f"liquidity < {usd(R['liq_min'])}", f"liquidity {'~' if liq_derived else ''}{usd(liq)} < {usd(R['liq_min'])}"))
    if curve and curve["real_sol"] >= RULES["curve_complete_sol"]:
        fails.append(("curve complete", f"curve complete: real SOL {curve['real_sol']:.1f} >= {RULES['curve_complete_sol']}" + (" (past graduation)" if curve["suspect"] else " (graduating/graduated, stats stale)")))
    if vol < R["vol24_min"]: fails.append((f"24h vol < {usd(R['vol24_min'])}", f"24h vol {usd(vol)} < {usd(R['vol24_min'])}"))
    if mcap is None: fails.append(("mcap missing", "mcap n/a"))
    elif mcap < R["mcap_min"]: fails.append((f"mcap < {usd(R['mcap_min'])}", f"mcap {usd(mcap)} < {usd(R['mcap_min'])}"))
    elif mcap > R["mcap_max"]: fails.append((f"mcap > {usd(R['mcap_max'])}", f"mcap {usd(mcap)} > {usd(R['mcap_max'])}"))
    qt = rel.get("quote_token", {}).get("data", {}).get("id", "")
    if qt and qt != "solana_So11111111111111111111111111111111111111112":
        fails.append(("quote not SOL", f"quote {qt.replace('solana_', '')[:6]}… not SOL"))
    bh1 = (tx.get("h1") or {}).get("buys") or 0; bm15 = (tx.get("m15") or {}).get("buys") or 0
    m15_na = tx.get("m15") is None   # 2026-10-22: DexScreener has no m15 window -> GT enrichment; same gate, missing = fail
    if bh1 < RULES["min_buys_h1"]: fails.append((f"buys h1 < {RULES['min_buys_h1']}", f"buys h1 {bh1} < {RULES['min_buys_h1']}"))
    if bm15 < RULES["min_buys_m15"]: fails.append((f"buys m15 < {RULES['min_buys_m15']}", "buys m15 n/a (no GeckoTerminal m15 data)" if m15_na else f"buys m15 {bm15} < {RULES['min_buys_m15']}"))
    if liq and vol / liq > R["max_vol24_to_liq"]:
        fails.append(("vol/liq wash", (f"vol/liq {vol/liq:.0f}x" if vol/liq < 1000 else "vol/liq >999x") + f" > {R['max_vol24_to_liq']}x wash"))
    for w in RULES["drop_if_sells_gt_buys_in"]:
        t = tx.get(w) or {}
        if (t.get("sells") or 0) > (t.get("buys") or 0):
            fails.append((f"sells > buys {w}", f"sells > buys {w} ({t.get('sells')} vs {t.get('buys')})"))
    if entry_rules.ENTRY_RULES_ONLY:   # USER ORDER 2026-10-24 13:57: only hard data / unbuyable checks stay at scan level; the six rules decide in meme.py / newpairs.py
        fails = [(k, t) for k, t in fails if k in ("curve complete", "mcap missing", "quote not SOL")]
        if not num(a.get("base_token_price_usd")): fails.append(("price n/a", "price n/a (no data -> no buy)"))
    why = [t for _, t in fails]
    b1 = (tx.get("h1") or {}).get("buyers") or 0; b6 = (tx.get("h6") or {}).get("buyers") or 0
    base = max(1.0, b6 / min(6.0, max(age_h, 1.0)))            # avg hourly unique buyers over last <=6h
    buyer_growth = math.log((b1 + 1) / (base + 1))
    price_growth = math.log(max(0.01, 1 + (num(pc.get("h1")) or 0) / 100))
    c = {"pool": a["address"], "name": a.get("name"), "venue": venue, "dex": dex,
         "base_token": rel.get("base_token", {}).get("data", {}).get("id", "").replace("solana_", ""),
         "age_h": round(age_h, 2), "liquidity_usd": round(liq, 2), "liq_derived": liq_derived, "gt_reserve_usd": gt_liq,
         "curve": curve, "vol_h24": round(vol, 2),
         "vol_h6": num((a.get("volume_usd") or {}).get("h6")), "mcap_usd": mcap,
         "vol_h1": num((a.get("volume_usd") or {}).get("h1")), "tx_m5": tx.get("m5") if tx.get("m5") else None,   # USER ORDER 2026-10-24 13:34: order rules 2 + 4
         "price_usd": num(a.get("base_token_price_usd")), "sol_usd": num(a.get("quote_token_price_usd")),
         "tx_m15": tx.get("m15"), "tx_h1": tx.get("h1"), "pc_h1": num(pc.get("h1")),
         "pc_m5": num(pc.get("m5")), "pc_m15": num(pc.get("m15")), "pc_m30": num(pc.get("m30")),
         "src": p.get("_src") or ["geckoterminal"],
         "buyers_h1": b1, "buyers_h6": b6, "score": round(buyer_growth - price_growth, 4),
         "url": f"https://www.geckoterminal.com/solana/pools/{a['address']}", "m15_na": m15_na or None,
         "data": ("dexscreener+gt" if p.get("_gt_enriched") else "dexscreener") if p.get("_ds") else "geckoterminal",
         "fail_keys": [k for k, _ in fails], "fails": why,
         "fp": json.dumps([tx.get("m15"), tx.get("h1"), mcap], sort_keys=True, default=str)}
    return c, why

SCAN_BUDGET_S = 40       # 1-min cadence: stop issuing GT calls after 40s so a run ends well before the next one

def gecko_pools():
    import time
    pools, calls, errs = {}, 0, []; deadline = time.time() + SCAN_BUDGET_S
    reqs = [("/networks/solana/dexes/pump-fun/pools", {"page": 1, "sort": "h24_tx_count_desc"}),
            ("/networks/solana/dexes/pump-fun/pools", {"page": 2, "sort": "h24_tx_count_desc"}),
            ("/networks/solana/dexes/pumpswap/pools", {"page": 1, "sort": "h24_volume_usd_desc"}),
            ("/networks/solana/dexes/pumpswap/pools", {"page": 2, "sort": "h24_volume_usd_desc"}),
            ("/networks/solana/new_pools", {"page": 1}), ("/networks/solana/new_pools", {"page": 2})]
    # 2026-10-20 14:5x: 6 list calls (was 8: new_pools p3/p4 dropped) + <= 1 /pools/multi call for extra sources
    # (sources.py) + <= 1 OHLCV call in Judge (dip check) = <= 8 per run (limiter 9 / rolling 60 s)
    for path, params in reqs:
        try:
            d = gt.get(path, params, deadline=deadline); calls += 1
            for p in d.get("data") or []: pools[p["id"]] = p
        except Exception as e:
            errs.append(f"{path} p{params.get('page')}: {e}")
    return pools, calls, errs, deadline

def dexscreener_fallback():
    """Map DexScreener pairs (pumpfun/pumpswap on solana) into GT-like dicts."""
    out = {}
    for q in ("pumpswap", "pump.fun"):
        r = requests.get("https://api.dexscreener.com/latest/dex/search", params={"q": q}, timeout=20); r.raise_for_status()
        for p in r.json().get("pairs") or []:
            if p.get("chainId") != "solana" or p.get("dexId") not in ("pumpswap", "pumpfun"): continue
            tx = {w: {"buys": (p.get("txns") or {}).get(k, {}).get("buys"), "sells": (p.get("txns") or {}).get(k, {}).get("sells"),
                      "buyers": None} for w, k in (("m15", "m5"), ("h1", "h1"), ("h6", "h6"), ("h24", "h24"))}
            out[p["pairAddress"]] = {"attributes": {
                "address": p["pairAddress"], "name": f"{p['baseToken']['symbol']} / {p['quoteToken']['symbol']}",
                "pool_created_at": dt.datetime.fromtimestamp(p.get("pairCreatedAt", 0) / 1000, UTC).isoformat(),
                "reserve_in_usd": (p.get("liquidity") or {}).get("usd"), "volume_usd": p.get("volume") or {},
                "market_cap_usd": p.get("marketCap"), "fdv_usd": p.get("fdv"), "base_token_price_usd": p.get("priceUsd"),
                "transactions": tx, "price_change_percentage": p.get("priceChange") or {}},
                "relationships": {"dex": {"data": {"id": "pumpswap" if p["dexId"] == "pumpswap" else "pump-fun"}},
                                  "base_token": {"data": {"id": p["baseToken"]["address"]}}}}
    return out

# 2026-10-20 19:5x (upgrade 3): compact rejects. The daily file hit its 40 MB cap at ~15:00 (60 full rejects x ~0.9 kB per
# 1-min run = ~54 kB/run) and per-coin details stopped. Now: 25 rejects/run (what the dashboard shows), compact fields
# (url/curve/gt_reserve dropped: url is derived from pool), compact JSON -> ~10 kB/run, ~15 MB/day. If a day still reaches
# REJECT_FILE_MAX the file is ROTATED (gzip -> rejects-DATE.partN.jsonl.gz) and a fresh one started, so details never stop.
REJECT_KEEP = 20          # dashboard shows <= 25
REJECT_FILE_MAX = 40_000_000   # expected ~15 kB/run x 1440 = ~22 MB/day; rotation is only the safety net
REJECT_DAYS = 14          # daily files (and their .gz parts) older than this are deleted

def _r(x, n=2):
    return round(x, n) if isinstance(x, float) else x

def _tx(t):
    return {k: t.get(k) for k in ("buys", "sells", "buyers") if t.get(k) is not None} if isinstance(t, dict) else t

def _slim(c, full=True):
    d = {"lead": lead_id(c.get("base_token")), "pool": c.get("pool"), "name": c.get("name"), "venue": c.get("venue"), "base_token": c.get("base_token") if full else None, "age_h": c.get("age_h"),
         "liquidity_usd": _r(c.get("liquidity_usd"), 0), "liq_derived": c.get("liq_derived") or None, "vol_h24": _r(c.get("vol_h24"), 0), "vol_h1": _r(c.get("vol_h1"), 0),
         "mcap_usd": _r(c.get("mcap_usd"), 0), "tx_m15": _tx(c.get("tx_m15")), "tx_h1": _tx(c.get("tx_h1")), "pc_h1": _r(c.get("pc_h1"), 1),
         "pc_m5": _r(c.get("pc_m5"), 1) if full else None, "score": c.get("score") if full else None, "fails": c.get("fails"), "src": c.get("src") if full else None}
    if c.get("wallet"): d["wallet"] = {k: c["wallet"].get(k) for k in ("n", "of", "wallets")}
    return {k: v for k, v in d.items() if v is not None}

def _rotate(path):
    """gzip the full daily file to rejects-DATE.partN.jsonl.gz and start a new one (never drops per-coin details)."""
    import gzip, shutil
    base = path[:-len(".jsonl")]; n = 1
    while os.path.exists(f"{base}.part{n}.jsonl.gz"): n += 1
    tmp = f"{base}.rot{n}"; os.replace(path, tmp)
    with open(tmp, "rb") as fi, gzip.open(f"{base}.part{n}.jsonl.gz", "wb", compresslevel=5) as fo: shutil.copyfileobj(fi, fo)
    os.remove(tmp)

def persist_rejects(out, rejects):
    day = dt.datetime.now(BER).date()
    path = f"{DESK}/scan/rejects-{day.isoformat()}.jsonl"
    if os.path.exists(path) and os.path.getsize(path) >= REJECT_FILE_MAX:
        try: _rotate(path)
        except Exception as e: out.setdefault("errors", []).append(f"rejects rotate: {e}")
    rec = {"type": "scan", "run_id": out["run_id"], "scanned_at": out["scanned_at"], "source": out["source"],
           "pools_seen": out["pools_seen"], "passed": len(out["candidates"]), "rejected_total": len(rejects),
           "sources": out.get("sources"), "cooldown_active": out.get("cooldown_active"), "cooldown_rejected": out.get("cooldown_rejected"),
           "watchlist_size": out.get("watchlist_size"), "gt_calls": out.get("gt_calls"), "errors": out.get("errors"),
           "by_reason": out["rejected_by_reason"], "venue_stats": out["venue_stats"],
           "bonding_curve_liq_derived": out["bonding_curve_liq_derived"], "by_first_reason": out["rejected_by_first_rule"],
           "rejects": [_slim(c, False) for c in rejects[:REJECT_KEEP]], "truncated": False,
           "passed_candidates": [_slim(c, False) for c in out["candidates"]]}
    with open(path, "a") as f: f.write(json.dumps(rec, default=str, separators=(",", ":")) + "\n")
    for old in glob.glob(f"{DESK}/scan/rejects-*") + glob.glob(f"{DESK}/scan/2*.json"):
        try:
            d = dt.date.fromisoformat(os.path.basename(old)[8:18] if "rejects-" in old else os.path.basename(old)[:10])
            if (day - d).days > REJECT_DAYS: os.remove(old)
        except ValueError: pass

def record_judge(run_id, decisions):
    """decisions: list of {pool, name, venue, decision: PICK|DECLINED, reason}"""
    path = f"{DESK}/scan/rejects-{dt.datetime.now(BER).date().isoformat()}.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps({"type": "judge", "run_id": run_id, "at": dt.datetime.now(BER).isoformat(timespec="seconds"),
                            "decisions": [{k: v for k, v in d.items() if v is not None and k not in ("score", "src", "venue")} for d in decisions]}, default=str, separators=(",", ":")) + "\n")

# 2026-10-22 USER ORDER (Dominic 14:53): DexScreener is the primary scan data source; GeckoTerminal only for the fields
# DexScreener lacks (txns m15, unique buyers, price change m15/m30: <= 1 /pools/multi call for pools that already pass every
# other gate) and as full fallback when DexScreener returns nothing. DESK_SCAN_SOURCE=geckoterminal = old path (parity/rollback).
SCAN_SOURCE = os.environ.get("DESK_SCAN_SOURCE", "dexscreener")
ENRICH_KEYS = {f"buys m15 < {RULES['min_buys_m15']}"}   # fail keys that depend only on GT-only fields

def ds_collect(now, wl, deadline):
    """Returns (pools, gt_calls, errs, src_stats) with DexScreener-mapped pools (+ GT overlay on the gate-passers)."""
    import sources
    watch = {k: v.get("mint") for k, v in wl.items()}
    pools, pf_only, st, errs = sources.ds_universe(watch, min(deadline, time.time() + 25))
    sols = sorted(num(p["attributes"].get("quote_token_price_usd")) for p in pools.values() if (num(p["attributes"].get("quote_token_price_usd")) or 0) > 1)
    SOL_FALLBACK[0] = sols[len(sols) // 2] if sols else None
    cool = cooldown_active(now); pre = []
    for p in pools.values():   # first pass on DexScreener fields: who passes every gate except the GT-only ones?
        c, why = evaluate(p, now)
        if c is None or not set(c["fail_keys"]) <= ENRICH_KEYS: continue
        if cool.get(c["base_token"]) or cool.get(c["pool"]): continue
        pre.append((c["pool"] in wl, "wallet" in (p.get("_src") or []), (c["tx_h1"] or {}).get("buys") or 0, c["pool"]))
    pre.sort(reverse=True)
    want = [x[3] for x in pre] + [a for a in pf_only if a not in {x[3] for x in pre}]
    g, calls, ge = sources.gt_enrich(want, deadline); errs += ge
    by_addr = {p["attributes"]["address"]: p for p in pools.values()}
    n_ov = n_pf = 0
    for addr, gp in g.items():
        if addr in by_addr: sources.gt_overlay(by_addr[addr], gp); n_ov += 1
        elif addr in pf_only:
            gp["_src"] = pf_only[addr][1]; pools[gp["id"]] = gp; n_pf += 1
    st.update({"gt_enrich_wanted": len(pre), "gt_enrich_pf_only_wanted": len(want) - len(pre), "gt_enrich_requested": min(len(want), sources.GT_ENRICH_MAX),
               "gt_enriched": n_ov, "gt_pf_only_added": n_pf, "gt_enrich_calls": calls})
    return pools, calls, errs, st

def gecko_collect(wl):
    """Old path (until 2026-10-22): 6 GeckoTerminal list calls + pump.fun/DexScreener extras enriched by GT /pools/multi."""
    pools, calls, errs, deadline = gecko_pools(); source = "geckoterminal"
    gt_n = len(pools); src_stats = {"geckoterminal_pools": gt_n}
    def mint_of(p): return ((p.get("relationships") or {}).get("base_token", {}).get("data") or {}).get("id", "").replace("solana_", "")
    try:
        import sources
        known = {mint_of(p) for p in pools.values()}
        have = {p["attributes"]["address"] for p in pools.values()}
        watch = {k: v.get("mint") for k, v in wl.items() if k not in have}
        xp, xs, xe, xc = sources.extra_pools(known, watch, min(deadline, time.time() + 25))
        calls += xc; errs += [f"extra {e}" for e in xe]; src_stats.update(xs)
        for k, p in xp.items(): pools.setdefault(k, p)
        src_stats["extra_pools_added"] = len(pools) - gt_n
        if len(pools) > gt_n: source = "geckoterminal + pump.fun/dexscreener extras"
    except Exception as e:
        errs.append(f"extra sources: {type(e).__name__} {str(e)[:80]}")
    if not pools:
        try: pools = dexscreener_fallback(); source = "dexscreener (fallback)"
        except Exception as e: errs.append(f"dexscreener: {e}")
    return pools, calls, errs, src_stats, source, gt_n

def scan(dry=False, source=None):
    """dry=True: evaluate only (no reject/scan files, no fingerprint update, no meme.log line)."""
    os.makedirs(f"{DESK}/scan", exist_ok=True)
    try: _fpd = json.load(open(FP_FILE))
    except (FileNotFoundError, ValueError): _fpd = {}
    prev_fp = _fpd.get("fp", {}); prev_n = _fpd.get("streak", {})   # streak = consecutive scans with this exact fingerprint
    new_fp, new_n = {}, {}
    now = dt.datetime.now(UTC)
    wl = watchlist_active(now); src_mode = source or SCAN_SOURCE; pools, calls, errs, src_stats = {}, 0, [], {}
    if src_mode == "dexscreener":
        try: pools, calls, errs, src_stats = ds_collect(now, wl, time.time() + SCAN_BUDGET_S)
        except Exception as e: errs.append(f"dexscreener scan: {type(e).__name__} {str(e)[:80]}")
        source = "dexscreener (+GT m15/buyers)"; gt_n = 0; src_stats["dexscreener_pools"] = len(pools)
        if not pools: src_mode = "geckoterminal"; src_stats["ds_failed_fallback_gt"] = True   # DexScreener down -> old path
    if src_mode != "dexscreener":
        p_, c_, e_, s_, source, gt_n = gecko_collect(wl)
        pools, calls, errs = p_, calls + c_, errs + e_; src_stats.update(s_)
    sols = sorted(num(p["attributes"].get("quote_token_price_usd")) for p in pools.values()
                  if (num(p["attributes"].get("quote_token_price_usd")) or 0) > 1)
    SOL_FALLBACK[0] = sols[len(sols) // 2] if sols else None
    cool = cooldown_active(now); n_cool = 0
    n_derived = [0]; venue_stats = {}
    cands, rej, rejects, by_reason = [], {}, [], {}
    for p in pools.values():
        c, why = evaluate(p, now)
        if c is None: continue
        new_fp[c["pool"]] = c["fp"]
        new_n[c["pool"]] = (prev_n.get(c["pool"], 1) + 1) if prev_fp.get(c["pool"]) == c["fp"] else 1
        if new_n[c["pool"]] >= RULES["stale_scans"]:   # identical txns + mcap in this scan and the previous 2 -> data frozen
            c["fail_keys"].append("stale data")
            c["fails"].append(f"stale data: txns m15/h1 + mcap unchanged for {new_n[c['pool']]} consecutive scans"); why = c["fails"]
        cd = cool.get(c["base_token"]) or cool.get(c["pool"])
        if cd:   # 24h cooldown after a stop-out / losing close (user-approved 2026-10-20)
            n_cool += 1; c["fail_keys"].insert(0, "cooldown")
            c["fails"].insert(0, f"cooldown: {cd['reason'][:60]} -> no re-entry until {dt.datetime.fromisoformat(cd['until']).astimezone(BER):%m-%d %H:%M}"); why = c["fails"]
        c["lead"] = lead_id(c.get("base_token"))
        if c["pool"] in wl: c["watch"] = wl[c["pool"]]
        if c.get("liq_derived"): n_derived[0] += 1
        vs = venue_stats.setdefault(c["venue"], {"evaluated": 0, "passed": 0, "rejected": 0, "gt_liq_zero_or_null": 0,
                                                  "gt_zero_now_pass_liq": 0, "fail_liq_derived": 0})
        vs["evaluated"] += 1; vs["passed" if not why else "rejected"] += 1
        if not c.get("gt_reserve_usd"):
            vs["gt_liq_zero_or_null"] += 1
            if not any(k.startswith("liquidity") for k in c["fail_keys"]): vs["gt_zero_now_pass_liq"] += 1
        if c.get("liq_derived") and any(k.startswith("liquidity") for k in c["fail_keys"]): vs["fail_liq_derived"] += 1
        if why:
            k = c["fail_keys"][0]; rej[k] = rej.get(k, 0) + 1
            for fk in c["fail_keys"]: by_reason[fk] = by_reason.get(fk, 0) + 1
            rejects.append(c)
        else: cands.append(c)
    # 2026-10-20 wallet signal: annotate + rank boost ONLY (1 vetted wallet bought in 6 h -> above non-signal coins,
    # 2+ wallets -> higher). Gates above/in Judge are untouched; a signalled coin that fails any gate stays rejected.
    try:
        import sources; _ws = sources.load_wallet_signal()
    except Exception: _ws = {}
    _wsm = _ws.get("mints", {}); src_stats["wallet_signal_mints"] = len(_wsm); n_ws = 0
    for c in cands + rejects:
        e = _wsm.get(c["base_token"])
        if e:
            n_ws += 1
            c["wallet"] = {"n": len(e["wallets"]), "of": _ws.get("of"), "wallets": [_ws.get("tags", {}).get(w, w[:4]) for w in e["wallets"]],
                           "first_buy_ts": e["first_buy_ts"], "sol": e["sol"]}
            if "wallet" not in (c.get("src") or []): c["src"] = list(c.get("src") or []) + ["wallet"]
    src_stats["wallet_signal_matched"] = n_ws
    rejects.sort(key=lambda c: (len(c["fails"]), -(c["vol_h24"] or 0)))
    cands.sort(key=lambda c: (bool(c.get("watch")), min(2, (c.get("wallet") or {}).get("n", 0)), c["score"]), reverse=True)   # watchlisted first, then wallet signal (2+ > 1 > 0), then score
    seen_m, dd = set(), []
    for c in cands:   # one pool per mint
        if c["base_token"] in seen_m: continue
        seen_m.add(c["base_token"]); dd.append(c)
    cands = dd[:RULES["max_out"] if entry_rules.ENTRY_RULES_ONLY else RULES["max_out_legacy"]]
    out = {"scanned_at": now.astimezone(BER).isoformat(timespec="seconds"), "network": "solana", "source": source,
           "pump_fun_frontend_api": "frontend-api-v3 feeds used as extra candidate source (sources.py)", "gt_calls": calls, "pools_seen": len(pools),
           "rejected_by_first_rule": rej, "rejected_by_reason": by_reason, "rejected_total": len(rejects),
           "bonding_curve_liq_derived": n_derived[0], "venue_stats": venue_stats, "errors": errs, "rules": RULES, "candidates": cands,
           "sources": src_stats, "cooldown_active": len({v["name"] for v in cool.values()}), "cooldown_rejected": n_cool,
           "watchlist_size": len(wl)}
    out["run_id"] = f"{now.astimezone(BER):%Y%m%dT%H%M%S}"
    # shadow book (meme.py): exactly one SCAN filter failed. A pool whose only "failure" is missing GT m15 data (not enriched)
    # is NOT a real one-gate miss -> excluded (2026-10-22 DexScreener data source)
    single = [c for c in rejects if len(c["fail_keys"]) == 1 and not c.get("m15_na")]
    if dry:
        out["single_fail"] = single
        print(f"[SCAN-DRY] {source}: {len(pools)} pools (" + (f"DexScreener {src_stats.get('ds_pairs')}, GT-enriched {src_stats.get('gt_enriched')} + pf-only {src_stats.get('gt_pf_only_added')}" if gt_n == 0 and src_stats.get("dexscreener_pools") else f"GT lists {gt_n} + extra {len(pools)-gt_n}") + f"; {calls} GT calls), {len(cands)} passed, cooldown-rejected {n_cool}, watchlist {len(wl)} | {src_stats} | errors {errs}", file=sys.stderr); return out
    if pools:
        tmp = FP_FILE + ".tmp"; json.dump({"at": out["scanned_at"], "fp": new_fp, "streak": new_n}, open(tmp, "w")); os.replace(tmp, FP_FILE)
    persist_rejects(out, rejects)
    with open(f"{DESK}/scan/{now.astimezone(BER):%Y-%m-%d_%H%M}.json", "w") as fh: json.dump(out, fh, indent=1)
    out["single_fail"] = single   # in-memory only (not written to the scan file)
    log(f"[SCAN] {source}: {len(pools)} pump.fun/PumpSwap pools seen (" + (f"DexScreener {src_stats.get('ds_pairs')}, GT-enriched {src_stats.get('gt_enriched')} + pf-only {src_stats.get('gt_pf_only_added')}" if gt_n == 0 and src_stats.get("dexscreener_pools") else f"GT lists {gt_n} + extra {len(pools)-gt_n}") + f"; {calls} GT calls), {len(cands)} passed, cooldown {n_cool}, watchlist {len(wl)}" +
        ("" if not cands else " | top: " + ", ".join(f"{c['name']} [{c['venue']}] score {c['score']:+.2f}" + (f" Wallet: {c['wallet']['n']} of {c['wallet']['of']}" if c.get("wallet") else "") for c in cands[:3])) +
        (f" | errors: {len(errs)}" if errs else ""))
    return out

if __name__ == "__main__":
    print(json.dumps(scan(), indent=1, default=str))
