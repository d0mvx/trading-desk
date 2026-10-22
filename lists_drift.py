#!/usr/bin/env python3
"""DRIFT list (post-earnings drift), free data only.
Rule (article): reported within the last 40 trading days, top-decile EPS surprise, closed UP on the report day.
Data: Nasdaq public earnings calendar (api.nasdaq.com/api/calendar/earnings?date=..., keyless, unofficial):
  EPS actual, consensus forecast (# of estimates), % surprise, market cap, report timing (pre-market/after-hours;
  for past dates Nasdaq shows 'time-not-supplied', so timing is recorded from upcoming-date calendars going forward).
  Price reaction: Alpaca daily bars (SIP, >15 min old = free plan).
Report-day reaction: pre-market -> close(D) > close(D-1); after-hours -> close(D+1) > close(D);
  unknown timing -> 2-session window close(D+1) > close(D-1) (covers both cases; documented approximation).
Desk guards (documented, configurable): >= 2 analyst estimates, market cap >= $300M, last price >= $5,
  active+tradable on Alpaca. Top decile = 90th percentile of % surprise over ALL eligible reports in the window.
Any data hole (a calendar day that failed) -> status null = hold. Symbols only from Nasdaq rows (never invented)."""
import os, sys, json, time, math, datetime as dt
import requests, pandas as pd
sys.path.insert(0, os.path.expanduser("~/.desk")); import alp_common as ac
OUT = f"{ac.DESK}/lists"; CACHE = f"{OUT}/earnings"; os.makedirs(CACHE, exist_ok=True)
SESSIONS, MIN_ESTS, MIN_MCAP, MIN_PRICE, DECILE = 40, 2, 300e6, 5.0, 0.90
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
       "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
TIMING = f"{CACHE}/_timing.json"

def cal(d, cache=True):
    p = f"{CACHE}/{d}.json"
    if cache and os.path.exists(p): return json.load(open(p))
    for a in range(3):
        try:
            r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": d}, headers=HDR, timeout=20)
            r.raise_for_status(); rows = ((r.json().get("data") or {}).get("rows")) or []
            if cache: ac.write_json(p, rows)
            return rows
        except Exception:
            time.sleep(3 * (a + 1))
    return None

def num(x):
    try: return float(str(x).replace("$", "").replace(",", "").replace("(", "-").replace(")", ""))
    except (ValueError, TypeError): return None

def record_timing():
    """Upcoming calendars carry pre-market/after-hours; store them so past report days get a real timing."""
    try: t = json.load(open(TIMING))
    except (FileNotFoundError, ValueError): t = {}
    for i in range(0, 8):
        d = (dt.date.today() + dt.timedelta(days=i)).isoformat()
        rows = cal(d, cache=False) or []
        for r in rows:
            if r.get("time") in ("time-pre-market", "time-after-hours"): t[f"{d}|{r['symbol']}"] = r["time"]
        time.sleep(0.5)
    ac.write_json(TIMING, t); return t

def build():
    tc = ac.trading()
    from alpaca.trading.requests import GetCalendarRequest
    today = dt.datetime.now(ac.NY).date()
    sess = [c.date for c in tc.get_calendar(GetCalendarRequest(start=today - dt.timedelta(days=80), end=today))]
    sess = [s for s in sess if s < today][-SESSIONS:]           # completed sessions only
    timing = record_timing()
    rows, missing = [], []
    for s in sess:
        r = cal(s.isoformat(), cache=(s < today - dt.timedelta(days=3)))   # re-pull the last few days (late updates)
        if r is None: missing.append(s.isoformat()); continue
        for x in r:
            sp, n, mc = num(x.get("surprise")), num(x.get("noOfEsts")), num(x.get("marketCap"))
            if sp is None or not x.get("symbol"): continue
            rows.append({"symbol": x["symbol"].strip().upper(), "date": s.isoformat(), "surprise_pct": sp, "eps": x.get("eps"),
                         "forecast": x.get("epsForecast"), "n_ests": int(n or 0), "mcap": mc or 0,
                         "time": timing.get(f"{s.isoformat()}|{x['symbol']}", x.get("time"))})
    elig = [r for r in rows if r["n_ests"] >= MIN_ESTS and r["mcap"] >= MIN_MCAP]
    if not elig or missing:
        out = {"list": "DRIFT", "status": "null", "names": None, "generated_at": dt.datetime.now(ac.BER).isoformat(timespec="seconds"),
               "reason": f"earnings calendar missing for {missing}" if missing else "no eligible reports", "sessions": len(sess)}
        ac.write_json(f"{OUT}/drift.json", out); ac.log("LISTS", f"DRIFT null (hold): {out['reason']}"); return out
    thr = float(pd.Series([r["surprise_pct"] for r in elig]).quantile(DECILE))
    top = {}
    for r in sorted(elig, key=lambda r: r["date"]):            # latest report per symbol wins
        if r["surprise_pct"] >= thr and r["surprise_pct"] > 0: top[r["symbol"]] = r
    # price reaction from Alpaca daily bars
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed
    sd = ac.stock_data(); syms = sorted(top)
    end = dt.datetime.now(ac.UTC) - dt.timedelta(minutes=16)
    closes = {}
    for i in range(0, len(syms), 100):
        try:
            df = sd.get_stock_bars(StockBarsRequest(symbol_or_symbols=syms[i:i + 100], timeframe=TimeFrame.Day,
                                                    start=dt.datetime.combine(sess[0] - dt.timedelta(days=10), dt.time(), ac.UTC), end=end, feed=DataFeed.SIP)).df
        except Exception as e:
            print(f"[DRIFT] bars failed {type(e).__name__}: {str(e)[:120]}"); df = pd.DataFrame()
        if not df.empty:
            for s in df.index.get_level_values(0).unique():
                c = df.loc[s]["close"]; c.index = [t.tz_convert(ac.NY).date() for t in c.index]; closes[s] = c
    def px(c, d, k):   # close k sessions relative to d (k=0 -> d, -1 -> previous)
        idx = list(c.index)
        if d not in idx: return None
        j = idx.index(d) + k
        return float(c.iloc[j]) if 0 <= j < len(idx) else None
    names, rejected = [], []
    tradable = {}
    for s, r in top.items():
        c = closes.get(s); d = dt.date.fromisoformat(r["date"])
        if c is None: rejected.append((s, "no bars")); continue
        if r["time"] == "time-pre-market": a, b, how = px(c, d, -1), px(c, d, 0), "pre-market: close(D)>close(D-1)"
        elif r["time"] == "time-after-hours": a, b, how = px(c, d, 0), px(c, d, 1), "after-hours: close(D+1)>close(D)"
        else: a, b, how = px(c, d, -1), px(c, d, 1), "timing unknown: close(D+1)>close(D-1)"
        if a is None or b is None: rejected.append((s, "reaction day not closed yet / bar missing")); continue
        last = float(c.iloc[-1])
        if not b > a: rejected.append((s, f"did not close up ({how})")); continue
        if last < MIN_PRICE: rejected.append((s, f"price {last:.2f} < {MIN_PRICE}")); continue
        try:
            asst = tc.get_asset(s.replace("/", ".")); ok = asst.tradable and str(asst.status.value) == "active" and str(asst.asset_class.value) == "us_equity"
        except Exception: ok = False
        if not ok: rejected.append((s, "not tradable on Alpaca")); continue
        names.append({"symbol": s, "report_date": r["date"], "surprise_pct": r["surprise_pct"], "eps": r["eps"], "forecast": r["forecast"],
                      "n_ests": r["n_ests"], "reaction": round(b / a - 1, 4), "reaction_rule": how, "last": last})
    names.sort(key=lambda x: -x["surprise_pct"])
    out = {"list": "DRIFT", "status": "ok", "generated_at": dt.datetime.now(ac.BER).isoformat(timespec="seconds"),
           "rule": f"reported in last {SESSIONS} sessions ({sess[0]}..{sess[-1]}), surprise >= p90 ({thr:.1f}%), closed up on report day",
           "guards": f">= {MIN_ESTS} estimates, mcap >= ${MIN_MCAP/1e6:.0f}M, price >= ${MIN_PRICE:.0f}, tradable on Alpaca",
           "source": "Nasdaq earnings calendar (unofficial public API) + Alpaca SIP daily bars",
           "reports_in_window": len(rows), "eligible_reports": len(elig), "top_decile_threshold_pct": round(thr, 2),
           "top_decile_symbols": len(top), "rejected": rejected[:60], "names": names}
    ac.write_json(f"{OUT}/drift.json", out)
    ac.log("LISTS", f"DRIFT {len(names)} names (surprise >= p90 {thr:.1f}%): {', '.join(n['symbol'] for n in names[:8])}")
    return out

if __name__ == "__main__":
    o = build()
    print(json.dumps({k: v for k, v in o.items() if k not in ("names", "rejected")} | {"names": [(n["symbol"], n["surprise_pct"], n["report_date"]) for n in (o.get("names") or [])]}, indent=1))
