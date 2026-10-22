#!/usr/bin/env python3
"""QUANT dial: free-data regime dial (FRED keyless CSV, same-data fallbacks + Alpaca free bars). Paper desk only; never trades."""
import os, io, sys, json, math, datetime as dt, urllib.request
from zoneinfo import ZoneInfo
import pandas as pd

BERLIN = ZoneInfo("Europe/Berlin")
UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
DESK = os.path.expanduser("~/.desk")

# Max normal age (hours) of the latest observation, measured from the observation date
# (00:00 UTC of that date for FRED, bar close for Alpaca). Older => DEGRADED => red.
MAX_AGE_H = {
    "WALCL": 240,          # weekly (Wed level), published Thu ~16:30 ET -> up to ~8.5d + holiday slack
    "WTREGEN": 240,        # weekly (Wed level), same H.4.1 release
    "RRPONTSYD": 120,      # daily, same-day ~13:15 ET; covers 3-day weekends
    "VIXCLS": 120,         # daily, FRED posts next morning; covers long weekends
    "BAMLH0A0HYM2": 120,   # daily, ICE/FRED posts next day; covers long weekends
    "BTC/USD": 48, "SOL/USD": 48, "ETH/USD": 48,   # 24/7 daily bars (last complete UTC day)
    "QQQ": 120,            # daily IEX bars; covers 3-day weekends
}

# ---- FRED inputs: validated fetch + same-data fallbacks (2026-10-21 fix) ----
# fredgraph.csv answers HTTP 200 + an HTML "Site Maintenance" page while the St. Louis Fed is down; that HTML used to
# reach pd.read_csv ("Expected 1 fields in line 5, saw 3") and every FRED input went DEGRADED. Now each response is
# validated; on failure the SAME series is taken from its original publisher (VIXCLS = Cboe VIX close; WALCL/WTREGEN =
# Fed H.4.1; RRPONTSYD = NY Fed ON RRP), then from FRED's API if FRED_API_KEY is set, then from the local cache of the
# last good fetch. Ages are still measured from the observation date, so stale data stays DEGRADED exactly as before.
FRED_CACHE = f"{DESK}/dial_cache"
SOURCES, FETCH_NOTES = {}, {}
UA = {"User-Agent": "curl/8.14.1", "Accept": "*/*"}

def _http(url, tries=3, timeout=(5, 30), binary=False):
    import requests, time
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, timeout=timeout, headers=UA)
            r.raise_for_status()
            return r.content if binary else r.text
        except Exception as e:
            last = e; time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url.split('?')[0]} failed: {last}")

def _series(pairs, series):
    s = pd.Series({pd.Timestamp(d, tz="UTC"): v for d, v in pairs}, dtype="object")   # FRED '.' = missing
    s = pd.to_numeric(s, errors="coerce").dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if s.empty: raise RuntimeError(f"{series}: empty")
    s.index.name = "date"
    return s

def parse_fred_csv(raw, series):
    """fredgraph.csv -> Series. Raises on anything that is not the expected 2-column CSV (HTML maintenance/error pages)."""
    head = (raw or "").lstrip()[:400].lower()
    if not head or head.startswith("<") or "<html" in head:
        why = "FRED maintenance page" if "maintenance" in (raw or "").lower() else "HTML/empty page"
        raise RuntimeError(f"{series}: non-CSV response from fredgraph.csv ({why})")
    df = pd.read_csv(io.StringIO(raw))
    if df.shape[1] != 2 or series.lower() not in str(df.columns[1]).lower():
        raise RuntimeError(f"{series}: unexpected CSV columns {list(df.columns)[:4]}")
    df.columns = ["date", "value"]
    return _series(zip(df["date"], df["value"]), series)   # '.' = missing -> NaN -> dropped

def src_fredgraph(series):
    import subprocess
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    errs = []
    try:
        return parse_fred_csv(_http(url), series)
    except Exception as e:
        errs.append(f"requests: {e}")
    try:   # curl fallback (different TLS/HTTP stack)
        raw = subprocess.run(["curl", "-sfL", "-m", "30", "-A", UA["User-Agent"], url], capture_output=True, text=True, check=True).stdout
        return parse_fred_csv(raw, series)
    except Exception as e:
        errs.append(f"curl: {e}")
    raise RuntimeError("; ".join(errs))

def src_fred_api(series):
    key = os.environ.get("FRED_API_KEY")
    if not key: raise RuntimeError("no FRED_API_KEY")
    d = json.loads(_http(f"https://api.stlouisfed.org/fred/series/observations?series_id={series}&api_key={key}&file_type=json"))
    return _series(((o["date"], o["value"]) for o in d["observations"]), series)

def src_cboe_vix(series):
    raw = _http("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv")
    df = pd.read_csv(io.StringIO(raw))
    if list(df.columns)[:1] != ["DATE"] or "CLOSE" not in df.columns: raise RuntimeError(f"Cboe: unexpected columns {list(df.columns)[:6]}")
    return _series(zip(pd.to_datetime(df["DATE"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d"), df["CLOSE"]), series)

_H41 = {}
H41_CODES = {"WALCL": "RESPPA_N.WW", "WTREGEN": "RESPPLLDT_XAW_N.WW"}   # total assets Wed level; TGA week average (millions)
def src_fed_h41(series):
    """Fed Data Download Program, full H.4.1 package (zip, ~9 MB), parsed once per run for both series."""
    import zipfile, re
    if not _H41:
        z = zipfile.ZipFile(io.BytesIO(_http("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H41&filetype=zip", binary=True)))
        want = {v: k for k, v in H41_CODES.items()}; cur = None; acc = {k: [] for k in H41_CODES}
        sname = re.compile(rb'<kf:Series [^>]*SERIES_NAME="([^"]+)"'); obs = re.compile(rb'OBS_VALUE="([^"]+)" TIME_PERIOD="([^"]+)"')
        with z.open("H41_data.xml") as fh:
            for line in fh:
                if b"<kf:Series" in line:
                    m = sname.search(line); cur = want.get(m.group(1).decode()) if m else None
                if cur:
                    acc[cur] += [(d.decode(), v.decode()) for v, d in obs.findall(line)]
        for k, pairs in acc.items():
            if pairs: _H41[k] = _series(pairs, k)
    if series not in _H41: raise RuntimeError(f"H.4.1: {H41_CODES[series]} not found")
    return _H41[series]

def src_nyfed_rrp(series):
    """NY Fed Markets API, ON RRP operations; daily total accepted (USD -> billions, as FRED RRPONTSYD)."""
    end = NOW.date(); start = end - dt.timedelta(days=760)
    d = json.loads(_http(f"https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json?startDate={start}&endDate={end}"))
    tot = {}
    for o in d["repo"]["operations"]:
        if o.get("operationType") == "Reverse Repo" and o.get("totalAmtAccepted") is not None:
            tot[o["operationDate"]] = tot.get(o["operationDate"], 0.0) + float(o["totalAmtAccepted"]) / 1e9
    return _series(tot.items(), series)

FALLBACKS = {"VIXCLS": [("cboe", src_cboe_vix)], "WALCL": [("fed_h41", src_fed_h41)],
             "WTREGEN": [("fed_h41", src_fed_h41)], "RRPONTSYD": [("nyfed", src_nyfed_rrp)], "BAMLH0A0HYM2": []}

def _cache_path(series): return f"{FRED_CACHE}/{series}.csv"

def _cache_write(series, s, source):
    try:
        os.makedirs(FRED_CACHE, exist_ok=True); p = _cache_path(series)
        s.rename("value").to_frame().to_csv(p + ".tmp", date_format="%Y-%m-%d")
        os.replace(p + ".tmp", p)
        with open(p + ".meta.json", "w") as f:
            json.dump({"source": source, "fetched_at": NOW.astimezone(BERLIN).isoformat(timespec="seconds")}, f)
    except Exception:
        pass

def _cache_read(series):
    df = pd.read_csv(_cache_path(series))
    meta = json.load(open(_cache_path(series) + ".meta.json"))
    return _series(zip(df["date"], df["value"]), series), meta

def fred(series):
    """One FRED series. Order: fredgraph.csv (validated, retried, curl fallback) -> original publisher ->
    FRED API (if FRED_API_KEY) -> last good cache. Raises only if all fail. Source recorded in SOURCES."""
    chain = [("fred", src_fredgraph)] + FALLBACKS.get(series, []) + [("fred_api", src_fred_api)]
    notes = []
    for name, fn in chain:
        try:
            s = fn(series)
            SOURCES[series] = name; _cache_write(series, s, name)
            if notes: FETCH_NOTES[series] = notes
            return s
        except Exception as e:
            notes.append(f"{name}: {str(e).strip()[:300]}")
    try:
        s, meta = _cache_read(series)
        SOURCES[series] = f"cache({meta.get('source')}, fetched {meta.get('fetched_at')})"
        FETCH_NOTES[series] = notes
        return s
    except Exception as e:
        notes.append(f"cache: {e}")
    FETCH_NOTES[series] = notes
    raise RuntimeError(f"{series}: all sources failed: " + " | ".join(notes))

def age_h(ts):
    return round((NOW - ts).total_seconds() / 3600, 1)

def value_at_or_before(s, ts):
    sub = s[s.index <= ts]
    return (sub.index[-1], float(sub.iloc[-1])) if len(sub) else (None, None)

def alpaca_clients():
    from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
    k, sec = os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET")
    return CryptoHistoricalDataClient(k, sec), StockHistoricalDataClient(k, sec)

def crypto_closes(cc, syms, days=420):
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame
    df = cc.get_crypto_bars(CryptoBarsRequest(symbol_or_symbols=syms, timeframe=TimeFrame.Day,
                                              start=NOW - dt.timedelta(days=days))).df
    out = {}
    for s in syms:
        c = df.loc[s]["close"].sort_index()
        c = c[c.index + pd.Timedelta(days=1) <= NOW]   # drop the in-progress UTC day
        out[s] = c
    return out

def stock_closes(sc, sym, days=420):
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed
    df = sc.get_stock_bars(StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day,
                                            start=NOW - dt.timedelta(days=days), feed=DataFeed.IEX)).df
    c = df.loc[sym]["close"].sort_index()
    # a bar stamped today (NY) is only final after 16:00 NY; drop it if the session is still running
    ny = NOW.astimezone(ZoneInfo("America/New_York"))
    last_ny = c.index[-1].astimezone(ZoneInfo("America/New_York"))
    if last_ny.date() == ny.date() and ny.hour < 16:
        c = c.iloc[:-1]
    return c

def floor_quarter(x):
    return math.floor(x * 4 + 1e-9) / 4

def main():
    inputs, greens, ages, degraded, errors = {}, {}, {}, [], {}

    def mark_age(name, ts):
        ages[name] = age_h(ts)
        if ages[name] > MAX_AGE_H[name]:
            degraded.append(name)

    # ---- net liquidity (billions) ----
    try:
        walcl, tga, rrp = fred("WALCL"), fred("WTREGEN"), fred("RRPONTSYD")
        mark_age("WALCL", walcl.index[-1]); mark_age("WTREGEN", tga.index[-1]); mark_age("RRPONTSYD", rrp.index[-1])
        weekly = []
        for d in walcl.index:            # Wednesday H.4.1 levels
            _, t = value_at_or_before(tga, d)
            rd, r = value_at_or_before(rrp, d)
            if t is None or r is None or (d - rd).days > 7:
                continue
            weekly.append((d, walcl[d] / 1000 - t / 1000 - r))   # millions->billions; RRP already billions
        nl = pd.Series(dict(weekly)).sort_index()
        last_d, last = nl.index[-1], float(nl.iloc[-1])
        prev_d, prev = value_at_or_before(nl, last_d - pd.Timedelta(days=28))
        chg = last - prev
        inputs["liquidity"] = {"net_liquidity_bn": round(last, 1), "as_of": last_d.date().isoformat(),
                               "4w_ago_bn": round(prev, 1), "4w_ago_date": prev_d.date().isoformat(),
                               "change_4w_bn": round(chg, 1), "rule": "green if 4w change > 0"}
        ok = chg > 0 and not any(x in degraded for x in ("WALCL", "WTREGEN", "RRPONTSYD"))
        greens["liquidity"] = bool(ok)
    except Exception as e:
        errors["liquidity"] = str(e); greens["liquidity"] = False; degraded.append("liquidity")

    # ---- volatility ----
    try:
        vix = fred("VIXCLS"); mark_age("VIXCLS", vix.index[-1])
        inputs["volatility"] = {"vix_last": float(vix.iloc[-1]), "as_of": vix.index[-1].date().isoformat(), "rule": "green if < 22"}
        greens["volatility"] = bool(vix.iloc[-1] < 22 and "VIXCLS" not in degraded)
    except Exception as e:
        errors["volatility"] = str(e); greens["volatility"] = False; degraded.append("VIXCLS")

    # ---- credit ----
    try:
        hy = fred("BAMLH0A0HYM2"); mark_age("BAMLH0A0HYM2", hy.index[-1])
        pd_, pv = value_at_or_before(hy, hy.index[-1] - pd.Timedelta(days=28))
        chg = float(hy.iloc[-1]) - pv
        inputs["credit"] = {"hy_oas_last": float(hy.iloc[-1]), "as_of": hy.index[-1].date().isoformat(),
                            "4w_ago": pv, "4w_ago_date": pd_.date().isoformat(), "change_4w": round(chg, 3),
                            "rule": "green if 4w change <= 0"}
        greens["credit"] = bool(chg <= 0 and "BAMLH0A0HYM2" not in degraded)
    except Exception as e:
        errors["credit"] = str(e); greens["credit"] = False; degraded.append("BAMLH0A0HYM2")

    # ---- crypto + nasdaq via Alpaca ----
    crypto = {}
    try:
        cc, sc = alpaca_clients()
    except Exception as e:
        cc = sc = None; errors["alpaca"] = str(e)
    try:
        crypto = crypto_closes(cc, ["BTC/USD", "ETH/USD", "SOL/USD"])
        for sym, n, key in (("BTC/USD", 200, "btc"), ("SOL/USD", 50, "sol")):
            c = crypto[sym]; sma = float(c.rolling(n).mean().iloc[-1]); last = float(c.iloc[-1])
            if math.isnan(sma): raise RuntimeError(f"{sym} SMA{n} NaN")
            mark_age(sym, c.index[-1] + pd.Timedelta(days=1))
            inputs[key] = {"close": round(last, 2), f"sma{n}": round(sma, 2), "bar_date": c.index[-1].date().isoformat(),
                           "rule": f"green if close > {n}d avg"}
            greens[key] = bool(last > sma and sym not in degraded)
        mark_age("ETH/USD", crypto["ETH/USD"].index[-1] + pd.Timedelta(days=1))
    except Exception as e:
        errors["crypto"] = str(e); greens.setdefault("btc", False); greens.setdefault("sol", False)
        degraded += [s for s in ("BTC/USD", "SOL/USD") if s not in degraded]
    try:
        q = stock_closes(sc, "QQQ"); sma = float(q.rolling(200).mean().iloc[-1]); last = float(q.iloc[-1])
        if math.isnan(sma): raise RuntimeError("QQQ SMA200 NaN")
        close_ts = q.index[-1].tz_convert("America/New_York").normalize() + pd.Timedelta(hours=16)
        mark_age("QQQ", close_ts)
        inputs["nasdaq"] = {"qqq_close": round(last, 2), "sma200": round(sma, 2), "bar_date": q.index[-1].date().isoformat(),
                            "bars": len(q), "feed": "IEX", "rule": "green if close > 200d avg"}
        greens["nasdaq"] = bool(last > sma and "QQQ" not in degraded)
    except Exception as e:
        errors["nasdaq"] = str(e); greens["nasdaq"] = False; degraded.append("QQQ")

    # ---- dials (share of greens, never rounded up: floored to the 0.25 grid) ----
    sleeves = {"meme": ["liquidity", "volatility", "btc", "sol"],
               "stocks": ["liquidity", "volatility", "credit", "nasdaq"],
               "crypto": ["liquidity", "credit", "btc"]}
    def interp(x):
        return "stand down" if x < 0.5 else "half" if x < 0.75 else "three-quarters" if x < 1.0 else "full"
    dial, dial_raw, dial_interp = {}, {}, {}
    for k, ins in sleeves.items():
        raw = sum(greens.get(i, False) for i in ins) / len(ins)
        dial_raw[k] = round(math.floor(raw * 10000) / 10000, 4)
        dial[k] = floor_quarter(raw)
        dial_interp[k] = interp(dial[k])

    # ---- crypto momentum targets: return from ~12 months ago to ~1 month ago ----
    targets = {"method": "close(t-30d)/close(t-365d)-1; top 2 positive, equal weight; none -> cash",
               "scores": {}, "weights": {}, "cash": 1.0}
    try:
        for sym, c in crypto.items():
            ref = c.index[-1]
            _, p12 = value_at_or_before(c, ref - pd.Timedelta(days=365))
            _, p1 = value_at_or_before(c, ref - pd.Timedelta(days=30))
            if p12 is None or p1 is None: raise RuntimeError(f"{sym}: not enough history")
            targets["scores"][sym.split("/")[0]] = round(p1 / p12 - 1, 4)
        pos = sorted([(v, k) for k, v in targets["scores"].items() if v > 0], reverse=True)[:2]
        if pos:
            w = round(1 / len(pos), 4)
            targets["weights"] = {k: w for _, k in pos}; targets["cash"] = round(1 - w * len(pos), 4)
    except Exception as e:
        errors["crypto_targets"] = str(e)

    out = {
        "date": NOW.astimezone(BERLIN).date().isoformat(),
        "generated_at": NOW.astimezone(BERLIN).isoformat(timespec="seconds"),
        "inputs": inputs, "greens": greens,
        "dial": dial, "dial_raw": dial_raw, "dial_interpretation": dial_interp,
        "crypto_targets": targets,
        "data_age_hours": ages, "max_normal_age_hours": MAX_AGE_H,
        "degraded": sorted(set(degraded)),
    }
    if SOURCES: out["sources"] = SOURCES
    if FETCH_NOTES: out["fetch_notes"] = FETCH_NOTES
    if errors: out["errors"] = errors
    js = json.dumps(out, indent=2, default=str)
    print(js)
    os.makedirs(f"{DESK}/dial", exist_ok=True)
    with open(f"{DESK}/dial/{out['date']}.json", "w") as f:
        f.write(js + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
