"""Extra candidate sources for SCAN (keyless, public). 2026-10-20 (user-approved universe widening).
  * pump.fun frontend-api-v3 (reachable again 2026-10-20):  /coins/currently-live, /coins?sort=last_trade_timestamp (2 pages),
    /coins?sort=market_cap&complete=false (bonding-curve leaders)
  * DexScreener: /token-profiles/latest/v1, /token-boosts/latest/v1, /token-boosts/top/v1 (60 req/min each),
    /latest/dex/search?q=pumpswap|pumpfun and /tokens/v1/solana/<<=30 mints> (300 req/min)
Every extra mint is resolved to ONE pump.fun/PumpSwap SOL pool (dedup by mint, GT-known mints skipped), cheaply prefiltered on
source data (age/mcap/activity), ranked by DexScreener h1 buys, then the top EXTRA_MAX pools are fetched from GeckoTerminal
/pools/multi (<= 2 calls, shared 9/min limiter) so they carry exactly the same fields (unique buyers, m15 txns) and go
through the SAME scan.evaluate() gates + Judge + RugCheck as GeckoTerminal-listed pools. No source is trusted on its own."""
import os, json, time, datetime as dt, requests
from concurrent.futures import ThreadPoolExecutor
import gt
UA = {"User-Agent": "Mozilla/5.0 (desk-meme/1.0)", "Accept": "application/json"}
WSOL = "So11111111111111111111111111111111111111112"; NATIVE = "11111111111111111111111111111111"
PF = "https://frontend-api-v3.pump.fun"; DS = "https://api.dexscreener.com"
PF_FEEDS = {"pf_live": (PF + "/coins/currently-live", {"limit": 50, "offset": 0, "includeNsfw": "false"}),
            "pf_active": (PF + "/coins", {"offset": 0, "limit": 50, "sort": "last_trade_timestamp", "order": "DESC", "includeNsfw": "false"}),
            "pf_active2": (PF + "/coins", {"offset": 50, "limit": 50, "sort": "last_trade_timestamp", "order": "DESC", "includeNsfw": "false"}),
            "pf_curve_top": (PF + "/coins", {"offset": 0, "limit": 50, "sort": "market_cap", "order": "DESC", "complete": "false", "includeNsfw": "false"})}
DS_FEEDS = {"ds_profiles": (DS + "/token-profiles/latest/v1", None), "ds_boosts": (DS + "/token-boosts/latest/v1", None),
            "ds_boosts_top": (DS + "/token-boosts/top/v1", None)}
DS_SEARCH = ("pumpswap", "pumpfun")
TIMEOUT = 6            # per HTTP call
EXTRA_MAX = 30         # extra pools per scan sent to GT /pools/multi (1 GT call; 2 calls pushed runs to 9/9 budget -> 28 s limiter waits)
DS_TOKEN_CALLS_MAX = 6 # /tokens/v1 batches (30 mints each) per scan
AGE_H = (0.25, 72.0); MCAP = (15_000 * 0.9, 8_000_000 * 1.1)   # loose prefilter (exact gates run later in scan.evaluate)

WALLET_SIGNAL = os.path.expanduser("~/.desk/scan/wallet_signal.json"); WALLET_SIGNAL_MAX_AGE_S = 600

def load_wallet_signal():
    """{} if missing or older than 10 min (stale signal is ignored, never trusted)."""
    try:
        d = json.load(open(WALLET_SIGNAL))
        return d if time.time() - d.get("updated_ts", 0) <= WALLET_SIGNAL_MAX_AGE_S else {}
    except (FileNotFoundError, ValueError): return {}

def _get(url, params=None):
    r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT); r.raise_for_status(); return r.json()

def _age_h(ms, now):
    try: return (now - ms / 1000) / 3600
    except TypeError: return None

def extra_pools(known_mints, watch, deadline):
    """known_mints: mints already in the GT lists. watch: {pool: mint} watchlisted pools that must be refreshed.
    Returns (gt_pools {id: pool}, stats, errs, gt_calls)."""
    now = time.time(); errs = []; stats = {}
    mints = {}       # mint -> {"src": set(), "pool": addr or None, "venue_hint": ..., "rank": h1 buys}
    def add(m, src, **kw):
        if not m or m in known_mints: return
        e = mints.setdefault(m, {"src": set(), "pool": None, "rank": -1}); e["src"].add(src)
        for k, v in kw.items():
            if v is not None and (k != "pool" or e["pool"] is None): e[k] = v
    jobs = {**{k: (u, p) for k, (u, p) in PF_FEEDS.items()}, **{k: (u, p) for k, (u, p) in DS_FEEDS.items()},
            **{f"ds_search_{q}": (DS + "/latest/dex/search", {"q": q}) for q in DS_SEARCH}}
    with ThreadPoolExecutor(8) as ex:
        fut = {k: ex.submit(_get, u, p) for k, (u, p) in jobs.items()}
        res = {}
        for k, f in fut.items():
            try: res[k] = f.result(timeout=max(1, deadline - time.time()))
            except Exception as e: errs.append(f"{k}: {type(e).__name__} {str(e)[:60]}"); res[k] = None
    # 2026-10-20 wallet signal (scan/wallet_signal.py): mints bought in the last 6 h by vetted COPYABLE wallets ->
    # extra candidate source only (same prefilter + GT enrichment + all scan/Judge/RugCheck gates as every other source)
    try:
        _ws = load_wallet_signal()
        for m in _ws.get("mints", {}): add(m, "wallet")
        stats["wallet_signal_mints"] = len(_ws.get("mints", {}))
    except Exception as e: errs.append(f"wallet_signal: {type(e).__name__}")
    ds_pairs = []
    for k, d in res.items():
        if d is None: stats[k] = "error"; continue
        if k.startswith("pf_"):
            n = 0
            for c in d if isinstance(d, list) else []:
                c = c.get("coin", c); n += 1
                if c.get("is_banned") or c.get("quote_mint") not in (None, NATIVE, WSOL): continue
                a = _age_h(c.get("created_timestamp"), now); mc = c.get("usd_market_cap") or c.get("market_cap_usd")
                if a is None or not (AGE_H[0] <= a <= AGE_H[1]) or not mc or not (MCAP[0] <= mc <= MCAP[1]): continue
                if c.get("last_trade_timestamp") and now - c["last_trade_timestamp"] / 1000 > 900: continue   # no trade in 15 min
                pool = (c.get("pump_swap_pool") or c.get("pool_address")) if c.get("complete") else c.get("bonding_curve")
                add(c["mint"], k, pf_pool=pool)
            stats[k] = n
        elif k.startswith("ds_search"):
            ps = d.get("pairs") or []; stats[k] = len(ps); ds_pairs += [(k, p) for p in ps]
        else:
            sol = [x for x in (d if isinstance(d, list) else []) if x.get("chainId") == "solana"]
            stats[k] = len(sol)
            for x in sol: add(x.get("tokenAddress"), k)
    # resolve mints without pair data via DexScreener /tokens/v1 (30 per call)
    need = [m for m in mints if m not in {(p.get("baseToken") or {}).get("address") for _, p in ds_pairs}]
    calls = 0
    for i in range(0, len(need), 30):
        if calls >= DS_TOKEN_CALLS_MAX or time.time() > deadline: errs.append(f"ds_tokens: {len(need) - i} mints unresolved (cap/deadline)"); break
        try: ds_pairs += [("ds_tokens", p) for p in _get(f"{DS}/tokens/v1/solana/" + ",".join(need[i:i + 30])) or []]; calls += 1
        except Exception as e: errs.append(f"ds_tokens: {type(e).__name__}"); break
    stats["ds_token_calls"] = calls
    best = {}   # mint -> pair (prefer PumpSwap if present, else pump.fun curve; highest liquidity)
    for src, p in ds_pairs:
        if p.get("chainId") != "solana" or p.get("dexId") not in ("pumpfun", "pumpswap"): continue
        if (p.get("quoteToken") or {}).get("address") != WSOL: continue
        m = (p.get("baseToken") or {}).get("address")
        if src.startswith("ds_search"): add(m, src)
        if m not in mints: continue
        cur = best.get(m)
        key = (p["dexId"] == "pumpswap", (p.get("liquidity") or {}).get("usd") or 0)
        if not cur or key > (cur["dexId"] == "pumpswap", (cur.get("liquidity") or {}).get("usd") or 0): best[m] = p
    sel, dropped = [], 0
    for m, e in mints.items():
        p = best.get(m)
        if p:
            a = _age_h(p.get("pairCreatedAt"), now); mc = p.get("marketCap") or p.get("fdv") or 0
            tx = (p.get("txns") or {}).get("h1") or {}
            if (a is not None and not (AGE_H[0] <= a <= AGE_H[1])) or not (MCAP[0] <= mc <= MCAP[1]) \
               or (tx.get("buys") or 0) < 10 or (tx.get("sells") or 0) > (tx.get("buys") or 0):
                dropped += 1; continue
            sel.append((tx.get("buys") or 0, p["pairAddress"], m, e["src"]))
        elif e.get("pf_pool"):   # pump.fun coin DexScreener doesn't index yet -> lowest priority, GT decides
            sel.append((0, e["pf_pool"], m, e["src"]))
        else: dropped += 1
    sel.sort(key=lambda x: (-("wallet" in x[3]), -x[0]))   # wallet-signal mints first (ranking/priority only)
    stats.update({"extra_mints": len(mints), "prefilter_dropped": dropped, "prefilter_kept": len(sel)})
    want = list(dict.fromkeys(list(watch) + [s[1] for s in sel]))[:EXTRA_MAX]
    src_of = {s[1]: sorted(s[3]) for s in sel}
    for w in watch: src_of.setdefault(w, []).append("watchlist")
    out, gcalls = {}, 0
    for i in range(0, len(want), 30):
        try:
            d = gt.get("/networks/solana/pools/multi/" + ",".join(want[i:i + 30]), deadline=deadline); gcalls += 1
            for p in d.get("data") or []:
                p["_src"] = src_of.get(p["attributes"]["address"], []); out[p["id"]] = p
        except Exception as e: errs.append(f"gt multi: {type(e).__name__} {str(e)[:60]}"); break
    stats.update({"extra_requested": len(want), "extra_returned": len(out), "extra_gt_calls": gcalls})
    return out, stats, errs, gcalls

# =====================================================================================================================
# 2026-10-22 USER ORDER (Dominic 14:53): DexScreener is the PRIMARY scan data source (GitHub runner IPs get GeckoTerminal
# 429s). Data source / fetching only: filters, risk rules, ticket size and rules 1-8 are untouched; every pool still goes
# through scan.evaluate() + Judge + RugCheck exactly as before.
#   Universe: pump.fun frontend-api-v3 feeds + DexScreener profiles/boosts/ads/takeovers/search -> mints -> DexScreener
#   /tokens/v1 (30 mints per call) -> ONE pump.fun/PumpSwap SOL pair per mint, mapped 1:1 into the GeckoTerminal pool shape
#   (ds_to_gt). Fields WITHOUT an exact DexScreener equivalent stay on GeckoTerminal (gt_overlay, /pools/multi, <= 1 call
#   of 30 pools per scan, only for pools that already pass every other SCAN gate): txns m15 (buys/sells), unique buyers
#   (h1/h6/h24), price change m15/m30. DexScreener only has m5/h1/h6/h24 windows and no unique-buyer counts.
DS_PF_FEEDS = {**PF_FEEDS,
    "pf_active_grad": (PF + "/coins", {"offset": 0, "limit": 50, "sort": "last_trade_timestamp", "order": "DESC", "complete": "true", "includeNsfw": "false"}),
    "pf_active_grad2": (PF + "/coins", {"offset": 50, "limit": 50, "sort": "last_trade_timestamp", "order": "DESC", "complete": "true", "includeNsfw": "false"})}   # 6 pump.fun calls per scan (was 4): pump.fun 429s short bursts, graduated-active pages carry most PumpSwap candidates
DS_DS_FEEDS = {**DS_FEEDS, "ds_ads": (DS + "/ads/latest/v1", None), "ds_cto": (DS + "/community-takeovers/latest/v1", None)}
DS_SEARCH_Q = ("pumpswap", "pumpfun")
DS_TOKENS_MAX = 12      # /tokens/v1 calls per scan (<= 360 mints); limit is ~300/min -> 1-min cadence uses <= 15 (incl. search)
GT_ENRICH_MAX = 30      # pools per scan enriched from GeckoTerminal (= 1 /pools/multi call)
DS_DEX = {"pumpfun": "pump-fun", "pumpswap": "pumpswap"}
GT_ONLY_FIELDS = ("transactions.m15", "transactions.*.buyers", "price_change_percentage.m15", "price_change_percentage.m30",
                  "price_change_percentage.<window> only when DexScreener omits it")

def ds_to_gt(p, src=()):
    """One DexScreener pair -> GeckoTerminal pool dict (same keys scan.evaluate reads). Fields DexScreener does not have
    are left OUT (not zero) so evaluate/Judge see them as missing: txns m15, unique buyers, price change m15/m30."""
    num = lambda x: float(x) if x not in (None, "") else None
    px, pn = num(p.get("priceUsd")), num(p.get("priceNative"))
    tx = p.get("txns") or {}; v = p.get("volume") or {}; pc = p.get("priceChange") or {}
    base, quote = p.get("baseToken") or {}, p.get("quoteToken") or {}
    return {"id": "solana_" + p["pairAddress"], "type": "pool", "_src": list(src), "_ds": True,
            "attributes": {
                "address": p["pairAddress"], "name": f"{base.get('symbol')} / {quote.get('symbol')}",
                "pool_created_at": dt.datetime.fromtimestamp(p["pairCreatedAt"] / 1000, dt.timezone.utc).isoformat() if p.get("pairCreatedAt") else None,
                "reserve_in_usd": (p.get("liquidity") or {}).get("usd"),
                "volume_usd": {w: v.get(w) for w in ("m5", "h1", "h6", "h24") if v.get(w) is not None},
                "market_cap_usd": p.get("marketCap"), "fdv_usd": p.get("fdv"),
                "base_token_price_usd": px, "quote_token_price_usd": (px / pn) if px and pn else None,
                "transactions": {w: {"buys": (tx.get(w) or {}).get("buys"), "sells": (tx.get(w) or {}).get("sells")}
                                 for w in ("m5", "h1", "h6", "h24") if tx.get(w) is not None},
                "price_change_percentage": {w: pc.get(w) for w in ("m5", "h1", "h6", "h24") if pc.get(w) is not None}},
            "relationships": {"dex": {"data": {"id": DS_DEX.get(p.get("dexId"), p.get("dexId"))}},
                              "base_token": {"data": {"id": "solana_" + (base.get("address") or "")}},
                              "quote_token": {"data": {"id": "solana_" + (quote.get("address") or "")}}}}

def gt_overlay(pool, gtp):
    """Copy ONLY the GeckoTerminal-only fields (GT_ONLY_FIELDS) from GT pool gtp into DexScreener-mapped pool (in place)."""
    a, g = pool["attributes"], (gtp or {}).get("attributes") or {}
    gtx = g.get("transactions") or {}; tx = a.setdefault("transactions", {})
    if gtx.get("m15") is not None: tx["m15"] = dict(gtx["m15"])
    for w in ("h1", "h6", "h24"):
        if (gtx.get(w) or {}).get("buyers") is not None: tx.setdefault(w, {})["buyers"] = gtx[w]["buyers"]
    gpc = g.get("price_change_percentage") or {}; pc = a.setdefault("price_change_percentage", {})
    for w in ("m15", "m30"):
        if gpc.get(w) is not None: pc[w] = gpc[w]
    for w in ("m5", "h1", "h6", "h24"):   # DexScreener omits a window's price change when it has no value -> GT fallback
        if pc.get(w) is None and gpc.get(w) is not None: pc[w] = gpc[w]
    pool["_gt_enriched"] = True
    return pool

def ds_universe(watch, deadline):
    """watch: {pool: mint} watchlisted pools. Returns (pools {id: GT-shaped pool}, pf_only {pool: (mint, src)}, stats, errs).
    pf_only = pump.fun coins DexScreener does not index yet (GeckoTerminal decides them, lowest priority)."""
    now = time.time(); errs = []; stats = {}; mints = {}
    def add(m, src, pf_pool=None):
        if not m: return
        e = mints.setdefault(m, {"src": set(), "pf_pool": None}); e["src"].add(src)
        if pf_pool and not e["pf_pool"]: e["pf_pool"] = pf_pool
    jobs = {**DS_PF_FEEDS, **DS_DS_FEEDS, **{f"ds_search_{q.replace('.', '')}": (DS + "/latest/dex/search", {"q": q}) for q in DS_SEARCH_Q}}
    with ThreadPoolExecutor(8) as ex:
        fut = {k: ex.submit(_get, u, p) for k, (u, p) in jobs.items()}; res = {}
        for k, f in fut.items():
            try: res[k] = f.result(timeout=max(1, deadline - time.time()))
            except Exception as e: errs.append(f"{k}: {type(e).__name__} {str(e)[:60]}"); res[k] = None
    try:
        _ws = load_wallet_signal()
        for m in _ws.get("mints", {}): add(m, "wallet")
        stats["wallet_signal_mints"] = len(_ws.get("mints", {}))
    except Exception as e: errs.append(f"wallet_signal: {type(e).__name__}")
    for pool, m in watch.items(): add(m, "watchlist")
    pairs = []
    for k, d in res.items():
        if d is None: stats[k] = "error"; continue
        if k.startswith("pf_"):
            n = 0
            for c in d if isinstance(d, list) else []:
                c = c.get("coin", c); n += 1
                if c.get("is_banned") or c.get("quote_mint") not in (None, NATIVE, WSOL): continue
                a = _age_h(c.get("created_timestamp"), now); mc = c.get("usd_market_cap") or c.get("market_cap_usd")
                if a is None or not (AGE_H[0] <= a <= AGE_H[1]) or not mc or not (MCAP[0] <= mc <= MCAP[1]): continue   # same loose prefilter as extra_pools
                if c.get("last_trade_timestamp") and now - c["last_trade_timestamp"] / 1000 > 900: continue   # no trade in 15 min
                pool = (c.get("pump_swap_pool") or c.get("pool_address")) if c.get("complete") else c.get("bonding_curve")
                add(c.get("mint"), k, pool)
            stats[k] = n
        elif k.startswith("ds_search"):
            ps = d.get("pairs") or []; stats[k] = len(ps); pairs += [(k, p) for p in ps]
            for p in ps:
                if p.get("chainId") == "solana" and p.get("dexId") in DS_DEX: add((p.get("baseToken") or {}).get("address"), k)
        else:
            sol = [x for x in (d if isinstance(d, list) else []) if x.get("chainId") == "solana"]; stats[k] = len(sol)
            for x in sol: add(x.get("tokenAddress"), k)
    have = {(p.get("baseToken") or {}).get("address") for _, p in pairs}
    need = [m for m in mints if m not in have]; calls = 0
    for i in range(0, len(need), 30):
        if calls >= DS_TOKENS_MAX or time.time() > deadline: errs.append(f"ds_tokens: {len(need) - i} mints unresolved (cap/deadline)"); break
        try: pairs += [("ds_tokens", p) for p in _get(f"{DS}/tokens/v1/solana/" + ",".join(need[i:i + 30])) or []]; calls += 1
        except Exception as e: errs.append(f"ds_tokens: {type(e).__name__} {str(e)[:60]}"); break
    stats["ds_token_calls"] = calls; stats["ds_mints"] = len(mints)
    best, watched, nocreated = {}, {}, {}
    for _, p in pairs:
        if p.get("chainId") != "solana" or p.get("dexId") not in DS_DEX or (p.get("quoteToken") or {}).get("address") != WSOL: continue
        m = (p.get("baseToken") or {}).get("address")
        if m not in mints: continue
        if not p.get("pairCreatedAt"): nocreated.setdefault(m, p["pairAddress"]); continue   # no pair age on DexScreener -> GT decides
        if p.get("pairAddress") in watch: watched[p["pairAddress"]] = (m, p)
        cur = best.get(m); key = (p["dexId"] == "pumpswap", (p.get("liquidity") or {}).get("usd") or 0)
        if not cur or key > (cur["dexId"] == "pumpswap", (cur.get("liquidity") or {}).get("usd") or 0): best[m] = p
    pools = {}
    for m, p in list(best.items()) + [w for w in watched.values()]:
        g = ds_to_gt(p, sorted(mints[m]["src"])); pools[g["id"]] = g
    pf_only = {e["pf_pool"]: (m, sorted(e["src"])) for m, e in mints.items() if m not in best and e.get("pf_pool")}
    for m, a in nocreated.items():
        if m not in best: pf_only.setdefault(a, (m, sorted(mints[m]["src"])))
    stats.update({"ds_pairs": len(pools), "pf_only_unindexed": len(pf_only), "ds_no_created_at": len(nocreated)})
    return pools, pf_only, stats, errs

def gt_enrich(addrs, deadline):
    """GeckoTerminal /pools/multi for <= GT_ENRICH_MAX pool addresses. Returns ({address: gt pool}, calls, errs)."""
    out, calls, errs = {}, 0, []
    for i in range(0, min(len(addrs), GT_ENRICH_MAX), 30):
        try:
            d = gt.get("/networks/solana/pools/multi/" + ",".join(addrs[i:min(i + 30, GT_ENRICH_MAX)]), deadline=deadline); calls += 1
            for p in d.get("data") or []: out[p["attributes"]["address"]] = p
        except Exception as e: errs.append(f"gt enrich: {type(e).__name__} {str(e)[:60]}"); break
    return out, calls, errs
