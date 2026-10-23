#!/usr/bin/env python3
"""NEW PAIRS sleeve (PAPER, simulated fills) — 2026-10-20, user request.
Fresh pump.fun launches (age 2..15 min, still on the bonding curve, SOL-quoted) with a VERY strong narrative
(famous people / trending on X / classic memes), then the strictest safety gates of the desk.
  run   : every minute (own cron line, flock .newpairs.lock), schedule ends 2026-10-28 01:40 Berlin (same end as the meme sleeve)
  dry   : full evaluation incl. RugCheck, no position/decision writes, prints a summary
Data (keyless, public): pump.fun frontend-api-v3 /coins?sort=created_timestamp (3 pages = newest 150 launches, ~4-5 min),
/coins-v2/<mint> (fresh curve state), /coins?creator=<dev> (dev launch history), swap-api.pump.fun /v2/coins/<mint>/trades
(buyers, sells, dev sells, first-block snipers), RugCheck report (shared cache with meme.py). 0 GeckoTerminal calls.
Positions live in meme_positions.json (sleeve="newpairs") so bank, RISK (every minute in meme.py), cooldown and DD are shared."""
import os, sys, re, json, time, fcntl, math, datetime as dt, requests
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.expanduser('~/.desk')); from leads import lead_id, ltag   # 2026-10-20 research upgrade: lead IDs
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
BER = ZoneInfo("Europe/Berlin"); UTC = dt.timezone.utc
PF = "https://frontend-api-v3.pump.fun"; SWAP = "https://swap-api.pump.fun"
UA = {"User-Agent": "Mozilla/5.0 (desk-meme/1.0)", "Accept": "application/json"}
NATIVE = "11111111111111111111111111111111"; WSOL = "So11111111111111111111111111111111111111112"
STATIC = f"{DESK}/scan/narratives_static.json"; TRENDING = f"{DESK}/scan/narratives_trending.json"
SEEN = f"{DESK}/scan/newpairs_seen.json"; TRCACHE = f"{DESK}/scan/newpairs_trades.json"; DEVCACHE = f"{DESK}/scan/newpairs_devs.json"
LATEST = f"{DESK}/scan/newpairs_latest.json"; DEC_LOG = f"{DESK}/scan/newpairs-{{}}.jsonl"
SCHEDULE_END = dt.datetime(2026, 10, 28, 1, 40, tzinfo=BER)
# ---- universe ----
FEED_PAGES = 3; AGE_MIN, AGE_MAX = 2.0, 15.0; PREFETCH_AGE_MIN = 0.5; SEEN_KEEP_MIN = 75
# ---- narrative ----
PTS_PER_W = 7; DESC_FACTOR = 0.7; EXTRA_MATCH_PTS, EXTRA_MATCH_MAX = 3, 9; TRENDING_BONUS = 10; TRENDING_MAX_AGE_H = 3.0
X_PROFILE, X_STATUS, X_COMMUNITY, WEB_REAL, WEB_LAUNCHPAD, TG = 10, 6, 6, 6, 2, 3
NO_SOCIALS, NO_IMAGE, COPYCAT, COPYCAT_CROWD, IMPERSONATE, OFFICIAL, SPAM, BOTDEPLOY = -20, -10, -30, -5, -25, -15, -10, -10
THRESHOLD = 70; STRONG = 85
# ---- safety / traction ----
MIN_BUYERS = 25; PROGRESS = (5.0, 60.0); SNIPER_MAX_PCT = 10.0; SNIPER_SLOTS = 2
DEV_24H_MAX = 2; DEV_7D_MAX = 9; DEV_TTL = 1800
TRADE_PAGES = 3; DEEP_MAX = 6; RUN_BUDGET_S = 45
INIT_REAL_TOKENS = 793_100_000 * 10**6; TOTAL_SUPPLY_UI = 1_000_000_000
# ---- size / exits ----
TICKET_PCT = 0.015; NP_MAX_OPEN = 3; TOTAL_MAX_OPEN = 8   # 2026-10-21 user order: more trades
EXIT_TIERS = {   # gains relative to entry fill; tp fractions are of the INITIAL qty
 # USER ORDER 2026-10-24 01:24 (Dominic): both tiers use the main regime (meme.EXIT_REGIME): TP1 +30% 1/3, TP2 +60% 1/3, last 1/3
 # runs; after any TP a FIXED stop at entry -20%; no trailing (the old trail/trail_tight/trail_after_time_stop and the STRONG
 # +100%/+300% ladder with a 35% trail are removed). Initial stop 0.30 (open_position). Time stops/max hold unchanged.
 "normal": {"tier": "normal", "regime": None, "tp": None, "post_tp_stop": None, "time_stop_min": 30, "time_stop_only_if_not_profit": True, "max_hold_min": 720},
 "strong": {"tier": "strong", "regime": None, "tp": None, "post_tp_stop": None, "time_stop_min": 180, "time_stop_only_if_not_profit": True, "max_hold_min": 720}}
# the full plan (regime, tp, post_tp_stop) is filled in by meme.regime_plan(EXIT_TIERS[tier]) at entry (single source: meme.EXIT_*)
SAFETY_RC_EVERY_S = 300; VOL_COLLAPSE_MIN_TRADES_10M = 3
# shadow book (upgrade 3): narrative passers that fail exactly ONE safety gate, or are blocked by max-open / one buy per run
SHADOW_RC_NEW = 2          # extra RugCheck calls per run to confirm a 1-cheap-fail coin has no RugCheck fail (cache shared, 10 min)
DATA_FAILS = ("rule 7 · no first-candle data", "not judged: rule", "curve state n/a", "dev history unavailable", "rugcheck unavailable", "coin data unavailable", "curve complete", "banned")
T0 = time.time()

def now(): return dt.datetime.now(UTC)
def jload(p, d):
    try: return json.load(open(p))
    except (FileNotFoundError, ValueError): return d
def jsave(p, d):
    tmp = p + ".tmp"; json.dump(d, open(tmp, "w"), default=str, separators=(",", ":")); os.replace(tmp, p)
def get(url, params=None, timeout=6):
    r = requests.get(url, params=params, headers=UA, timeout=timeout); r.raise_for_status(); return r.json()
def log(line, dry=False):
    if dry: print("[DRY] " + line); return
    with open(f"{DESK}/logs/meme.log", "a") as f: f.write(f"{now().astimezone(BER):%Y-%m-%d %H:%M:%S %Z} {line}\n")
    print(line)

# ================= narrative =================
def norm(s): return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
def squash(s): return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def load_trending():
    d = jload(TRENDING, None)
    if not d: return [], "trending file missing"
    try:
        age = (now() - dt.datetime.fromisoformat(str(d["updated_at"]).replace("Z", "+00:00"))).total_seconds() / 3600
    except Exception: return [], "trending file: bad updated_at"
    if age > TRENDING_MAX_AGE_H: return [], f"trending file stale ({age:.1f}h > {TRENDING_MAX_AGE_H:.0f}h, ignored)"
    out = []
    for t in d.get("topics") or []:
        term = norm(str(t.get("term", "")).lstrip("#$"))
        try: w = max(1, min(10, int(float(t.get("weight", 5)))))
        except (TypeError, ValueError): w = 5
        if len(squash(term)) >= 3: out.append({"term": term, "w": w, "src": t.get("source", "?")})
    return out, f"trending ok ({len(out)} topics, {age:.1f}h old)"

def build_terms(static, trending):
    terms = []   # (alias_norm, alias_squash, term, w, cat)
    for cat, c in static["categories"].items():
        for term, v in c["terms"].items():
            for a in set([term] + v.get("aliases", [])):
                terms.append((norm(a), squash(a), term, v["w"], cat))
    for t in trending:
        for v in {t["term"], " ".join(w[:-1] if len(w) > 4 and w.endswith("s") else w for w in t["term"].split())}:   # 'glowing chickens' ~ 'glowing chicken'
            terms.append((v, squash(v), t["term"], t["w"], "trending:" + t["src"]))
    return terms

def _host(u):
    m = re.match(r"https?://([^/]+)", (u or "").strip().lower()); return (m.group(1) if m else "").removeprefix("www.")

def narrative(c, terms, static, groups):
    """Returns (score 0..100, matched [{term,cat,w,field}], reasons [str])."""
    name, sym, desc = c.get("name") or "", c.get("symbol") or "", c.get("description") or ""
    fields = {"symbol": (norm(sym), squash(sym)), "name": (norm(name), squash(name)), "desc": (norm(desc), "")}
    matched = {}
    for a_n, a_s, term, w, cat in terms:
        if not a_n: continue
        for f, (txt, sq) in fields.items():
            hit = bool(re.search(r"(?<![a-z0-9])" + re.escape(a_n) + r"(?![a-z0-9])", txt))
            if not hit and f != "desc" and len(a_s) >= 4 and " " not in txt and a_s in sq: hit = True   # TRUMPCAT, ELONDOGE
            if hit:
                pts = w * PTS_PER_W * (1.0 if f != "desc" else DESC_FACTOR)
                k = (term, cat)
                if k not in matched or pts > matched[k]["pts"]: matched[k] = {"term": term, "cat": cat, "w": w, "field": f, "pts": round(pts, 1)}
                break
    m = sorted(matched.values(), key=lambda x: -x["pts"]); reasons = []; score = 0.0
    if m:
        score = m[0]["pts"]; reasons.append(f"{m[0]['term']} ({m[0]['cat']}, w{m[0]['w']}, {m[0]['field']}) +{m[0]['pts']:.0f}")
        extra = min(EXTRA_MATCH_MAX, EXTRA_MATCH_PTS * len({x["term"] for x in m[1:]}))
        if extra: score += extra; reasons.append(f"+{extra} extra matches")
        if any(x["cat"].startswith("trending") for x in m): score += TRENDING_BONUS; reasons.append(f"+{TRENDING_BONUS} trending on X now")
    else: reasons.append("no narrative match")
    imp = static.get("impersonation", {}); hosts = set(static.get("launchpad_website_hosts", []))
    tw, web, tg = (c.get("twitter") or "").strip(), (c.get("website") or "").strip(), (c.get("telegram") or "").strip()
    soc = 0
    if tw and _host(tw) in ("x.com", "twitter.com"):
        path = re.sub(r"^https?://[^/]+/", "", tw).split("?")[0].strip("/")
        handle = path.split("/")[0].lower()
        if "/status/" in tw: soc += X_STATUS; reasons.append(f"+{X_STATUS} X post linked (@{handle})")
        elif path.startswith("i/communities"): soc += X_COMMUNITY; reasons.append(f"+{X_COMMUNITY} X community")
        elif handle in imp.get("celeb_handles", []): score += IMPERSONATE; reasons.append(f"{IMPERSONATE} impersonation: X link is @{handle}'s own account")
        elif handle: soc += X_PROFILE; reasons.append(f"+{X_PROFILE} own X account @{handle}")
    if web:
        h = _host(web)
        if h and not any(h == x or h.endswith("." + x) for x in hosts): soc += WEB_REAL; reasons.append(f"+{WEB_REAL} website {h}")
        elif h: soc += WEB_LAUNCHPAD; reasons.append(f"+{WEB_LAUNCHPAD} launchpad page {h}")
    if tg: soc += TG; reasons.append(f"+{TG} telegram")
    if not (tw or web or tg): score += NO_SOCIALS; reasons.append(f"{NO_SOCIALS} no socials")
    score += soc
    if not c.get("image_uri"): score += NO_IMAGE; reasons.append(f"{NO_IMAGE} no image")
    low = (name + " " + desc).lower()
    if m and any(x["cat"] in ("famous_people", "crypto_figures") for x in m) and any(k in low for k in imp.get("official_markers", [])):
        score += OFFICIAL; reasons.append(f"{OFFICIAL} impersonation risk ('official'/'real' claim about a person)")
    if any(k in low for k in imp.get("spam_markers", [])): score += SPAM; reasons.append(f"{SPAM} spam wording")
    if any(k in low for k in imp.get("bot_deployer_markers", [])): score += BOTDEPLOY; reasons.append(f"{BOTDEPLOY} bot-deployed")
    g = groups.get(squash(sym)) or []
    if len(g) > 1:
        leader = g[0]
        if leader != c["mint"]: score += COPYCAT; reasons.append(f"{COPYCAT} copycat: {len(g)} coins with ticker {sym[:12]} in 1h, not the most-traded/first")
        elif len(g) >= 4: score += COPYCAT_CROWD; reasons.append(f"{COPYCAT_CROWD} crowded ticker ({len(g)} in 1h; this is the leader)")
    return max(0, min(100, round(score))), [{k: v for k, v in x.items()} for x in m[:5]], reasons

def ticker_groups(seen):
    """squashed symbol -> [mints] of launches in the last 60 min, leader first (most real SOL in curve, then earliest)."""
    cut = time.time() - 3600; g = {}
    for mnt, c in seen.items():
        if c["created"] / 1000 >= cut: g.setdefault(squash(c.get("symbol")), []).append(c)
    return {k: [x["mint"] for x in sorted(v, key=lambda x: (-(x.get("real_sol") or 0), x["created"]))] for k, v in g.items() if k}

# ================= feeds / state =================
def fetch_feed(errs):
    out = []
    for i in range(FEED_PAGES):
        try:
            out += get(PF + "/coins", {"offset": 50 * i, "limit": 50, "sort": "created_timestamp", "order": "DESC", "includeNsfw": "false"})
        except Exception as e: errs.append(f"feed p{i}: {type(e).__name__}"); break
    return out

KEEP = ("mint", "name", "symbol", "description", "twitter", "telegram", "website", "image_uri", "creator", "bonding_curve", "quote_mint", "program")
def update_seen(seen, feed):
    new = 0; t = time.time()
    for c in feed:
        m = c.get("mint")
        if not m: continue
        e = seen.get(m)
        if not e:
            e = {k: (c.get(k) or "") for k in KEEP}; e["created"] = c.get("created_timestamp") or 0; e["first_seen"] = round(t); new += 1
            e["description"] = e["description"][:400]; seen[m] = e
        e["real_sol"] = (c.get("real_sol_reserves") or 0) / 1e9 if (c.get("quote_mint") or NATIVE) == NATIVE else 0
        e["complete"] = bool(c.get("complete")); e["banned"] = bool(c.get("is_banned")); e["mcap_usd"] = c.get("usd_market_cap")
    cut = (t - SEEN_KEEP_MIN * 60) * 1000
    for m in [m for m, e in seen.items() if e["created"] < cut]: seen.pop(m)
    return new

# ================= safety =================
RPCS = ["https://solana-rpc.publicnode.com", "https://api.mainnet-beta.solana.com"]
def chain_curves(addrs, errs):
    """pump.fun bonding-curve accounts straight from chain (1 getMultipleAccounts call, public keyless RPC).
    Layout: 8B discriminator, virtual_token, virtual_sol, real_token, real_sol, total_supply (u64 LE), complete (bool).
    Virtual SOL differs between curves, so progress is token-based: (793.1M - real_token) / 793.1M."""
    import base64, struct
    addrs = [a for a in addrs if a]
    if not addrs: return {}
    for u in RPCS:
        try:
            r = requests.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts", "params": [addrs, {"encoding": "base64"}]},
                              headers={"User-Agent": "curl/8.5.0 (desk-newpairs)"}, timeout=6).json()
            out = {}
            for a, v in zip(addrs, r["result"]["value"]):
                if not v: continue
                b = base64.b64decode(v["data"][0]); vt, vs, rt, rs, ts = struct.unpack_from("<5Q", b, 8)
                out[a] = {"real_sol": rs / 1e9, "progress": round((793_100_000 - rt / 1e6) / 793_100_000 * 100, 1),
                          "price_sol": (vs / 1e9) / (vt / 1e6) if vt else None, "complete": bool(b[48]), "vsol": vs / 1e9}
            return out
        except Exception as ex: errs.append(f"rpc {u.split('//')[1][:10]}: {type(ex).__name__}")
    return {}

def sol_usd_of(fresh):
    mc, mq = float(fresh.get("usd_market_cap") or 0), float(fresh.get("market_cap_quote") or fresh.get("market_cap") or 0)
    return mc / mq if mc and mq else None

def dev_history(creator, cache, errs):
    e = cache.get(creator)
    if e and time.time() - e["ts"] < DEV_TTL: return e
    try:
        d = get(PF + "/coins", {"creator": creator, "offset": 0, "limit": 50, "sort": "created_timestamp", "order": "DESC", "includeNsfw": "true"})
        ts = [c.get("created_timestamp", 0) / 1000 for c in d if c.get("creator") == creator]
        t = time.time()
        e = {"ts": t, "n": len(ts), "n24": sum(1 for x in ts if t - x < 86400), "n7d": sum(1 for x in ts if t - x < 7 * 86400), "full_page": len(d) >= 50}
        cache[creator] = e; return e
    except Exception as ex: errs.append(f"dev history: {type(ex).__name__}"); return None

def slot_of(t):
    try: return int(str(t.get("slotIndexId", ""))[:13])
    except ValueError: return None

def update_trades(mint, cache, max_pages, errs):
    """Incremental trade cache (newest first API). Fetch the newest page; while the coin's first trade has not been reached,
    continue backwards from the oldest cursor stored in earlier runs (e['cur']). <= max_pages calls per coin per run."""
    e = cache.setdefault(mint, {"tr": {}, "start": False, "ts": 0, "cur": None}); known = e["tr"]; cursor = "0"
    for _ in range(max_pages):
        try: d = get(f"{SWAP}/v2/coins/{mint}/trades", {"limit": 100, "cursor": cursor})
        except Exception as ex: errs.append(f"trades: {type(ex).__name__}"); break
        tr = d.get("trades") or []; hit = False
        oldest_before = min((v[0] for v in known.values()), default=None)
        for t in tr:
            if t["tx"] in known: hit = True; continue
            ts = dt.datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")).timestamp()
            known[t["tx"]] = [round(ts), t.get("userAddress"), t.get("type"), float(t.get("baseAmount") or 0), slot_of(t), float(t.get("amountSol") or 0)]
        pg = d.get("pagination") or {}; nxt = pg.get("nextCursor")
        page_oldest = min((dt.datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")).timestamp() for t in tr), default=None)
        extends_back = oldest_before is None or (page_oldest is not None and page_oldest <= oldest_before)
        if not pg.get("hasMore"):
            if extends_back or not hit: e["start"] = True
            if extends_back: break
        if extends_back: e["cur"] = nxt
        if e["start"]:
            if hit or not nxt: break
            cursor = nxt; continue          # gap between newest page and known trades (very busy coin)
        if hit: cursor = e.get("cur") or nxt  # newest part known -> resume the backward walk
        else: cursor = nxt
        if not cursor: break
    e["ts"] = time.time(); return e

def trade_stats(e, creator):
    tr = list(e["tr"].values())
    buys = [t for t in tr if t[2] == "buy"]; sells = [t for t in tr if t[2] == "sell"]
    buyers = {t[1] for t in buys if t[1] != creator}
    dev_sold = any(t[1] == creator for t in sells)
    st = {"trades": len(tr), "buys": len(buys), "sells": len(sells), "buyers": len(buyers), "dev_sold": dev_sold, "start_known": e["start"]}
    if e["start"] and tr:
        s0 = min(t[4] for t in tr if t[4] is not None) if any(t[4] is not None for t in tr) else None
        if s0 is not None:
            snip = sum(t[3] for t in buys if t[1] != creator and t[4] is not None and t[4] < s0 + SNIPER_SLOTS)
            st["sniper_pct"] = round(snip / TOTAL_SUPPLY_UI * 100, 2)
            st["dev_buy_pct"] = round(sum(t[3] for t in buys if t[1] == creator) / TOTAL_SUPPLY_UI * 100, 2)
    return st

def safety(c, fresh, cs, dev, ts, rc_fn, rc_gates):
    """Returns (fails list, info dict). RugCheck only when everything cheap passes."""
    f = []
    if fresh.get("complete"): f.append("curve complete (graduated)")
    if fresh.get("is_banned"): f.append("banned on pump.fun")
    sv = (fresh.get("security_verdict") or {}).get("verdict")
    if sv and sv != "allow": f.append(f"pump.fun security verdict {sv}")
    if int(fresh.get("transfer_fee_bps") or 0) != 0: f.append("transfer fee")
    if cs and cs.get("complete"): f.append("curve complete (on chain)")
    prog = cs["progress"] if cs else None
    info = {"progress": round(prog, 1) if prog is not None else None, **ts}
    if prog is None: f.append("curve state n/a (RPC)")
    elif not (PROGRESS[0] <= prog <= PROGRESS[1]): f.append(f"curve progress {prog:.0f}% outside {PROGRESS[0]:.0f}..{PROGRESS[1]:.0f}%")
    if ts["buyers"] < MIN_BUYERS: f.append(f"unique buyers {ts['buyers']} < {MIN_BUYERS}")
    if ts["buys"] <= ts["sells"]: f.append(f"buys {ts['buys']} <= sells {ts['sells']}")
    if ts["dev_sold"]: f.append("dev has sold")
    if not ts["start_known"]: f.append("first-block snipers unknown (trade history not reached)")
    elif ts.get("sniper_pct") is not None and ts["sniper_pct"] > SNIPER_MAX_PCT: f.append(f"first-{SNIPER_SLOTS}-block snipers/bundle {ts['sniper_pct']:.1f}% > {SNIPER_MAX_PCT:.0f}%")
    if dev is None: f.append("dev history unavailable")
    else:
        info["dev"] = {k: dev[k] for k in ("n", "n24", "n7d")}
        o24 = dev["n24"] - 1; o7 = dev["n7d"] - 1
        if o24 > DEV_24H_MAX or o7 > DEV_7D_MAX or dev.get("full_page"): f.append(f"serial launcher: dev made {o24} other coins in 24h / {o7} in 7d")
    if f: return f, info
    # USER ORDER 2026-10-21 19:34/19:37: rule 7 (first candle at launch = giant pump -> skip; no data -> skip) + rule 8 (bot-wash)
    try:
        import rugpattern
        rp, notes = rugpattern.check(c["mint"], newpairs=True)
    except Exception as ex:
        rp, notes = [f"rule 7 · no first-candle data (check error {type(ex).__name__})"], []
    if notes: info["rugpattern_notes"] = notes
    if rp: return f + rp, info
    try:
        rep, _ = rc_fn(c["mint"])
        g = rc_gates({"venue": "bonding_curve", "pool": c["bonding_curve"]}, rep)
        info["rc_score"] = rep.get("score_normalised")
        if g: f += ["rugcheck: " + x for x in g]
    except Exception as ex: f.append(f"rugcheck unavailable ({ex}) -> no buy")
    return f, info

# ================= risk hook (called by meme.risk for sleeve=newpairs positions) =================
def position_safety(o):
    """Safety/rug exits for a held new pair: dev sold since entry, volume collapse, RugCheck danger appearing. Returns reason or None."""
    import meme
    mint, dev = o["token"], o.get("creator")
    try:
        d = get(f"{SWAP}/v2/coins/{mint}/trades", {"limit": 100, "cursor": "0"}, timeout=5); tr = d.get("trades") or []
        et = dt.datetime.fromisoformat(o["entry_time"]).timestamp(); t = time.time()
        for x in tr:
            ts = dt.datetime.fromisoformat(x["timestamp"].replace("Z", "+00:00")).timestamp()
            if dev and x.get("userAddress") == dev and x.get("type") == "sell" and ts >= et - 60: return "safety exit: dev wallet sold"
        n10 = sum(1 for x in tr if t - dt.datetime.fromisoformat(x["timestamp"].replace("Z", "+00:00")).timestamp() <= 600)
        if t - et >= 600 and n10 < VOL_COLLAPSE_MIN_TRADES_10M: return f"safety exit: volume collapse ({n10} trades in 10 min)"
    except Exception: pass
    if time.time() - (o.get("np_rc_at") or 0) >= SAFETY_RC_EVERY_S:
        try:
            rep, _ = meme.rugcheck_report(mint); o["np_rc_at"] = time.time()
            bad = []
            if rep.get("rugged"): bad.append("rugged")
            if rep.get("mintAuthority") or (rep.get("token") or {}).get("mintAuthority"): bad.append("mint authority")
            if rep.get("freezeAuthority") or (rep.get("token") or {}).get("freezeAuthority"): bad.append("freeze authority")
            bad += [x.get("name") for x in rep.get("risks") or [] if x.get("level") == "danger"]
            if bad: return "safety exit: RugCheck " + ", ".join(map(str, bad))[:80]
        except Exception: pass
    return None

def pf_price(o):
    """Price for a held new pair DexScreener/GT don't index yet: bonding curve from chain x SOL/USD (pump.fun coins-v2 ratio)."""
    cs = chain_curves([o["pool"]], []).get(o["pool"])
    if not cs or not cs.get("price_sol") or cs.get("complete"): return None
    try: sol = sol_usd_of(get(f"{PF}/coins-v2/{o['token']}", timeout=5)) or o.get("sol_usd")
    except Exception: sol = o.get("sol_usd")
    px = cs["price_sol"] * sol
    return {"base_token_price_usd": px, "quote_token_price_usd": sol, "reserve_in_usd": cs["real_sol"] * sol, "market_cap_usd": px * TOTAL_SUPPLY_UI,
            "volume_usd": {}, "_src": "chain+pump.fun", "_migrated_to": None, "pool_created_at": None}

# ================= run =================
def run(dry=False):
    import meme, scan
    if dt.datetime.now(BER) >= SCHEDULE_END: return
    errs = []; static = jload(STATIC, None)
    if not static: log("[NEWPAIRS] narratives_static.json missing -> skip", dry); return
    trending, tstat = load_trending(); terms = build_terms(static, trending)
    seen = jload(SEEN, {}); trc = jload(TRCACHE, {}); devc = jload(DEVCACHE, {})
    feed = fetch_feed(errs); new = update_seen(seen, feed)
    groups = ticker_groups(seen); t = time.time()
    cands, nscored, near = [], 0, []
    window = [e for e in seen.values() if PREFETCH_AGE_MIN <= (t - e["created"] / 1000) / 60 <= AGE_MAX]
    in_age = 0
    for e in window:
        age = (t - e["created"] / 1000) / 60
        if (e.get("quote_mint") or NATIVE) != NATIVE or e.get("complete") or e.get("banned"): continue
        if age >= AGE_MIN: in_age += 1
        sc, mt, rs = narrative(e, terms, static, groups); nscored += 1
        rec = {"mint": e["mint"], "name": e["name"][:40], "symbol": e["symbol"][:16], "age_min": round(age, 1), "score": sc, "matched": [x["term"] + "/" + x["cat"] for x in mt], "why": rs}
        if e.get("last_score") != sc and not dry:
            e["last_score"] = sc; dec_log({"type": "narrative", "decision": "PASS" if sc >= THRESHOLD else "REJECT", **rec})
        if sc >= THRESHOLD: cands.append((sc, age, e, rec))
        elif sc >= 45: near.append(rec)
    cands.sort(key=lambda x: (-x[0], x[1]))
    # deep checks (pump.fun coin + trades + dev history + RugCheck) for narrative passers; prefetch trades for 0.5-2 min coins
    p = meme.load_pos(); held = {o.get("token") for o in p["open"]}; cool = scan.cooldown_active()
    results, passers = [], []; sh_single, rc_new = [], [0]
    curves = chain_curves([e.get("bonding_curve") for sc, age, e, rec in cands[:DEEP_MAX] if age >= AGE_MIN], errs)
    for sc, age, e, rec in cands[:DEEP_MAX]:
        if time.time() - T0 > RUN_BUDGET_S: rec.update(decision="SKIP", reason="run time budget"); results.append(rec); continue
        if e["mint"] in held: rec.update(decision="HELD", reason="already held"); results.append(rec); continue
        if e["mint"] in cool or e.get("bonding_curve") in cool: rec.update(decision="REJECT", reason="cooldown: " + ((cool.get(e["mint"]) or cool.get(e.get("bonding_curve")) or {}).get("reason") or "24h")[:90]); results.append(rec); continue
        tr = update_trades(e["mint"], trc, TRADE_PAGES, errs); ts = trade_stats(tr, e["creator"])
        if age < AGE_MIN:
            rec.update(decision="WAIT", reason=f"too young ({age:.1f} < {AGE_MIN:.0f} min), trades prefetched", traction=ts); results.append(rec); continue
        try: fresh = get(f"{PF}/coins-v2/{e['mint']}")
        except Exception as ex: rec.update(decision="REJECT", reason=f"coin data unavailable ({type(ex).__name__})"); results.append(rec); continue
        dev = dev_history(e["creator"], devc, errs)
        fails, info = safety(e, fresh, curves.get(e.get("bonding_curve")), dev, ts, meme.rugcheck_report, meme.rugcheck_gates)
        meme.chase_cooldown(fails, [e["mint"], e.get("bonding_curve")], e.get("name") or e["mint"][:8])
        rec["traction"] = info; rec["tier"] = "strong" if sc >= STRONG else "normal"
        if len(fails) == 1 and not fails[0].startswith(DATA_FAILS) and not fails[0].startswith("rugcheck") and rc_new[0] < SHADOW_RC_NEW:
            try:   # one cheap gate failed -> confirm RugCheck would pass before calling it a single-gate miss
                hit = meme._rc_cache().get(e["mint"])
                if not (hit and time.time() - hit["ts"] < meme.RC_TTL): rc_new[0] += 1
                rep_, _ = meme.rugcheck_report(e["mint"]); g = meme.rugcheck_gates({"venue": "bonding_curve", "pool": e["bonding_curve"]}, rep_)
                if not g: sh_single.append((sc, e, fresh, rec, fails[0]))
            except Exception: pass
        elif len(fails) == 1 and fails[0].startswith("rugcheck: "): sh_single.append((sc, e, fresh, rec, fails[0]))
        if fails: rec.update(decision="REJECT", reason="; ".join(fails)[:300])
        else: rec.update(decision="PASS", reason="narrative + all safety gates"); passers.append((sc, e, fresh, curves.get(e.get("bonding_curve")), rec))
        results.append(rec)
        if not dry: dec_log({"type": "safety", **rec})
    # trim caches
    live = {e["mint"] for e in window}
    trc = {m: v for m, v in trc.items() if m in live or m in held}
    devc = {k: v for k, v in devc.items() if time.time() - v["ts"] < DEV_TTL}
    jsave(SEEN, seen); jsave(TRCACHE, trc); jsave(DEVCACHE, devc)
    # buy
    buy = None; reason = None
    if passers: buy, reason = enter(passers[0], dry, meme)
    try: n_sh = shadow_entries(passers, buy, reason, sh_single, dry, meme)
    except Exception as ex: n_sh = 0; errs.append(f"shadow: {type(ex).__name__} {str(ex)[:60]}")
    n_in_age = in_age
    stats = {"run_at": now().astimezone(BER).isoformat(timespec="seconds"), "feed": len(feed), "new_launches": new,
             "per_min_est": new, "in_window_2_15m": n_in_age, "scored": nscored, "narrative_pass": len(cands),
             "deep_checked": sum(1 for r in results if r.get("decision") in ("PASS", "REJECT") and "traction" in r),
             "safety_pass": len(passers), "trending": tstat, "errors": errs[-6:], "threshold": THRESHOLD, "strong": STRONG,
             "duration_s": round(time.time() - T0, 1), "bought": buy, "buy_note": reason, "shadow_opened": n_sh}
    out = {**stats, "candidates": results[:15], "near_misses": sorted(near, key=lambda r: -r["score"])[:10]}
    if not dry: jsave(LATEST, out)
    _out = log if (passers or buy) else (lambda l, d=False: print(f"{now().astimezone(BER):%Y-%m-%d %H:%M:%S %Z} " + ("[DRY] " if d else "") + l))
    _out(f"[NEWPAIRS] {new} new launches, {n_in_age} aged 2-15m, {len(cands)} narrative>={THRESHOLD}, {len(passers)} passed safety"
        + (f" | top: " + ", ".join(f"{r['symbol']} {r['score']} {r.get('decision','')}" for r in results[:3]) if results else "")
        + (f" | BUY {buy}" if buy else (f" | {reason}" if reason else "")) + f" | {tstat}" + (f" | errors {len(errs)}" if errs else ""), dry)
    return out

def dec_log(rec):
    path = DEC_LOG.format(now().astimezone(BER).date().isoformat())
    with open(path, "a") as f: f.write(json.dumps({"t": now().astimezone(BER).isoformat(timespec="seconds"), **({"lead": lead_id(rec.get("mint"))} if rec.get("mint") else {}), **rec}, default=str) + "\n")

def gate_key(text):
    import meme; return meme.gate_key(text.replace("rugcheck: ", "")) if not text.startswith("rugcheck: ") else "rugcheck: " + meme.gate_key(text[10:])

def shadow_entries(passers, buy, reason, singles, dry, meme):
    """virtual trades (shadow book) for: passers[0] blocked by max open, passers[1:] (one buy per run), single-gate misses."""
    cap = bool(reason) and ("max" in reason and "open" in reason)
    picks = []
    if passers and cap: picks.append(("np:blocked:max_open", passers[0][0], passers[0][1], passers[0][2], "passed narrative + all safety gates; " + reason))
    if passers and (buy or cap):
        picks += [("np:blocked:one_per_run", sc, e, fr, "passed narrative + all safety gates; another new pair taken this run") for sc, e, fr, cs, rec in passers[1:]]
    picks += [("np:gate:" + gate_key(f), sc, e, fr, f) for sc, e, fr, rec, f in singles]
    if not picks: return 0
    if dry: print("[DRY] new-pairs shadow: " + "; ".join(f"{k} {e['symbol']} ({n[:40]})" for k, sc, e, fr, n in picks)); return 0
    import shadow
    dial, _ = meme.latest_dial(); dm = (dial or {}).get("dial", {}).get("meme") or 1.0; eq = meme.meme_state()["equity"]
    cs = chain_curves([e["bonding_curve"] for _, _, e, _, _ in picks], [])
    ents = []
    for k, sc, e, fr, note in picks:
        c = cs.get(e["bonding_curve"]); sol = sol_usd_of(fr)
        if not c or not c.get("price_sol") or not sol or c.get("complete"): continue
        price = c["price_sol"] * sol; liq = c["real_sol"] * sol; tier = meme.regime_plan(EXIT_TIERS["strong" if sc >= STRONG else "normal"])
        ents.append({"cat": k, "note": note, "pool": e["bonding_curve"], "token": e["mint"], "name": f"{e['symbol'][:16]} / SOL", "venue": "bonding_curve",
                     "price": price, "sol": sol, "liq": liq, "mcap": price * TOTAL_SUPPLY_UI, "ticket": round(min(meme.FIXED_TICKET_USD, meme.LIQ_CAP * liq), 2),
                     "exit": tier, "tier": tier["tier"], "sleeve": "newpairs", "creator": e["creator"], "narrative_score": sc, "url": f"https://pump.fun/coin/{e['mint']}"})
    return shadow.open_entries(ents)

def enter(pick, dry, meme):
    sc, e, fresh, cs, rec = pick
    dial, age = meme.latest_dial()
    if meme.daily_halt_active(): return None, "daily drawdown halt active"
    if not dial: return None, "no dial"
    if age > meme.DIAL_MAX_AGE_H: return None, f"dial {age:.1f}h old"
    if dial["dial"]["meme"] < 0.50: return None, f"meme dial {dial['dial']['meme']} < 0.50"
    cs = (chain_curves([e["bonding_curve"]], []) or {}).get(e["bonding_curve"]) or cs   # fresh fill price from chain
    sol = sol_usd_of(fresh)
    if not cs or not cs.get("price_sol") or not sol: return None, "no price"
    if cs.get("complete"): return None, "graduated just now"
    price = cs["price_sol"] * sol; liq = cs["real_sol"] * sol; mc = price * TOTAL_SUPPLY_UI
    tier = meme.regime_plan(EXIT_TIERS["strong" if sc >= STRONG else "normal"])
    if dry: return None, f"DRY: would buy {e['symbol']} score {sc} tier {tier['tier']}"
    try:
        if True:   # sizing reads the book; the locked add + all cap re-checks happen in meme.book_add (2026-10-20 risk audit)
            p = meme.load_pos(); ms = meme.meme_state(p)
            npo = [o for o in p["open"] if o.get("sleeve") == "newpairs"]
            if len(p["open"]) >= TOTAL_MAX_OPEN: return None, f"overall max {TOTAL_MAX_OPEN} open"
            if len(npo) >= NP_MAX_OPEN: return None, f"max {NP_MAX_OPEN} new-pair positions open"
            if any(o.get("token") == e["mint"] for o in p["open"]): return None, "already held"
            t1, t2 = meme.FIXED_TICKET_USD, meme.LIQ_CAP * liq   # fixed 10 EUR (user order 2026-10-21)
            ticket = round(min(t1, t2, ms["cash"]), 2)
            fee, fr = meme.total_fee(ticket, "bonding_curve", mc, sol)
            if ticket < meme.MIN_TICKET or fee >= 0.10 * ticket:
                log(f"[SIZE] NEW PAIR skip {e['symbol']}: ticket ${ticket:.2f} (fixed 10 EUR = ${t1:.2f}, 2% liq ${t2:.2f}) < min ${meme.MIN_TICKET:.2f} or fee ${fee:.3f}")
                return None, f"ticket ${ticket:.2f} too small"
            b = meme.sim_buy(ticket, "bonding_curve", price, sol, liq, mc)
            o = {"lead": lead_id(e["mint"]), "pool": e["bonding_curve"], "token": e["mint"], "name": f"{e['symbol'][:16]} / SOL", "venue": "bonding_curve",
                 "url": f"https://pump.fun/coin/{e['mint']}", "entry_time": meme.now().isoformat(), **b, "tp_done": False, "tp_hits": [], "stop_loss": 0.30,
                 "sleeve": "newpairs", "tier": tier["tier"], "exit": tier, "creator": e["creator"], "narrative_score": sc,
                 "narrative": rec.get("matched"), "narrative_why": rec.get("why"), "traction": rec.get("traction"),
                 "src": ["pump.fun new"], "last_check": meme.now().isoformat(), "simulated": True}
            blk = meme.book_add(o, NP_MAX_OPEN, TICKET_PCT, TOTAL_MAX_OPEN)
            if blk: return None, blk
    except TimeoutError: return None, "positions lock busy -> retry next minute"
    log(f"[SIZE] NEW PAIR ticket ${ticket:.2f} = min(1.5% x meme bank ${ms['equity']:.2f} x dial {dial['dial']['meme']} = ${t1:.2f}, 2% curve liq ${t2:.2f}); fee {fr:.2%} + ${meme.NETWORK_FEE_USD + meme.PRIORITY_FEE_USD:.3f} network/priority")
    log(f"[FILLS] BUY [NEW PAIR · {tier['tier'].upper()}] {ltag(o['token'])}{o['name']} (SIMULATED pump.fun bonding_curve) ${ticket:.2f} @ {b['entry_price']:.10g} (slip {b['entry_slippage']:.2%}; rent deposit ${b['rent_usd']:.3f} refundable) | narrative {sc}: {', '.join(rec.get('matched') or [])} | buyers {rec['traction'].get('buyers')} curve {rec['traction'].get('progress')}%")
    dec_log({"type": "buy", "mint": e["mint"], "symbol": e["symbol"], "score": sc, "tier": tier["tier"], "ticket": ticket, "fill": b["entry_price"]})
    return o["name"], None

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dry"
    if cmd == "run": run()
    elif cmd == "dry":
        r = run(dry=True)
        if r: print(json.dumps({k: v for k, v in r.items() if k not in ("near_misses",)}, indent=1, default=str)[:12000]); print("NEAR", json.dumps(r["near_misses"][:6], indent=0)[:3000])
