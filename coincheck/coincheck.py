#!/usr/bin/env python3
"""coincheck.py - Solana memecoin analyzer (pump.fun / PumpSwap / Raydium / Meteora).

Usage:
  python3 ~/.desk/coincheck/coincheck.py <mint | pool | dexscreener/pump.fun/gmgn/fomo URL> [--text] [--no-gt]
    (default) JSON report on stdout          --text  short German summary (iPhone-friendly)
    --no-gt   never touch GeckoTerminal (0 GT calls)

Data sources (keyless, real data only):
  DexScreener   api.dexscreener.com          pairs, price, MC/FDV, liquidity, txns, volume, socials   (1-2 calls)
  RugCheck      api.rugcheck.xyz/v1/tokens/<mint>/report  authorities, LP lock, holders, risks, score (1 call)
  Solana RPC    api.mainnet-beta.solana.com  mint account (authorities, Token-2022 transfer fee), bonding-curve state
  pump.fun      swap-api.pump.fun/v2/coins/<mint>/candles  OHLCV for pump.fun coins (curve + PumpSwap)
  GeckoTerminal at most ONE call per run, through ~/.desk/gt.py (shared cross-process 9 calls/60 s limiter),
                only if a slot is free right now (6 s deadline, never waits for the desk) and only if needed:
                OHLCV for non-pump.fun coins, otherwise pool stats for unique buyers. Results cached 3 min.
  Desk scan     ~/.desk/scan/*.json (+ rejects jsonl) unique buyers from the desk's last GT scan if < 5 min old (0 calls)
Everything computed (ATH, supports, trend, curve progress, score, plan) is flagged as estimate ("_est").
"""
import os, sys, re, json, time, math, base64, struct, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qsl, unquote

# ============================== SCORING CONFIG (documented, edit here) ==============================
CONFIG = {
    # --- Safety gate: any DANGER caps the final Kauf-Score hard at danger_cap ---
    "danger_cap": 15,
    "danger_rules": {
        "mint_authority_set": True,        # mint authority not revoked
        "freeze_authority_set": True,      # freeze authority not revoked
        "transfer_fee_pct_max": 0.0,       # any Token-2022 transfer fee > 0
        "rugcheck_rugged": True,           # RugCheck 'rugged' flag
        "rugcheck_danger_risk": True,      # any RugCheck risk with level 'danger'
        "lp_locked_min_pct": 90.0,         # AMM main pool: LP locked/burned below this
        "top_holder_max_pct": 20.0,        # largest non-pool holder (AMM/locker/curve accounts excluded)
        "creator_max_pct": 10.0,           # creator/dev wallet share of supply
        "insiders_max": 20,                # RugCheck graphInsidersDetected
        "min_liquidity_usd": 3000.0,       # AMM pool liquidity below this (or 0 = LP pulled)
    },
    "unknown_safety_cap": 35,              # RugCheck unreachable -> safety unknown -> cap
    "young_age_min": 15, "young_cap": 40,  # coin younger than 15 min -> too little data -> cap
    "wash_cap": 30,                        # wash/bot suspicion -> cap
    "downtrend_cap": 50,                   # OHLCV shows lower lows/highs -> cap (no 'Kauf möglich' into a downtrend)
    "chase_cap": 50,                       # at/near ATH (<5% below) after >50% 1h pump -> cap (no FOMO buys)
    "overheated_h1_pct": 150.0, "overheated_cap": 50,   # 1h change above this -> cap
    "no_unique_buyers_cap": 60,            # unique buyers unknown (GT budget full) -> bot check missing -> cap
    "bs_suspicious": 2.5,                  # buys/sells 1h above this looks like micro-buy bots -> only pts_bs_suspicious
    "pts_bs_suspicious": 4,
    "wash_vol_liq_max": 40.0,              # vol24 / liquidity above this = wash suspicion (AMM only)
    "bot_buyers_per_buy_min": 0.20,        # unique buyers / buys (h1) below this = bot-like
    # --- Components (sum of maxima = 100) ---
    "max": {"safety": 30, "liquidity": 15, "momentum": 20, "flow": 20, "entry": 15},
    "safety": {"warn_penalty": 4, "warn_penalty_max": 12, "top10_hi": 30.0, "top10_hi_pen": 6, "top10_mid": 20.0,
               "top10_mid_pen": 3, "creator_warn_pct": 3.0, "creator_pen": 4, "no_socials_pen": 4,
               "lp_lock_warn_pct": 99.0, "lp_lock_pen": 4, "mutable_meta_pen": 2},
    "liquidity": {"ratio_steps": [(0.15, 15), (0.08, 10), (0.04, 6), (0.0, 2)], "curve_points": 10, "abs_low_usd": 10000.0, "abs_low_pen": 5},
    "momentum": {"h1_sweet": (5.0, 100.0), "pts_h1_sweet": 8, "pts_h1_flat": 5, "pts_h1_dip": 3, "pts_h1_hot": 4,
                 "h1_dip_floor": -15.0, "pts_h6_pos": 2, "pts_vol_rising": 2, "pts_trend_up": 8, "pts_trend_side": 4},
    "flow": {"bs_h1_steps": [(1.3, 8), (1.1, 6), (0.95, 3)], "bs_m5_min": 1.1, "pts_bs_m5": 4,
             "ubpb_steps": [(0.35, 8), (0.25, 5), (0.20, 2)], "pts_ubpb_unknown": 4},
    "entry": {"near_support_pct": 10.0, "pts_near": 15, "mid_support_pct": 25.0, "pts_mid": 9, "pts_far": 4,
              "pts_no_support": 5, "chase_dd_pct": 5.0, "chase_h1_pct": 50.0, "pts_chase": 3, "dead_dd_pct": 80.0, "pts_dead": 2},
    # --- Verdict bands / plan ---
    "buy_min": 65, "dip_min": 45,          # >=65 Kauf möglich, 45-64 nur bei Dip/Bestätigung, <45 kein Kauf
    "buy_requires_entry_pts": 9,           # 'Kauf möglich' only if price is <=25% above a support (else dip plan)
    "stop_below_support_pct": 12.0,        # stop = support MC x (1 - 12%) (or next lower support if closer)
    "support_swing_k": 3,                  # swing low = lowest of +/- k candles
    "support_bounce_min_pct": 8.0,         # price must have bounced >= 8% off that low to count as support
    "support_cluster_pct": 6.0,            # merge supports closer than 6%
    "wick_filter_x": 2.5,                  # ignore candle highs > 2.5x max(open, close) (single-trade wicks) for ATH
}
# ======================================================================================================

HOME = os.path.expanduser("~")
DESK = os.path.join(HOME, ".desk")
CACHE = os.path.join(DESK, "coincheck", ".cache.json")
UA = {"User-Agent": "Mozilla/5.0 (coincheck/1.0)"}
RPC = "https://api.mainnet-beta.solana.com"
DS = os.environ.get("COINCHECK_DS_URL", "https://api.dexscreener.com")      # env overrides only for outage tests
RC = os.environ.get("COINCHECK_RC_URL", "https://api.rugcheck.xyz/v1/tokens/{}/report")
PUMP_CANDLES = "https://swap-api.pump.fun/v2/coins/{}/candles"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
SOL_MINT = "So11111111111111111111111111111111111111112"
QUOTES = {SOL_MINT, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrAgEBzc7yJbJEGFgHBrSvEmgrphTUoU5U4y8tF"}
IGNORE_ADDR = QUOTES | {"11111111111111111111111111111111", "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb", PUMP_PROGRAM}
BC_INITIAL_REAL_TOKENS = 793_100_000 * 10**6   # pump.fun curve: real tokens sellable on the curve
T0 = time.time()
BER = dt.timezone(dt.timedelta(hours=2))
try:
    from zoneinfo import ZoneInfo; BER = ZoneInfo("Europe/Berlin")
except Exception: pass

try:
    import requests
except ImportError:  # use the desk venv if run with a bare python3
    vpy = os.path.join(DESK, "venv", "bin", "python")
    if os.path.exists(vpy) and sys.executable != vpy: os.execv(vpy, [vpy] + sys.argv)
    raise

class UserError(Exception):
    def __init__(self, code, de, en=None): super().__init__(en or de); self.code, self.de, self.en = code, de, en or de

# ----------------------------------------------------------------------------- helpers
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58decode(s):
    n = 0
    for ch in s:
        i = B58.find(ch)
        if i < 0: return None
        n = n * 58 + i
    b = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + b

def is_sol_addr(s): return bool(s) and 32 <= len(s) <= 44 and (b := b58decode(s)) is not None and len(b) == 32

def fnum(x):
    try: return float(x) if x is not None and x != "" else None
    except (TypeError, ValueError): return None

def http_json(url, params=None, timeout=8, method="GET", body=None):
    r = requests.request(method, url, params=params, json=body, timeout=timeout, headers=UA)
    if r.status_code == 404: return None
    r.raise_for_status(); return r.json()

def rpc(method, params, timeout=6):
    d = http_json(RPC, method="POST", body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
    if d is None or "error" in d: raise RuntimeError(f"RPC {method}: {(d or {}).get('error')}")
    return d["result"]

def cache_get(key, ttl):
    try:
        c = json.load(open(CACHE)); e = c.get(key)
        return e["v"] if e and time.time() - e["ts"] < ttl else None
    except Exception: return None

def cache_put(key, v):
    try:
        try: c = json.load(open(CACHE))
        except Exception: c = {}
        c = {k: e for k, e in c.items() if time.time() - e["ts"] < 900}; c[key] = {"ts": time.time(), "v": v}
        tmp = CACHE + ".tmp"; json.dump(c, open(tmp, "w")); os.replace(tmp, CACHE)
    except Exception: pass

# ----------------------------------------------------------------------------- input parsing
FOMO_NO_ADDR = "Keine Adresse im Link gefunden – bitte die Coin-Adresse aus der FOMO-App kopieren."

def _candidates(text):
    out = []
    for tok in re.split(r"[^1-9A-HJ-NP-Za-km-z]+", text):   # split on any non-base58 char (/, ?, &, =, _, -, ...)
        if 32 <= len(tok) <= 44 and tok not in IGNORE_ADDR and is_sol_addr(tok) and tok not in out: out.append(tok)
    return out

def parse_input(raw):
    """-> (kind, address_or_list, note). kind: 'addr' | 'ds_pair' | 'addrs' (candidates to probe)."""
    s = raw.strip().strip("<>\"'")
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", s) or re.search(r"0x[0-9a-fA-F]{40}", s):
        raise UserError("not_solana", "Das ist eine EVM-Adresse (Ethereum/Base/BSC) – kein Solana-Coin.", "EVM address, not Solana")
    if not re.match(r"^[a-z]+://", s, re.I) and ("." in s and "/" in s): s = "https://" + s
    if not re.match(r"^[a-z]+://", s, re.I):
        if is_sol_addr(s): return "addr", s, None
        raise UserError("bad_input", "Keine gültige Solana-Adresse (Base58, 32–44 Zeichen) und kein Link.", "not a Solana address or URL")
    u = urlparse(s); host = (u.hostname or "").lower(); path = unquote(u.path or "")
    segs = [x for x in path.split("/") if x]
    if host.endswith("dexscreener.com") and segs:
        chain = segs[0].lower()
        if chain != "solana": raise UserError("not_solana", f"DexScreener-Link ist für '{chain}', nicht Solana.", f"chain {chain}")
        if len(segs) > 1 and re.fullmatch(r"[0-9A-Za-z]{32,44}", segs[1]):   # DexScreener lowercases pair ids (not valid base58)
            return ("addr" if is_sol_addr(segs[1]) else "ds_pair"), segs[1], "dexscreener"
    if host.endswith("gmgn.ai") and segs and segs[0].lower() in ("eth", "bsc", "base", "tron", "blast", "arb"):
        raise UserError("not_solana", f"GMGN-Link ist für '{segs[0]}', nicht Solana.", "gmgn non-solana")
    text = path + " " + " ".join(f"{k} {v}" for k, v in parse_qsl(u.query or "")) + " " + unquote(u.fragment or "")
    c = _candidates(text)
    if c: return ("addr", c[0], host) if len(c) == 1 else ("addrs", c, host)
    # no address in the URL itself: fetch the page (share links / redirects), check final URL, og: tags, HTML
    is_fomo = "fomo" in host
    try:
        r = requests.get(s, timeout=8, headers=UA, allow_redirects=True)
        found = _candidates(unquote(r.url))
        html = r.text[:600000] if "html" in (r.headers.get("content-type") or "") or r.text.lstrip().startswith("<") else ""
        metas = " ".join(re.findall(r'<meta[^>]+(?:og:|twitter:)[^>]*>', html, re.I))
        for t in (metas, html):
            for x in _candidates(t):
                if x not in found: found.append(x)
    except Exception:
        found = []
    if found: return "addrs", found[:6], host + " (Seite geladen)"
    if is_fomo: raise UserError("no_address", FOMO_NO_ADDR, "no address in FOMO link")
    raise UserError("no_address", "Keine Solana-Adresse im Link gefunden – bitte die Coin-Adresse (Mint) direkt angeben.", "no address in URL")

# ----------------------------------------------------------------------------- resolution (DexScreener)
def ds_token_pairs(mint):
    d = http_json(f"{DS}/latest/dex/tokens/{mint}", timeout=5) or {}
    return d.get("pairs") or []

def ds_pair(addr):
    d = http_json(f"{DS}/latest/dex/pairs/solana/{addr}", timeout=5) or {}
    return d.get("pairs") or ([d["pair"]] if d.get("pair") else [])

def resolve(kind, val):
    """-> (mint, pairs, input_was_pool)"""
    tried = val if kind == "addrs" else [val]
    ds_err = None
    for a in tried:
        try:
            if kind != "ds_pair":
                pairs = ds_token_pairs(a)
                sol = [p for p in pairs if p.get("chainId") == "solana"]
                if pairs and not sol: raise UserError("not_solana", "Token ist nicht auf Solana gelistet.", "not on Solana")
                mine = [p for p in sol if (p.get("baseToken") or {}).get("address") == a or (p.get("quoteToken") or {}).get("address") == a]
                if mine: return a, mine, False
            pp = ds_pair(a)
            pp = [p for p in pp if p.get("chainId") == "solana"]
            if pp:
                p = pp[0]; b, q = p["baseToken"]["address"], p["quoteToken"]["address"]
                mint = q if b in QUOTES and q not in QUOTES else b
                return mint, [x for x in ds_token_pairs(mint) if x.get("chainId") == "solana"] or pp, True
        except UserError: raise
        except Exception as e: ds_err = e
    a = tried[0] if kind != "ds_pair" else None
    if ds_err:
        if a and is_sol_addr(a): return a, None, False   # DexScreener down -> partial report
        raise UserError("api_down", f"DexScreener nicht erreichbar ({type(ds_err).__name__}) – später erneut versuchen.", str(ds_err))
    # not on DexScreener: is it at least a token mint?
    for a in (tried if kind != "ds_pair" else []):
        try:
            acc = rpc("getAccountInfo", [a, {"encoding": "jsonParsed"}])["value"]
            if acc and isinstance(acc.get("data"), dict) and (acc["data"].get("parsed") or {}).get("type") == "mint": return a, [], False
        except Exception: pass
    raise UserError("unknown", "Unbekannte Adresse: kein Solana-Token/Pool mit Handelspaar gefunden (DexScreener/RPC).", "unknown address")

VENUES = {"pumpfun": "pump.fun Bonding Curve", "pumpswap": "PumpSwap", "raydium": "Raydium", "meteora": "Meteora",
          "meteoradbc": "Meteora DBC (Bonding Curve)", "orca": "Orca", "launchlab": "Raydium LaunchLab (Bonding Curve)",
          "raydiumlaunchlab": "Raydium LaunchLab (Bonding Curve)", "moonshot": "Moonshot", "boop": "boop.fun"}
CURVE_DEX = {"pumpfun", "meteoradbc", "launchlab", "raydiumlaunchlab", "moonshot", "boop"}

def pick_main(pairs):
    def liq(p): return fnum((p.get("liquidity") or {}).get("usd")) or 0
    def vol(p): return fnum((p.get("volume") or {}).get("h24")) or 0
    amm = [p for p in pairs if p.get("dexId") not in CURVE_DEX and liq(p) > 0]
    if amm: return max(amm, key=lambda p: (liq(p) * (1 if vol(p) > 0 else 0.01), vol(p)))
    curve = [p for p in pairs if p.get("dexId") in CURVE_DEX]
    if curve: return max(curve, key=lambda p: (vol(p), p.get("pairCreatedAt") or 0))
    return max(pairs, key=lambda p: (vol(p), p.get("pairCreatedAt") or 0)) if pairs else None

# ----------------------------------------------------------------------------- data fetchers (parallel)
def get_rugcheck(mint):
    r = requests.get(RC.format(mint), timeout=(4, 8), headers=UA)
    if r.status_code != 200: raise RuntimeError(f"RugCheck HTTP {r.status_code}")
    return r.json()

def get_mint_rpc(mint):
    v = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]
    if not v: return None
    p = (v.get("data") or {}).get("parsed") or {}
    info = p.get("info") or {}
    out = {"program": p.get("program") or v.get("owner"), "mint_authority": info.get("mintAuthority"), "freeze_authority": info.get("freezeAuthority"),
           "supply_raw": info.get("supply"), "decimals": info.get("decimals"), "transfer_fee_bps": 0, "meta_uri": None}
    for ext in info.get("extensions") or []:
        st = ext.get("state") or {}
        if ext.get("extension") == "transferFeeConfig":
            out["transfer_fee_bps"] = max(int((st.get("newerTransferFee") or {}).get("transferFeeBasisPoints") or 0),
                                          int((st.get("olderTransferFee") or {}).get("transferFeeBasisPoints") or 0))
        if ext.get("extension") == "tokenMetadata": out["meta_uri"] = st.get("uri")
        if ext.get("extension") in ("permanentDelegate", "nonTransferable", "transferHook"): out.setdefault("risky_extensions", []).append(ext["extension"])
    return out

def get_curve(addr):
    v = rpc("getAccountInfo", [addr, {"encoding": "base64"}])["value"]
    if not v or v.get("owner") != PUMP_PROGRAM: return None
    raw = base64.b64decode(v["data"][0])
    vt, vs, rt, rs, ts = struct.unpack_from("<5Q", raw, 8); complete = bool(raw[48])
    prog = max(0.0, min(100.0, (1 - rt / BC_INITIAL_REAL_TOKENS) * 100)) if not complete else 100.0
    return {"virtual_token_reserves": vt, "virtual_sol_reserves": vs / 1e9, "real_token_reserves": rt, "real_sol": rs / 1e9,
            "complete": complete, "progress_pct_est": round(prog, 1)}

def get_pump_candles(mint, interval, limit=1000, age_h=None):
    """pump.fun swap-api sometimes answers with only the latest candle (CDN/cache): retry once if the series is too short."""
    exp = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}[interval]
    want = min(5, int((age_h or 0) * 60 / exp * 0.3))
    out = []
    for attempt in range(2):
        out = _pump_candles_once(mint, interval, limit)
        if len(out) >= want: break
        time.sleep(0.4)
    return out

def _pump_candles_once(mint, interval, limit):
    d = http_json(PUMP_CANDLES.format(mint), params={"interval": interval, "limit": limit, "currency": "USD",
                                                    "createdTs": int(time.time()) * 1000}, timeout=6)
    out = []
    for c in d or []:
        o, h, l, cl, v = (fnum(c.get(k)) for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, cl) or min(o, h, l, cl) <= 0: continue
        out.append([c["timestamp"] / 1000, o, h, l, cl, v or 0.0])
    return sorted(out)

def gt_slot_free():
    try:
        with open(os.path.join(DESK, ".gt_calls")) as f: calls = [float(x) for x in f.read().split()]
        return sum(1 for c in calls if time.time() - c < 60) < 9
    except FileNotFoundError: return True
    except Exception: return False

def gt_call(path, params, cache_key):
    """At most one GT call per run, via desk limiter; never waits (6 s deadline)."""
    hit = cache_get(cache_key, 180)
    if hit is not None: return hit, "cache"
    if time.time() - T0 > 13: return None, "GT übersprungen (Laufzeit-Budget)"
    if not gt_slot_free(): return None, "GT-Budget voll (Desk-Scan hat Vorrang) – übersprungen"
    sys.path.insert(0, DESK)
    try:
        import gt
        import threading
        box = {}
        def run():
            try: box["d"] = gt.get(path, params, deadline=time.time() + 5)
            except Exception as e: box["e"] = e
        t = threading.Thread(target=run, daemon=True); t.start(); t.join(max(1.0, 18 - (time.time() - T0)))
        if "e" in box: raise box["e"]
        if "d" not in box: return None, "GT übersprungen: Timeout (Laufzeit-Budget)"
        d = box["d"]; cache_put(cache_key, d); return d, "live"
    except Exception as e: return None, f"GT übersprungen: {type(e).__name__}: {str(e)[:80]}"

def gt_ohlcv(pool, age_h):
    if age_h is not None and age_h <= 3: tf, agg, iv = "minute", 1, "1m"
    elif age_h is None or age_h <= 80: tf, agg, iv = "minute", 5, "5m"
    elif age_h <= 240: tf, agg, iv = "minute", 15, "15m"
    elif age_h <= 1000: tf, agg, iv = "hour", 1, "1h"
    else: tf, agg, iv = "hour", 4, "4h"
    d, how = gt_call(f"/networks/solana/pools/{pool}/ohlcv/{tf}", {"aggregate": agg, "limit": 1000, "currency": "usd"}, f"ohlcv:{pool}:{iv}")
    if not d: return None, iv, how
    rows = (((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list")) or []
    return sorted([[r[0], *map(float, r[1:6])] for r in rows if r and all(x for x in r[1:5])]), iv, how

def desk_scan_lookup(pool):
    """Unique buyers from the desk's own latest GeckoTerminal scan (0 extra calls) if fresh (<5 min)."""
    try:
        import glob
        files = sorted(glob.glob(os.path.join(DESK, "scan", "2*.json")))
        cands, at = [], None
        if files:
            d = json.load(open(files[-1])); at = d.get("scanned_at"); cands = d.get("candidates") or []
        rj = sorted(glob.glob(os.path.join(DESK, "scan", "rejects-*.jsonl")))
        if rj:
            with open(rj[-1], "rb") as f:
                f.seek(0, 2); f.seek(max(0, f.tell() - 900000)); tail = f.read().decode("utf8", "ignore").splitlines()
            for line in reversed(tail):
                if '"type": "scan"' in line or '"type":"scan"' in line:
                    try: d = json.loads(line)
                    except ValueError: continue
                    if not at or d.get("scanned_at", "") >= at: at = d.get("scanned_at"); cands = cands + (d.get("rejects") or [])
                    break
        if not at: return None
        age = time.time() - dt.datetime.fromisoformat(at).timestamp()
        if age > 300: return None
        for c in cands:
            if c.get("pool") == pool and c.get("tx_h1"):
                return {"tx_h1": c["tx_h1"], "tx_m15": c.get("tx_m15"), "at": at, "src": "desk scan (GeckoTerminal)"}
    except Exception: return None
    return None

def gt_pool_buyers(pool):
    d, how = gt_call(f"/networks/solana/pools/{pool}", None, f"pool:{pool}")
    if not d: return None, how
    tx = (((d.get("data") or {}).get("attributes") or {}).get("transactions")) or {}
    return {"tx_h1": tx.get("h1"), "tx_m15": tx.get("m15"), "tx_m5": tx.get("m5"), "src": f"GeckoTerminal ({how})"}, how

def get_meta_socials(uri):
    if not uri: return {}
    if uri.startswith("ipfs://"): uri = "https://ipfs.io/ipfs/" + uri[7:]
    d = http_json(uri, timeout=3) or {}
    ext = d.get("extensions") or {}
    return {k: v for k, v in {"website": d.get("website") or ext.get("website"), "twitter": d.get("twitter") or ext.get("twitter"),
                              "telegram": d.get("telegram") or ext.get("telegram")}.items() if isinstance(v, str) and v.strip()}

# ----------------------------------------------------------------------------- analysis
def swing_supports(c, k, bounce_pct, cluster_pct):
    lows = []
    for i in range(len(c)):
        lo = c[i][3]
        win = c[max(0, i - k): i + k + 1]
        if lo > min(x[3] for x in win): continue
        after = c[i + 1:]
        if not after: continue
        hi_after = max(x[2] for x in after[: max(k * 4, 6)])
        if hi_after >= lo * (1 + bounce_pct / 100): lows.append((lo, c[i][0]))
    lows.sort()
    clusters = []
    for lo, ts in lows:
        if clusters and lo <= clusters[-1]["price"] * (1 + cluster_pct / 100):
            clusters[-1]["touches"] += 1; clusters[-1]["last_ts"] = max(clusters[-1]["last_ts"], ts)
        else: clusters.append({"price": lo, "touches": 1, "last_ts": ts})
    return clusters

def trend_struct(c):
    """Higher lows / higher highs over the last ~4 segments of the series."""
    if len(c) < 8: return {"label": "zu wenig Daten", "higher_lows": None}
    seg = c[-min(len(c), 48):]; n = 4; L = len(seg) // n
    lows = [min(x[3] for x in seg[i * L:(i + 1) * L]) for i in range(n)]
    highs = [max(x[2] for x in seg[i * L:(i + 1) * L]) for i in range(n)]
    hl = sum(lows[i] > lows[i - 1] for i in range(1, n)); hh = sum(highs[i] > highs[i - 1] for i in range(1, n))
    if hl >= 2 and lows[-1] > lows[0]: lab = "Aufwärtstrend (höhere Tiefs)"
    elif hl <= 1 and hh <= 1 and lows[-1] < lows[0]: lab = "Abwärtstrend (tiefere Tiefs/Hochs)"
    else: lab = "Seitwärts / gemischt"
    return {"label": lab, "higher_lows": hl >= 2 and lows[-1] > lows[0], "segment_lows": lows, "segment_highs": highs,
            "window_candles": len(seg)}

def analyze(raw, use_gt=True):
    kind, val, note = parse_input(raw)
    try: mint, pairs, input_pool = resolve(kind, val)
    except UserError as e:
        if e.code == "unknown" and note and "Seite geladen" in note and "fomo" in note: raise UserError("no_address", FOMO_NO_ADDR, "no mint in FOMO page")
        raise
    warnings, sources = [], {}
    main = pick_main(pairs) if pairs else None
    if pairs is None: warnings.append("DexScreener nicht erreichbar – keine Marktdaten")
    elif not pairs: warnings.append("Kein Handelspaar auf DexScreener (evtl. zu neu)")
    dex = (main or {}).get("dexId"); pool = (main or {}).get("pairAddress")
    created = [p.get("pairCreatedAt") for p in pairs or [] if p.get("pairCreatedAt")]
    age_h = (time.time() - min(created) / 1000) / 3600 if created else None
    is_pump = mint.endswith("pump") or any(p.get("dexId") in ("pumpfun", "pumpswap") for p in pairs or [])
    curve_pair = next((p for p in pairs or [] if p.get("dexId") == "pumpfun"), None)

    jobs = {}
    with ThreadPoolExecutor(8) as ex:
        jobs["rc"] = ex.submit(get_rugcheck, mint)
        jobs["mint"] = ex.submit(get_mint_rpc, mint)
        if curve_pair: jobs["curve"] = ex.submit(get_curve, curve_pair["pairAddress"])
        if is_pump:
            iv = "1m" if (age_h or 0) <= 3 else "5m" if (age_h or 0) <= 80 else "15m" if age_h <= 240 else "1h" if age_h <= 1000 else "4h"
            jobs["pc"] = ex.submit(get_pump_candles, mint, iv, 1000, age_h); jobs["pc_iv"] = iv
        res, errs = {}, {}
        for k, f in jobs.items():
            if k == "pc_iv": continue
            try: res[k] = f.result(timeout=max(1, 15 - (time.time() - T0)))
            except Exception as e: errs[k] = f"{type(e).__name__}: {str(e)[:100]}"
    rc = res.get("rc"); mi = res.get("mint"); curve = res.get("curve")
    for k, e in errs.items(): warnings.append({"rc": "RugCheck", "mint": "Solana-RPC (Mint)", "curve": "RPC (Bonding Curve)", "pc": "pump.fun Candles"}[k] + f" fehlgeschlagen: {e}")
    sources["dexscreener"] = "ok" if pairs is not None else "down"; sources["rugcheck"] = "ok" if rc else "fehlgeschlagen"
    sources["solana_rpc"] = "ok" if mi else "fehlgeschlagen"

    # ---- market basics
    price = fnum((main or {}).get("priceUsd")); mcap = fnum((main or {}).get("marketCap")); fdv = fnum((main or {}).get("fdv"))
    liq = fnum(((main or {}).get("liquidity") or {}).get("usd"))
    native = fnum((main or {}).get("priceNative")); sol_usd = price / native if price and native and (main.get("quoteToken") or {}).get("address") == SOL_MINT else None
    on_curve = dex in CURVE_DEX
    if curve and on_curve and dex == "pumpfun":
        if sol_usd: liq = curve["real_sol"] * sol_usd * 2; liq_note = "geschätzt: 2 x reale SOL im Curve (RPC)"
        else: liq_note = None
    else: liq_note = None
    if mcap is None and rc and rc.get("price") and (rc.get("token") or {}).get("supply"):
        mcap = rc["price"] * float(rc["token"]["supply"]) / 10 ** (rc["token"].get("decimals") or 6)
        warnings.append("MC aus RugCheck-Preis x Supply berechnet (Schätzung)")
    sup_factor = (mcap / price) if mcap and price else None   # MC = price x factor
    tx = (main or {}).get("txns") or {}; vol = (main or {}).get("volume") or {}; pc = (main or {}).get("priceChange") or {}
    def bs(w): t = tx.get(w) or {}; return t.get("buys"), t.get("sells")

    # ---- unique buyers (desk scan -> GT pool if slot free and GT not needed for OHLCV)
    ub = desk_scan_lookup(pool) if pool else None
    candles, c_iv, c_src = None, None, None
    if is_pump and res.get("pc"):
        pcs = res["pc"]
        if len(pcs) >= 3 and price and abs(pcs[-1][4] / price - 1) < 0.35: candles, c_iv, c_src = pcs, jobs["pc_iv"], "pump.fun swap-api"
        else: warnings.append("pump.fun Candles: keine/unplausible Daten für diesen Mint – verworfen")
    elif mint.endswith("pump") and "pc" in res and not res["pc"]: warnings.append("pump.fun Candles: leere Antwort")
    gt_used = False
    if candles is None and pool and use_gt and not on_curve:
        candles, c_iv, how = gt_ohlcv(pool, age_h); gt_used = True
        c_src = f"GeckoTerminal ({how})" if candles else None
        if not candles: warnings.append(f"OHLCV nicht verfügbar: {how}")
    elif candles is None and pool and use_gt and on_curve:
        candles, c_iv, how = gt_ohlcv(pool, age_h); gt_used = True; c_src = f"GeckoTerminal ({how})" if candles else None
        if not candles: warnings.append(f"OHLCV nicht verfügbar: {how}")
    if not ub and pool and use_gt and not gt_used and dex in ("pumpswap", "pumpfun", "raydium", "meteora"):
        ub, how = gt_pool_buyers(pool)
        if not ub: warnings.append(f"Unique Buyers nicht verfügbar: {how}")
    sources["ohlcv"] = c_src or "keine"; sources["unique_buyers"] = (ub or {}).get("src", "keine")

    # ---- socials
    info = (main or {}).get("info") or next((p.get("info") for p in pairs or [] if p.get("info")), None) or {}
    soc = {}
    for s in info.get("socials") or []:
        t = (s.get("type") or "").lower(); soc.setdefault("twitter" if t in ("twitter", "x") else t, s.get("url"))
    for w in info.get("websites") or []: soc.setdefault("website", w.get("url"))
    if not soc:
        uri = (mi or {}).get("meta_uri") or ((rc or {}).get("tokenMeta") or {}).get("uri")
        try: soc = get_meta_socials(uri) if time.time() - T0 < 15 else {}
        except Exception: soc = {}
        if soc: soc["_src"] = "Token-Metadaten (URI)"

    # ---- safety
    danger, warn = [], []
    tok = (rc or {}).get("token") or {}
    mint_auth = (mi or {}).get("mint_authority") if mi else (rc or {}).get("mintAuthority") or tok.get("mintAuthority")
    freeze_auth = (mi or {}).get("freeze_authority") if mi else (rc or {}).get("freezeAuthority") or tok.get("freezeAuthority")
    if not mi and not rc: mint_auth = freeze_auth = "unbekannt"
    fee_pct = ((mi or {}).get("transfer_fee_bps") or 0) / 100
    if rc and fnum((rc.get("transferFee") or {}).get("pct")): fee_pct = max(fee_pct, fnum(rc["transferFee"]["pct"]))
    DR = CONFIG["danger_rules"]
    if mint_auth and mint_auth != "unbekannt": danger.append("Mint Authority aktiv (unbegrenzt nachprägbar)")
    if freeze_auth and freeze_auth != "unbekannt": danger.append("Freeze Authority aktiv (Wallets einfrierbar)")
    if fee_pct > DR["transfer_fee_pct_max"]: danger.append(f"Transfer-Fee {fee_pct:g}%")
    for e in (mi or {}).get("risky_extensions") or []: warn.append(f"Token-2022 Extension: {e}")
    supply = fnum(tok.get("supply")) or fnum((mi or {}).get("supply_raw"))
    creator = (rc or {}).get("creator")
    creator_pct = (fnum(rc.get("creatorBalance")) or 0) / supply * 100 if rc and supply else None
    lp_locked = None; top1 = top10 = None; insiders = None; rc_score = None; risks = []
    if rc:
        if rc.get("rugged"): danger.append("RugCheck: als 'rugged' markiert")
        risks = [{"name": r.get("name"), "level": r.get("level"), "value": r.get("value"), "description": r.get("description")} for r in rc.get("risks") or []]
        for r in risks:
            if r["level"] == "danger": danger.append(f"RugCheck danger: {r['name']}" + (f" ({r['value']})" if r.get("value") else ""))
            elif r["level"] == "warn": warn.append(f"RugCheck: {r['name']}")
        mk = rc.get("markets") or []; known = rc.get("knownAccounts") or {}
        m = next((m for m in mk if m.get("pubkey") == pool), None)
        if m and not on_curve: lp_locked = fnum((m.get("lp") or {}).get("lpLockedPct"))
        pool_keys = {pool} | {x.get("pubkey") for x in mk} | {x.get("liquidityA") for x in mk} | {x.get("liquidityB") for x in mk} \
            | {k for k, v in known.items() if (v or {}).get("type") in ("AMM", "LOCKER")} | ({curve_pair["pairAddress"]} if curve_pair else set())
        hold = [h for h in rc.get("topHolders") or [] if h.get("owner") not in pool_keys and h.get("address") not in pool_keys]
        top1 = max((fnum(h.get("pct")) or 0 for h in hold), default=0.0); top10 = sum(fnum(h.get("pct")) or 0 for h in hold[:10])
        insiders = rc.get("graphInsidersDetected") or 0
        ins_holders = sum(1 for h in hold if h.get("insider"))
        rc_score = rc.get("score_normalised")
        if creator and creator_pct is not None:
            cp2 = sum(fnum(h.get("pct")) or 0 for h in hold if h.get("owner") == creator)
            creator_pct = max(creator_pct, cp2)
        if lp_locked is not None and lp_locked < DR["lp_locked_min_pct"] and not any("LP Unlocked" in d for d in danger):
            danger.append(f"LP nur {lp_locked:.0f}% gelockt/verbrannt")
        if top1 > DR["top_holder_max_pct"]: danger.append(f"Größter Holder (ohne Pool) {top1:.1f}%")
        if creator_pct is not None and creator_pct > DR["creator_max_pct"]: danger.append(f"Creator hält {creator_pct:.1f}%")
        if insiders > DR["insiders_max"]: danger.append(f"Insider-Netzwerk: {insiders} Wallets")
        meta_mutable = (rc.get("tokenMeta") or {}).get("mutable")
    else:
        meta_mutable = None; ins_holders = None
    if main and not on_curve and liq is not None and liq < DR["min_liquidity_usd"]:
        danger.append(f"Liquidität nur {fmc(liq)}" + (" (LP abgezogen?)" if liq == 0 else ""))
    PRIO = ("Liquidität nur", "rugged", "Low Liquidity", "Mint Authority", "Freeze Authority", "Transfer-Fee", "LP", "Creator", "Single holder", "Größter Holder")
    danger.sort(key=lambda d: next((i for i, k in enumerate(PRIO) if k in d), 99))
    bundles = [r["name"] for r in risks if "bundl" in (r["name"] or "").lower() or "snip" in (r["name"] or "").lower()]

    # ---- momentum / structure from OHLCV
    ath = None; supports = []; trend = {"label": "keine OHLCV-Daten", "higher_lows": None}
    if candles:
        wx = CONFIG["wick_filter_x"]
        hi_c = [(x[0], x[2] if x[2] <= wx * max(x[1], x[4]) else max(x[1], x[4])) for x in candles]
        ts_ath, p_ath = max(hi_c, key=lambda t: t[1])
        cur = price or candles[-1][4]
        ath = {"price_usd": p_ath, "mcap_usd_est": p_ath * sup_factor if sup_factor else None, "at": dt.datetime.fromtimestamp(ts_ath, BER).isoformat(timespec="minutes"),
               "drawdown_pct_est": round((1 - cur / p_ath) * 100, 1) if p_ath else None,
               "scope": f"seit Beginn der {c_iv}-Candles ({dt.datetime.fromtimestamp(candles[0][0], BER):%d.%m. %H:%M}), Wicks gefiltert"}
        sp = swing_supports(candles, CONFIG["support_swing_k"], CONFIG["support_bounce_min_pct"], CONFIG["support_cluster_pct"])
        below = sorted([s for s in sp if s["price"] < cur], key=lambda s: -s["price"])[:3]
        supports = [{"price_usd": s["price"], "mcap_usd_est": s["price"] * sup_factor if sup_factor else None, "touches": s["touches"],
                     "dist_pct": round((cur / s["price"] - 1) * 100, 1), "last": dt.datetime.fromtimestamp(s["last_ts"], BER).strftime("%d.%m. %H:%M")} for s in below]
        trend = trend_struct(candles)
        vs = [x[5] for x in candles]
        if len(vs) >= 12:
            a, b = sum(vs[-6:]), sum(vs[-12:-6])
            trend["volume_last6_vs_prev6"] = round(a / b, 2) if b else None
    vol_h1, vol_h6, vol_m5 = fnum(vol.get("h1")), fnum(vol.get("h6")), fnum(vol.get("m5"))
    vol_trend = None
    if vol_h1 is not None and vol_h6:
        r = vol_h1 / (vol_h6 / 6); vol_trend = {"h1_vs_avg_h6": round(r, 2), "label": "steigend" if r >= 1.2 else "fallend" if r < 0.7 else "stabil"}

    # ---- score
    C = CONFIG; comp = {}; why = {}
    def ratio(b, s): return (b / s) if b is not None and s else (None if b is None else (9.9 if b else None))
    # safety
    if rc is None: sfs = C["max"]["safety"] // 2; why["safety"] = ["RugCheck nicht erreichbar – Sicherheit unbekannt"]
    else:
        S = C["safety"]; sfs = C["max"]["safety"]; why["safety"] = []
        p = min(S["warn_penalty_max"], S["warn_penalty"] * len([w for w in warn if w.startswith("RugCheck")]))
        if p: sfs -= p; why["safety"].append(f"-{p} RugCheck-Warnungen")
        if top10 is not None and top10 > S["top10_hi"]: sfs -= S["top10_hi_pen"]; why["safety"].append(f"-{S['top10_hi_pen']} Top10 {top10:.0f}%")
        elif top10 is not None and top10 > S["top10_mid"]: sfs -= S["top10_mid_pen"]; why["safety"].append(f"-{S['top10_mid_pen']} Top10 {top10:.0f}%")
        if creator_pct and creator_pct > S["creator_warn_pct"]: sfs -= S["creator_pen"]; why["safety"].append(f"-{S['creator_pen']} Creator {creator_pct:.1f}%")
        if not any(k in soc for k in ("twitter", "telegram", "website")): sfs -= S["no_socials_pen"]; why["safety"].append(f"-{S['no_socials_pen']} keine Socials")
        if lp_locked is not None and lp_locked < S["lp_lock_warn_pct"]: sfs -= S["lp_lock_pen"]; why["safety"].append(f"-{S['lp_lock_pen']} LP-Lock {lp_locked:.0f}%")
        if meta_mutable: sfs -= S["mutable_meta_pen"]; why["safety"].append(f"-{S['mutable_meta_pen']} Metadaten änderbar")
        if danger: sfs = 0; why["safety"].append("0: Danger-Befund")
    comp["safety"] = max(0, sfs)
    # liquidity
    L = C["liquidity"]
    if on_curve: lq = L["curve_points"]; why["liquidity"] = ["Bonding Curve (Liquidität strukturell vorhanden)"]
    elif liq and mcap:
        rt = liq / mcap; lq = next(p for th, p in L["ratio_steps"] if rt >= th); why["liquidity"] = [f"Liq/MC {rt:.2f}"]
    else: lq = 0; why["liquidity"] = ["keine Liquiditätsdaten"]
    if liq is not None and liq < L["abs_low_usd"] and not on_curve: lq = max(0, lq - L["abs_low_pen"]); why["liquidity"].append(f"-{L['abs_low_pen']} Liq < {L['abs_low_usd']:,.0f}$")
    comp["liquidity"] = lq
    # momentum
    M = C["momentum"]; mo = 0; why["momentum"] = []; h1 = fnum(pc.get("h1")); h6 = fnum(pc.get("h6"))
    if h1 is not None:
        if M["h1_sweet"][0] <= h1 <= M["h1_sweet"][1]: mo += M["pts_h1_sweet"]; why["momentum"].append(f"+{M['pts_h1_sweet']} 1h {h1:+.0f}%")
        elif 0 <= h1 < M["h1_sweet"][0]: mo += M["pts_h1_flat"]; why["momentum"].append(f"+{M['pts_h1_flat']} 1h {h1:+.0f}% (flach)")
        elif M["h1_dip_floor"] <= h1 < 0: mo += M["pts_h1_dip"]; why["momentum"].append(f"+{M['pts_h1_dip']} 1h {h1:+.0f}% (Dip)")
        elif h1 > M["h1_sweet"][1]: mo += M["pts_h1_hot"]; why["momentum"].append(f"+{M['pts_h1_hot']} 1h {h1:+.0f}% (überhitzt)")
        else: why["momentum"].append(f"+0 1h {h1:+.0f}%")
    if h6 is not None and h6 > 0: mo += M["pts_h6_pos"]; why["momentum"].append(f"+{M['pts_h6_pos']} 6h positiv")
    if vol_trend and vol_trend["label"] != "fallend": mo += M["pts_vol_rising"]; why["momentum"].append(f"+{M['pts_vol_rising']} Volumen {vol_trend['label']}")
    if trend.get("higher_lows"): mo += M["pts_trend_up"]; why["momentum"].append(f"+{M['pts_trend_up']} höhere Tiefs")
    elif trend["label"].startswith("Seitwärts"): mo += M["pts_trend_side"]; why["momentum"].append(f"+{M['pts_trend_side']} seitwärts")
    else: why["momentum"].append(f"+0 Trend: {trend['label']}")
    comp["momentum"] = mo
    # flow
    F = C["flow"]; fl = 0; why["flow"] = []
    b1, s1 = bs("h1"); r1 = ratio(b1, s1)
    if r1 is not None:
        p = next((p for th, p in F["bs_h1_steps"] if r1 >= th), 0)
        if r1 > C["bs_suspicious"]: p = C["pts_bs_suspicious"]; why["flow"].append(f"+{p} Buys/Sells 1h {r1:.2f} (auffällig hoch, Micro-Buy-Bots?)")
        else: why["flow"].append(f"+{p} Buys/Sells 1h {r1:.2f}")
        fl += p
    b5, s5 = bs("m5"); r5 = ratio(b5, s5)
    if r5 is not None and r5 >= F["bs_m5_min"]: fl += F["pts_bs_m5"]; why["flow"].append(f"+{F['pts_bs_m5']} Buys/Sells 5m {r5:.2f}")
    ubpb = None
    if ub and ub.get("tx_h1") and (ub["tx_h1"].get("buys") or 0) > 0:
        ubpb = (ub["tx_h1"].get("buyers") or 0) / ub["tx_h1"]["buys"]
        p = next((p for th, p in F["ubpb_steps"] if ubpb >= th), 0); fl += p; why["flow"].append(f"+{p} Unique Buyer/Buy {ubpb:.2f}")
    else: fl += F["pts_ubpb_unknown"]; why["flow"].append(f"+{F['pts_ubpb_unknown']} Unique Buyers unbekannt (neutral)")
    comp["flow"] = fl
    # entry
    E = C["entry"]; why["entry"] = []
    dd = (ath or {}).get("drawdown_pct_est")
    if dd is not None and dd >= E["dead_dd_pct"]: en = E["pts_dead"]; why["entry"].append(f"{dd:.0f}% unter ATH (tot?)")
    elif dd is not None and dd < E["chase_dd_pct"] and (h1 or 0) > E["chase_h1_pct"]: en = E["pts_chase"]; why["entry"].append("am ATH nach starkem Pump (FOMO-Einstieg)")
    elif supports:
        d0 = supports[0]["dist_pct"]
        en = E["pts_near"] if d0 <= E["near_support_pct"] else E["pts_mid"] if d0 <= E["mid_support_pct"] else E["pts_far"]
        why["entry"].append(f"{d0:.0f}% über Support")
    else: en = E["pts_no_support"]; why["entry"].append("kein Support erkennbar")
    comp["entry"] = en
    raw_score = sum(comp.values())
    caps = []
    if danger: caps.append((C["danger_cap"], "Danger: " + "; ".join(danger[:3])))
    if rc is None: caps.append((C["unknown_safety_cap"], "RugCheck nicht erreichbar"))
    if age_h is not None and age_h * 60 < C["young_age_min"]: caps.append((C["young_cap"], f"jünger als {C['young_age_min']} min"))
    wash = []
    if liq and not on_curve and fnum(vol.get("h24")) and fnum(vol.get("h24")) / liq > C["wash_vol_liq_max"]: wash.append(f"Vol24/Liq {fnum(vol['h24']) / liq:.0f}x")
    if ubpb is not None and ubpb < C["bot_buyers_per_buy_min"]: wash.append(f"Unique Buyer/Buy {ubpb:.2f} (Bots)")
    if wash: caps.append((C["wash_cap"], "Wash/Bot-Verdacht: " + ", ".join(wash)))
    if trend["label"].startswith("Abwärtstrend"): caps.append((C["downtrend_cap"], "Abwärtstrend im Chart"))
    if dd is not None and dd < C["entry"]["chase_dd_pct"] and (h1 or 0) > C["entry"]["chase_h1_pct"]: caps.append((C["chase_cap"], "am ATH nach starkem Pump"))
    if (h1 or 0) > C["overheated_h1_pct"]: caps.append((C["overheated_cap"], f"überhitzt (1h {h1:+.0f}%)"))
    if ubpb is None and main: caps.append((C["no_unique_buyers_cap"], "Unique Buyers unbekannt (Bot-Check fehlt)"))
    if not main: caps.append((0, "keine Marktdaten"))
    score = raw_score
    for cap, _ in caps: score = min(score, cap)
    score = int(round(score))

    # ---- plan (levels from real supports / ATH, expressed as MC + price)
    def lvl(mc): return {"mcap_usd": mc, "price_usd": mc / sup_factor if sup_factor and mc else None}
    plan = {"_est": True}
    s1 = supports[0] if supports else None; s2 = supports[1] if len(supports) > 1 else None
    cur_mc = mcap
    target_mc = None
    if ath and ath.get("mcap_usd_est") and cur_mc and ath["mcap_usd_est"] > cur_mc * 1.15: target_mc = ath["mcap_usd_est"] * 0.95
    elif cur_mc: target_mc = cur_mc * 1.5
    if danger:
        plan.update(action="kein Kauf", text="kein Kauf – Sicherheitsrisiko (" + danger[0] + ")")
    elif not main:
        plan.update(action="kein Kauf", text="kein Kauf – keine Marktdaten")
    else:
        entry_mc = s1["mcap_usd_est"] if s1 and s1.get("mcap_usd_est") else (cur_mc * 0.8 if cur_mc else None)
        stop_mc = None
        if entry_mc:
            stop_mc = entry_mc * (1 - C["stop_below_support_pct"] / 100)
            if s2 and s2.get("mcap_usd_est") and s2["mcap_usd_est"] < entry_mc and s2["mcap_usd_est"] > entry_mc * 0.7: stop_mc = s2["mcap_usd_est"] * 0.95
        buy_now = score >= C["buy_min"] and comp["entry"] >= C["buy_requires_entry_pts"]
        if buy_now:
            plan.update(action="Kauf möglich (kleine Position)", entry=lvl(cur_mc), stop=lvl(stop_mc if s1 and s1["dist_pct"] <= 25 else cur_mc * 0.8), target=lvl(target_mc))
        else:
            plan.update(action="kein Kauf jetzt" if score < C["dip_min"] else "nur bei Dip/Bestätigung" if score < C["buy_min"] else "Score hoch, aber nicht hinterherkaufen", entry=lvl(entry_mc), stop=lvl(stop_mc), target=lvl(target_mc))
        plan["entry_basis"] = "Support aus OHLCV" if s1 else "kein Support erkennbar -> -20% vom aktuellen MC (Schätzung)"
        plan["target_basis"] = "95% des ATH-MC" if ath and target_mc and ath.get("mcap_usd_est") and target_mc < ath["mcap_usd_est"] else "+50% (kein höheres ATH bekannt)"
        e, st, tg = plan.get("entry") or {}, plan.get("stop") or {}, plan.get("target") or {}
        if buy_now: lead = f"Kauf möglich bei ~{fmc(cur_mc)} MC"
        else: lead = f"{plan['action']}; Einstieg erst bei Dip auf ~{fmc(e.get('mcap_usd'))} MC" + (" (Support)" if s1 else " (kein Support, -20%)")
        plan["text"] = f"{lead}, Stop bei ~{fmc(st.get('mcap_usd'))}, Ziel ~{fmc(tg.get('mcap_usd'))}"
    # reason + improvements
    lost = sorted(((C["max"][k] - v, k) for k, v in comp.items()), reverse=True)
    hints = []
    if not main: hints.append("Marktdaten (DexScreener) wieder verfügbar / Coin gelistet – dann erneut prüfen")
    if danger: hints.append("Danger-Befunde müssen weg (" + "; ".join(danger[:2]) + ") – sonst bleibt der Score ≤ 15%")
    if wash: hints.append("echtes Orderflow statt Wash/Bots (" + ", ".join(wash) + ")")
    CAPHINT = {"Abwärtstrend": "Trendwende abwarten (neues höheres Tief)", "am ATH": "Rücksetzer auf einen Support abwarten",
               "überhitzt": "Abkühlung nach dem Pump abwarten", "Unique Buyers unbekannt": "Unique-Buyer-Check (in ~1 min erneut ausführen, wenn GT-Slot frei)",
               "jünger als": "Coin älter als 15 min werden lassen", "RugCheck nicht": "RugCheck erreichbar (erneut versuchen)"}
    for _, r_ in sorted(caps):
        h_ = next((v for k, v in CAPHINT.items() if r_.startswith(k)), None)
        if h_ and h_ not in hints: hints.append(h_)
    for gap, k in (lost if main else []):
        if gap <= 2 or len(hints) >= 5: continue
        hints.append({"safety": "sauberere Holder-Verteilung / weniger RugCheck-Warnungen / Socials",
                      "liquidity": "mehr Liquidität im Verhältnis zum MC",
                      "momentum": "höhere Tiefs im Chart + steigendes Volumen",
                      "flow": ("natürlicheres Buy/Sell-Verhältnis (aktuell auffällig hoch → Bot-Verdacht)" if r1 and r1 > C["bs_suspicious"]
                               else "mehr Käufer als Verkäufer (Buys/Sells > 1,3) und mehr Unique Buyers"),
                      "entry": "Preis nahe an einem Support (≤10% darüber) statt im Niemandsland/am ATH"}[k])
    if danger: reason = "Sicherheits-Gate: " + danger[0]
    elif caps and min(caps)[0] < raw_score: reason = min(caps)[1]
    else:
        DEN = {"safety": "Sicherheit", "liquidity": "Liquidität", "momentum": "Momentum", "flow": "Orderflow", "entry": "Einstieg"}
        reason = f"stärkste Komponente: {DEN[max(comp, key=lambda k: comp[k] / C['max'][k])]}, schwächste: {DEN[lost[0][1]]}"

    venue = VENUES.get(dex, dex)
    report = {
        "ok": True, "generated_at": dt.datetime.now(BER).isoformat(timespec="seconds"), "input": raw, "input_resolved_via": note,
        "input_was_pool": input_pool,
        "basics": {
            "name": ((main or {}).get("baseToken") or {}).get("name") or ((rc or {}).get("tokenMeta") or {}).get("name"),
            "symbol": ((main or {}).get("baseToken") or {}).get("symbol") or ((rc or {}).get("tokenMeta") or {}).get("symbol"),
            "mint": mint, "main_pool": pool, "venue": venue, "dex_id": dex, "dexscreener_url": (main or {}).get("url"),
            "other_pools": [{"pool": p["pairAddress"], "dex": p.get("dexId"), "liq_usd": fnum((p.get("liquidity") or {}).get("usd")),
                             "vol24_usd": fnum((p.get("volume") or {}).get("h24"))} for p in (pairs or []) if p is not main][:5],
            "age_h": round(age_h, 2) if age_h is not None else None, "price_usd": price, "sol_usd": sol_usd,
            "mcap_usd": mcap, "fdv_usd": fdv, "liquidity_usd": liq, "liquidity_note": liq_note,
            "price_change_pct": {k: fnum(pc.get(k)) for k in ("m5", "h1", "h6", "h24")},
            "volume_usd": {k: fnum(vol.get(k)) for k in ("m5", "h1", "h6", "h24")},
            "txns": {k: tx.get(k) for k in ("m5", "h1", "h6", "h24")},
            "unique_buyers": ({"h1": (ub.get("tx_h1") or {}).get("buyers"), "m15": (ub.get("tx_m15") or {}).get("buyers"),
                               "buyers_per_buy_h1": round(ubpb, 3) if ubpb is not None else None, "source": ub.get("src"), "as_of": ub.get("at")} if ub else None),
            "bonding_curve": ({"progress_pct_est": curve["progress_pct_est"], "complete": curve["complete"], "real_sol": round(curve["real_sol"], 3),
                               "pair": curve_pair["pairAddress"], "status": "graduiert" if curve["complete"] else "auf der Curve"} if curve else None),
        },
        "safety": {
            "mint_authority": mint_auth, "freeze_authority": freeze_auth, "transfer_fee_pct": fee_pct, "token_program": (mi or {}).get("program") or (rc or {}).get("tokenProgram"),
            "lp_locked_pct": lp_locked, "lp_note": "Bonding Curve: kein LP" if on_curve else (None if lp_locked is not None else "unbekannt"),
            "top_holder_pct_excl_pools": round(top1, 2) if top1 is not None else None, "top10_pct_excl_pools": round(top10, 2) if top10 is not None else None,
            "creator": creator, "creator_pct": round(creator_pct, 3) if creator_pct is not None else None,
            "insiders_detected": insiders, "insider_holders_in_top": ins_holders, "bundles": bundles or ("keine Bundle-Risiken bei RugCheck" if rc else None),
            "rugcheck_score_normalised": rc_score, "rugcheck_rugged": (rc or {}).get("rugged"), "rugcheck_risks": risks,
            "total_holders": (rc or {}).get("totalHolders"), "metadata_mutable": meta_mutable,
            "socials": {k: soc.get(k) for k in ("twitter", "telegram", "website")} | ({"source": soc["_src"]} if soc.get("_src") else {}),
            "danger": danger, "warnings": warn,
        },
        "momentum": {"_est": True, "ohlcv_source": c_src, "ohlcv_interval": c_iv, "candles": len(candles or []), "trend": trend,
                     "ath": ath, "supports": supports, "volume_trend": vol_trend},
        "verdict": {"_est": True, "kauf_score_pct": score, "raw_score_before_caps": round(raw_score, 1), "components": comp,
                    "component_max": C["max"], "component_reasons": why, "caps_applied": [{"cap": c, "reason": r} for c, r in caps],
                    "reason": reason, "plan": plan, "what_would_raise_score": hints},
        "sources": sources, "warnings": warnings, "runtime_s": round(time.time() - T0, 2), "gt_calls_used": int(sources["ohlcv"].startswith("GeckoTerminal (live") or sources["unique_buyers"].startswith("GeckoTerminal (live")),
    }
    return report

# ----------------------------------------------------------------------------- German text
def fmc(x):
    if x is None: return "?"
    if x >= 1e9: return f"{x / 1e9:.2f} Mrd $".replace(".", ",")
    if x >= 1e6: return f"{x / 1e6:.2f} Mio $".replace(".", ",")
    if x >= 1e3: return f"{x / 1e3:.1f}k $".replace(".", ",")
    return f"{x:.0f} $"

def fpx(p):
    if not p: return "?"
    if p >= 1: return f"{p:.4f} $".replace(".", ",")
    s = f"{p:.{max(2, -int(math.floor(math.log10(p))) + 3)}f}"; return s.replace(".", ",") + " $"

def fage(h): return f"{h * 60:.0f} min" if h < 1 else f"{h:.1f} h".replace(".", ",") if h < 48 else f"{h / 24:.1f} Tage".replace(".", ",")

def fde(x, d=1): return "?" if x is None else f"{x:.{d}f}".replace(".", ",")

def fpct(x): return "?" if x is None else f"{x:+.1f}%".replace(".", ",")

def text_de(r):
    b, s, m, v = r["basics"], r["safety"], r["momentum"], r["verdict"]
    de = lambda t: re.sub(r"(\d)\.(\d)", r"\1,\2", t)
    L = [f"🪙 {b['name']} (${b['symbol']}) – {b['venue'] or 'kein Pool/Marktdaten'}",
         f"MC {fmc(b['mcap_usd'])} | Liq {fmc(b['liquidity_usd'])} | Alter {fage(b['age_h'])}" if b["age_h"] is not None else f"MC {fmc(b['mcap_usd'])} | Liq {fmc(b['liquidity_usd'])}",
         f"Preis {fpx(b['price_usd'])} | 5m {fpct(b['price_change_pct']['m5'])} 1h {fpct(b['price_change_pct']['h1'])} 6h {fpct(b['price_change_pct']['h6'])} 24h {fpct(b['price_change_pct']['h24'])}"]
    t1 = b["txns"].get("h1") or {}
    line = f"Vol 1h {fmc(b['volume_usd']['h1'])} / 24h {fmc(b['volume_usd']['h24'])} | Buys/Sells 1h {t1.get('buys', '?')}/{t1.get('sells', '?')}"
    if b["unique_buyers"]: line += f" | Unique Buyer 1h {b['unique_buyers']['h1']}"
    L.append(line)
    if b["bonding_curve"]: L.append(f"Bonding Curve: {b['bonding_curve']['progress_pct_est']:.0f}% ({b['bonding_curve']['status']}, geschätzt)")
    so = [k for k in ("twitter", "telegram", "website") if s["socials"].get(k)]
    L.append(f"🛡 Sicherheit: Mint {'❌ aktiv' if s['mint_authority'] else '✅ aus'}, Freeze {'❌ aktiv' if s['freeze_authority'] else '✅ aus'}, "
             f"LP {('%.0f%% gelockt' % s['lp_locked_pct']) if s['lp_locked_pct'] is not None else (s['lp_note'] or '?')}, "
             f"Top-Holder {fde(s['top_holder_pct_excl_pools'])}% / Top10 {fde(s['top10_pct_excl_pools'])}%, "
             f"Dev {fde(s['creator_pct'])}%, RugCheck {s['rugcheck_score_normalised'] if s['rugcheck_score_normalised'] is not None else '?'}/100 (niedrig=gut), "
             f"Socials: {', '.join(so) if so else 'keine'}")
    if s["danger"]: L.append("⛔ " + de("; ".join(s["danger"])))
    elif s["warnings"]: L.append("⚠️ " + "; ".join(s["warnings"][:3]))
    a = m.get("ath")
    tl = f"📈 Trend: {m['trend']['label']}"
    if a: tl += f" | ATH {fmc(a['mcap_usd_est'])} MC, jetzt {a['drawdown_pct_est']:.0f}% darunter".replace(".", ",")
    if m["supports"]: tl += " | Supports: " + ", ".join(fmc(x["mcap_usd_est"]) for x in m["supports"][:3])
    if m.get("volume_trend"): tl += f" | Volumen {m['volume_trend']['label']}"
    L.append(tl + " (geschätzt)")
    c = v["components"]; mx = v["component_max"]
    L.append(f"🎯 Kauf-Score: {v['kauf_score_pct']}% (Sicherheit {c['safety']}/{mx['safety']}, Liquidität {c['liquidity']}/{mx['liquidity']}, "
             f"Momentum {c['momentum']}/{mx['momentum']}, Orderflow {c['flow']}/{mx['flow']}, Einstieg {c['entry']}/{mx['entry']}"
             + (f"; gedeckelt: {', '.join(str(x['cap']) + '%' for x in v['caps_applied'])}" if v["caps_applied"] else "") + ")")
    L.append(de(f"Grund: {v['reason']}"))
    p = v["plan"]; L.append(de(f"Plan: {p['text']}"))
    if p.get("entry") and p["entry"].get("price_usd"):
        L.append(f"   (Preis: Einstieg {fpx(p['entry']['price_usd'])}, Stop {fpx((p.get('stop') or {}).get('price_usd'))}, Ziel {fpx((p.get('target') or {}).get('price_usd'))})")
    if v["what_would_raise_score"]: L.append("Was würde den Score erhöhen: " + de("; ".join(v["what_would_raise_score"])))
    if r["warnings"]: L.append("Hinweis: " + "; ".join(str(w) for w in r["warnings"][:3]))
    L.append(f"Mint: {b['mint']}")
    L.append("Alles mit 'geschätzt' ist berechnet, keine Anlageberatung.")
    return "\n".join(L)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args or "--help" in flags or "-h" in sys.argv:
        print(__doc__); sys.exit(0 if args or "--help" in flags else 1)
    try:
        r = analyze(" ".join(args), use_gt="--no-gt" not in flags)
        print(text_de(r) if "--text" in flags else json.dumps(r, ensure_ascii=False, indent=1, default=str))
    except UserError as e:
        out = {"ok": False, "error": e.code, "message_de": e.de, "message": e.en, "runtime_s": round(time.time() - T0, 2)}
        print(("❌ " + e.de) if "--text" in flags else json.dumps(out, ensure_ascii=False, indent=1)); sys.exit(2)
    except requests.RequestException as e:
        msg = f"API nicht erreichbar ({type(e).__name__}) – bitte später erneut versuchen."
        print(("❌ " + msg) if "--text" in flags else json.dumps({"ok": False, "error": "api_down", "message_de": msg, "message": str(e)[:200]}, ensure_ascii=False)); sys.exit(3)

if __name__ == "__main__":
    main()
