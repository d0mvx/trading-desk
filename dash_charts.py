"""Chart data for the dashboard's tap-to-expand position cards (2026-10-20 21:4x). DISPLAY ONLY, read-only APIs, no trading.
Meme / NEW PAIRS: pump.fun swap-api candles (1m every 2 min, 1h every 15 min, 24h every 60 min per open coin, <= 4 calls/build,
0 GeckoTerminal calls). Fallback only if pump.fun fails for a coin: GeckoTerminal 1m via ~/.desk/gt.py (shared 9/60 s limiter),
only with >= 2 free slots, <= 1 call per build, per coin every 5 min. Between fetches the chart is extended from the RISK log
marks (1/min, 0 calls) + the position's last price.
Facts (mcap, liquidity, vol 24h, age): DexScreener pairs API, one batched call per build, cached 60 s. Holders: RugCheck cache.
Alpaca: data API bars (IEX for stocks), 5m every 5 min, 1h every 30 min, 1D every 6 h, <= 12 data calls per build (5m first).
Cache: ~/.desk/chart_cache/<key>.json (atomic writes). Times are sent as Berlin wall-clock seconds (the chart lib shows UTC)."""
import os, re, json, time, math, datetime as dt
from zoneinfo import ZoneInfo
DESK = os.path.expanduser("~/.desk"); CACHE = f"{DESK}/chart_cache"; BER = ZoneInfo("Europe/Berlin"); UTC = dt.timezone.utc
GT_MIN_FREE, M1_EVERY, H1_EVERY, GT_ERR_BACKOFF = 3, 180, 1200, 600
DS_EVERY = 60
ALP_EVERY = {"5m": 300, "1h": 1800, "1T": 21600}; ALP_MAX_CALLS = 6
_state = {"gt_calls": 0, "alp_calls": 0, "notes": []}

def _safe(k): return re.sub(r"[^A-Za-z0-9_.-]", "_", k)[:80]
def _load(k):
    try: return json.load(open(f"{CACHE}/{_safe(k)}.json"))
    except Exception: return {}
def _save(k, d):
    os.makedirs(CACHE, exist_ok=True); p = f"{CACHE}/{_safe(k)}.json"; tmp = p + f".{os.getpid()}.tmp"
    json.dump(d, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, p)
def loc(ts):   # epoch UTC -> Berlin wall-clock epoch (DST-correct per point)
    return int(ts + dt.datetime.fromtimestamp(ts, BER).utcoffset().total_seconds())
def _sig(x, n=6): return float(f"{x:.{n}g}") if x else 0.0
def prec_for(p):
    if not p or p <= 0: return 4
    if p >= 100: return 2
    if p >= 1: return 3
    return min(12, max(4, -int(math.floor(math.log10(p))) + 3))

def resample(bars, sec, local_day=False):
    """bars [[t,o,h,l,c,v]] (t = UTC epoch, ascending) -> buckets of `sec` (local Berlin days if local_day)."""
    out = {}
    for t, o, h, l, c, v in bars:
        k = (loc(t) // 86400 * 86400) if local_day else (t // sec * sec)
        if k not in out: out[k] = [k, o, h, l, c, v]
        else:
            b = out[k]; b[2] = max(b[2], h); b[3] = min(b[3], l); b[4] = c; b[5] += v
    return [out[k] for k in sorted(out)]

def _gt_free():
    try:
        calls = [float(x) for x in open(f"{DESK}/.gt_calls").read().split()]
        return 9 - sum(1 for c in calls if time.time() - c < 60)
    except Exception: return 9

def _gt_ohlcv(pool, tf, limit):
    import sys; sys.path.insert(0, DESK); import gt
    path = f"/networks/solana/pools/{pool}/ohlcv/{'minute' if tf == 'm1' else 'hour'}"
    d = gt.get(path, {"aggregate": 1, "limit": int(limit), "currency": "usd"}, deadline=time.time() + 3)
    rows = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    return sorted([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)] for r in rows])

def _risk_marks(lead, since_ts, lines):
    """1/min RISK marks for this lead from meme.log -> [(utc_ts, price)]."""
    out = []
    if not lead: return out
    tag = f"[{lead}]"
    for l in lines:
        if tag not in l or "[RISK]" not in l or " mark " not in l: continue
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", l); mm = re.search(r" mark ([0-9.eE+-]+)", l)
        if not (m and mm): continue
        try:
            ts = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=BER).timestamp()
            if ts >= since_ts - 60: out.append((ts, float(mm.group(1))))
        except ValueError: pass
    return out

def _extend(bars, marks, sec):
    """Append/merge price samples (utc_ts, price) into candles of `sec` seconds after the last fetched candle."""
    bars = [list(b) for b in bars]
    for ts, p in sorted(marks):
        k = int(ts) // sec * sec
        if bars and k < bars[-1][0]: continue
        if bars and bars[-1][0] == k:
            b = bars[-1]; b[2] = max(b[2], p); b[3] = min(b[3], p); b[4] = p
        else:
            o = bars[-1][4] if bars else p
            bars.append([k, o, max(o, p), min(o, p), p, 0.0])
    return bars

def ds_facts(pools):
    """DexScreener facts for pools (one batched call, cached DS_EVERY s)."""
    c = _load("_dexscreener"); now = time.time(); want = [p for p in pools if p]
    if want and (now - c.get("ts", 0) >= DS_EVERY or any(p not in c.get("pairs", {}) for p in want)):
        try:
            import requests
            r = requests.get("https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(want[:30]), timeout=8)
            pairs = {p["pairAddress"]: {"mcap": p.get("marketCap") or p.get("fdv"), "liq": (p.get("liquidity") or {}).get("usd"),
                                        "vol24": (p.get("volume") or {}).get("h24"), "created": (p.get("pairCreatedAt") or 0) / 1000 or None,
                                        "chg": p.get("priceChange") or {}, "tx24": ((p.get("txns") or {}).get("h24") or {}), "dex": p.get("dexId"),
                                        "price": float(p["priceUsd"]) if p.get("priceUsd") else None}
                     for p in (r.json().get("pairs") or [])}
            c = {"ts": now, "pairs": {**c.get("pairs", {}), **pairs}}; _save("_dexscreener", c)
        except Exception as e: _state["notes"].append(f"DexScreener: {type(e).__name__}")
    return c.get("pairs", {})

def holders(mint, pool):
    try:
        r = (json.load(open(f"{DESK}/rugcheck_cache.json")).get(mint) or {}).get("r") or {}
    except Exception: return None
    th = r.get("topHolders") or []
    if not th: return None
    skip = {pool}
    for m in r.get("markets") or []:
        if isinstance(m, dict): skip |= {v for v in m.values() if isinstance(v, str)}
    hs = [h for h in th if h.get("owner") not in skip and h.get("address") not in skip]
    return {"top10_pct": round(sum(float(h.get("pct") or 0) for h in hs[:10]), 1), "largest_pct": round(float(hs[0].get("pct") or 0), 1) if hs else None,
            "n_listed": len(th)}

PF_EVERY = {"m1": 120, "h1": 900, "d1": 3600}; PF_MAX_CALLS = 4; GT_EVERY = 300; GT_MIN_FREE = 2
def _pf_candles(mint, iv, start_ts, limit):
    """pump.fun swap-api candles (USD; works for bonding-curve and PumpSwap coins). Unofficial public endpoint, 0 GT calls."""
    import requests
    r = requests.get(f"https://swap-api.pump.fun/v2/coins/{mint}/candles", params={"interval": iv, "limit": int(limit), "currency": "USD",
                     "createdTs": int(start_ts * 1000)}, headers={"User-Agent": "Mozilla/5.0 (desk-dashboard)", "Accept": "application/json"}, timeout=6)
    r.raise_for_status(); d = r.json()
    if not isinstance(d, list): raise ValueError("unexpected pump.fun response")
    return sorted([[int(x["timestamp"]) // 1000, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x.get("volume") or 0)] for x in d])

def meme_requests(reqs):
    """Refresh cached candles. Primary: pump.fun candles (1m / 1h / 24h, <= PF_MAX_CALLS per build). Fallback (only if pump.fun
    fails for that coin): GeckoTerminal 1m, at most ONE call per build, only with >= GT_MIN_FREE free slots, per coin every GT_EVERY s."""
    now = time.time(); pf_calls = 0; gt_done = False
    for q in sorted(reqs, key=lambda q: (_load(q["key"]).get("m1") or {}).get("ts", 0)):
        o = q["o"]; c = _load(q["key"]); ent = dt.datetime.fromisoformat(o["entry_time"]).timestamp(); changed = False
        mint = o.get("token") or ""
        for tf, iv, start, lim in (("m1", "1m", ent - 3600, min(1000, int((now - ent) / 60) + 62)), ("h1", "1h", now - 14 * 86400, 336), ("d1", "24h", now - 90 * 86400, 90)):
            if pf_calls >= PF_MAX_CALLS or now - (c.get(tf) or {}).get("ts", 0) < PF_EVERY[tf] or now - c.get("pf_err", 0) < GT_ERR_BACKOFF: continue
            try:
                bars = _pf_candles(mint, iv, start, lim); pf_calls += 1; _state["pf_calls"] = _state.get("pf_calls", 0) + 1
                c[tf] = {"ts": now, "src": "pump.fun", "bars": [[t, _sig(a), _sig(b), _sig(cc), _sig(d), round(v, 2)] for t, a, b, cc, d, v in bars]}; changed = True
            except Exception as e:
                pf_calls += 1; c["pf_err"] = now; c["pf_err_msg"] = f"{type(e).__name__}"; changed = True; _state["notes"].append(f"pump.fun {tf} {q['key'][:10]}: {type(e).__name__}")
        pf_bad = now - c.get("pf_err", 0) < GT_ERR_BACKOFF and not (c.get("m1") or {}).get("bars")
        if pf_bad and not gt_done and now - (c.get("m1") or {}).get("ts", 0) >= GT_EVERY and now - c.get("gt_err", 0) >= GT_ERR_BACKOFF and _gt_free() >= GT_MIN_FREE:
            gt_done = True
            try:
                bars = _gt_ohlcv(o["pool"], "m1", min(1000, max(120, int((now - ent) / 60) + 60))); _state["gt_calls"] += 1
                c["m1"] = {"ts": now, "src": "GeckoTerminal", "bars": [[t, _sig(a), _sig(b), _sig(cc), _sig(d), round(v, 2)] for t, a, b, cc, d, v in bars]}
            except Exception as e:
                c["gt_err"] = now; c["gt_err_msg"] = f"{type(e).__name__}: {str(e)[:80]}"; _state["notes"].append(f"GT m1 {q['key'][:10]}: {type(e).__name__}")
            changed = True
        if changed: _save(q["key"], c)

def meme_chart(q, log_lines, facts):
    o = q["o"]; c = _load(q["key"]); now = time.time()
    ent = dt.datetime.fromisoformat(o["entry_time"]).timestamp(); entry = o["entry_price"]; last = o.get("last_price") or entry
    m1 = (c.get("m1") or {}).get("bars") or []; h1 = (c.get("h1") or {}).get("bars") or []
    marks = _risk_marks(q.get("lead"), ent, log_lines)
    try: lc = dt.datetime.fromisoformat(o["last_check"]).timestamp()
    except Exception: lc = now
    marks.append((lc, last))
    m1 = [b for b in m1 if b[0] >= ent - 3600]          # a bit (<= 60 min) before entry .. now
    m1x = _extend(m1, marks, 60)
    if not m1: marks_note = "nur RISK-Kurse (1/min), Kerzen noch nicht geladen"
    else: marks_note = f"{c['m1'].get('src', 'GeckoTerminal')}-Kerzen, geladen vor {int((now - c['m1']['ts']) / 60)} Min · danach RISK-Kurse + letzter Kurs"
    h1x = _extend(h1, marks, 3600) if h1 else []
    d1 = (c.get("d1") or {}).get("bars") or []
    tfs = {"1m": m1x, "5m": resample(m1x, 300) if m1x else [], "1h": h1x or (resample(m1x, 3600) if m1x else []),
           "1T": _extend(d1, marks, 86400) if d1 else (resample(h1x, 86400, True) if h1x else [])}
    f = facts.get(o.get("pool")) or {}
    created = f.get("created")
    return {"kind": "meme", "prec": prec_for(min(entry, last)),
            "tf": {k: [[(loc(b[0]) if k != "1T" else (b[0] if not d1 else loc(b[0]) // 86400 * 86400)), b[1], b[2], b[3], b[4]] for b in v] for k, v in tfs.items() if v},
            "order": ["1m", "5m", "1h", "1T"], "default": "1m" if (now - ent) < 5400 else "5m",
            "entry": {"t": loc(ent), "p": entry}, "lines": q["levels"], "sells": [{"t": loc(s["t"]), "p": s["p"], "txt": s["txt"]} for s in q.get("sells", [])],
            "src": marks_note + (f" · pump.fun-Fehler: {c['pf_err_msg']}" if c.get("pf_err") and now - c["pf_err"] < 3600 else "") + (f" · GT-Fehler: {c['gt_err_msg']}" if c.get("gt_err") and now - c["gt_err"] < 3600 else ""),
            "facts": {"mcap": f.get("mcap"), "liq": f.get("liq"), "vol24": f.get("vol24"), "age_h": ((now - created) / 3600) if created else None,
                      "chg_h1": (f.get("chg") or {}).get("h1"), "chg_h24": (f.get("chg") or {}).get("h24"), "tx24": f.get("tx24"), "dex": f.get("dex"),
                      "holders": holders(o.get("token"), o.get("pool"))},
            "links": {"dex": f'https://dexscreener.com/solana/{o.get("pool")}', "pump": f'https://pump.fun/coin/{o.get("token")}' if o.get("token") else None,
                      "embed": f'https://dexscreener.com/solana/{o.get("pool")}?embed=1&theme=dark&trades=0&info=0', "embed_name": "DexScreener"}}

ALP_KEEP = {"5m": 200, "1h": 150, "1T": 260}; ALP_MAX_CALLS = 12
def _alp_fetch(key, sym, sleeve, entry_ts, tf, api_key, api_secret):
    c = _load(key); now = time.time(); is_c = sleeve == "crypto"
    if now - (c.get(tf) or {}).get("ts", 0) < ALP_EVERY[tf] or _state["alp_calls"] >= ALP_MAX_CALLS: return
    dsym = (sym[:-3] + "/USD") if is_c and "/" not in sym else sym
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    tfo, days = {"5m": (TimeFrame(5, TimeFrameUnit.Minute), 4), "1h": (TimeFrame(1, TimeFrameUnit.Hour), 30), "1T": (TimeFrame(1, TimeFrameUnit.Day), 400)}[tf]
    start = dt.datetime.now(UTC) - dt.timedelta(days=days)
    if entry_ts and tf == "5m": start = min(start, dt.datetime.fromtimestamp(entry_ts - 3 * 3600, UTC))
    try:
        if is_c:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoBarsRequest
            bs = CryptoHistoricalDataClient(api_key, api_secret).get_crypto_bars(CryptoBarsRequest(symbol_or_symbols=dsym, timeframe=tfo, start=start))
        else:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.enums import DataFeed
            bs = StockHistoricalDataClient(api_key, api_secret).get_stock_bars(StockBarsRequest(symbol_or_symbols=dsym, timeframe=tfo, start=start, feed=DataFeed.IEX))
        _state["alp_calls"] += 1
        rows = bs.data.get(dsym) or []
        c[tf] = {"ts": now, "bars": [[int(b.timestamp.timestamp()), _sig(b.open, 5), _sig(b.high, 5), _sig(b.low, 5), _sig(b.close, 5)] for b in rows][-ALP_KEEP[tf]:]}
    except Exception as e:
        _state["alp_calls"] += 1; _state["notes"].append(f"Alpaca bars {sym} {tf}: {type(e).__name__}"); c[tf] = {"ts": now - ALP_EVERY[tf] + 120, "bars": (c.get(tf) or {}).get("bars") or []}
    _save(key, c)

def alp_prefetch(reqs, api_key, api_secret):
    """5m for every position first, then 1h, then 1D (<= ALP_MAX_CALLS data calls per build)."""
    for tf in ("5m", "1h", "1T"):
        for ck, sym, sl, ets, epx in reqs: _alp_fetch(ck, sym, sl, ets, tf, api_key, api_secret)

def alpaca_chart(key, sym, sleeve, entry_ts, entry_px, levels, api_key=None, api_secret=None):
    c = _load(key); is_c = sleeve == "crypto"
    tfs = {tf: (c.get(tf) or {}).get("bars") or [] for tf in ("5m", "1h", "1T")}
    last = (tfs["5m"] or tfs["1h"] or [[0, 0, 0, 0, entry_px]])[-1][4]
    return {"kind": "alpaca", "prec": prec_for(min(entry_px or last or 1, last or 1)) if (entry_px or last) else 2,
            "tf": {k: [[(loc(b[0]) if k != "1T" else loc(b[0]) // 86400 * 86400), b[1], b[2], b[3], b[4]] for b in v] for k, v in tfs.items() if v},
            "order": ["5m", "1h", "1T"], "default": "5m" if tfs["5m"] else "1h",
            "entry": {"t": loc(entry_ts), "p": entry_px} if entry_ts else ({"t": None, "p": entry_px} if entry_px else None), "lines": levels, "sells": [],
            "src": "Alpaca " + ("Crypto" if is_c else "IEX") + "-Bars · 5m alle 5 Min, 1h alle 30 Min, 1T alle 6 Std",
            "facts": {}, "links": {"ext": (f"https://www.tradingview.com/symbols/{sym.replace('/', '').replace('USD', '')}USD/" if is_c else f"https://finance.yahoo.com/quote/{sym}"),
                              "embed": "https://s.tradingview.com/widgetembed/?symbol=" + (("COINBASE:" + sym.replace("/", "")) if is_c else sym)
                                       + "&interval=5&theme=dark&style=1&locale=de_DE&timezone=Europe%2FBerlin&hide_side_toolbar=1&allow_symbol_change=0&saveimage=0&toolbarbg=1c1c1e",
                              "embed_name": "TradingView"}}

def alp_history(tc):
    """Alpaca PAPER portfolio history (read-only): today 5Min + 1M 1H, cached 5 min -> {"today": [[t_loc, eq]], "month": [...]}."""
    c = _load("_alp_hist"); now = time.time()
    if now - c.get("ts", 0) >= 300:
        # 2026-10-21: Alpaca rejects 1H for periods > 30 days ("1M"+"1H" -> 400) -> week 1H + month 1D; each period fails soft
        from alpaca.trading.requests import GetPortfolioHistoryRequest
        out, bad = {}, []
        for k, per, tf in (("today", "1D", "5Min"), ("week", "1W", "1H"), ("month", "1M", "1D")):
            try:
                h = tc.get_portfolio_history(GetPortfolioHistoryRequest(period=per, timeframe=tf, extended_hours=True))
                out[k] = [[int(t), float(e)] for t, e in zip(h.timestamp or [], h.equity or []) if e]
            except Exception as e: bad.append(f"{k} {type(e).__name__}"); out[k] = c.get(k) or []
        if bad: _state["notes"].append("Alpaca history: " + ", ".join(bad))
        c = {"ts": now if not bad else now - 180, **out}; _save("_alp_hist", c)
    pts = {}
    for k in ("month", "week", "today"):
        for t, e in c.get(k) or []: pts[t] = e
    return [[loc(t), round(e, 2)] for t, e in sorted(pts.items())]

def notes(): return dict(_state)
