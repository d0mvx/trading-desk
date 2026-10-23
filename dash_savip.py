"""SAVIP redesign (2026-10-21): black 'desk floor' dashboard layout modelled on the x-savip reference video.
DISPLAY ONLY. Assembles real desk data (positions, equity, scan/judge records, trades) into
  - data["savip"]   (desks / floor scenes / analysis meta, re-rendered client side from data.json every 15 s)
  - fragments       hold rows (tap-to-expand .tc cards), analysis panel, activity panel
and provides CSS + JS (canvas pixel-art floor, neon balance chart). No external images; read-only APIs only
(DexScreener pairs -> mint, pump.fun candles for the analysed candidate; <= 1 DS + 2 pump.fun calls per build, cached)."""
import os, re, json, time, math, html, datetime as dt
from zoneinfo import ZoneInfo
DESK = os.path.expanduser("~/.desk"); BER = ZoneInfo("Europe/Berlin"); UTC = dt.timezone.utc
esc = html.escape

THEME = {"meme": "#22e33a", "newpairs": "#a3f75a", "trend": "#f5c518", "stocks": "#3b82f6", "crypto": "#f7931a"}
DESKS = [  # id, label, floor title, logo kind, venue text, bots on the floor (real desk bots)
    ("meme", "MEME", "THE PUMPSWAP FLOOR", "pill", "PumpSwap", ["SCAN", "JUDGE", "SIZE", "FILLS", "RISK", "QUANT"]),
    ("newpairs", "NEW PAIRS", "THE PUMP.FUN FLOOR", "pill2", "pump.fun", ["SCAN", "JUDGE", "SIZE", "FILLS", "RISK"]),
    ("trend", "TREND", "THE TQQQ FLOOR", "alpaca", "Alpaca", ["TREND", "QUANT", "RISK", "FILLS"]),
    ("stocks", "STOCKS", "THE STOCKS FLOOR", "stocks", "Alpaca", ["STOCKS", "QUANT", "SIZE", "RISK", "FILLS"]),
    ("crypto", "CRYPTO", "THE CRYPTO FLOOR", "btc", "Alpaca", ["CRYPTO", "QUANT", "RISK", "FILLS"]),
]
BY = {"meme": "JUDGE", "newpairs": "SCAN", "trend": "TREND", "stocks": "STOCKS", "crypto": "CRYPTO"}
RULES = {
    "meme": ["SL -20% swap / -30% curve", "TP 1/2 @+50% 1/4 @+100%", "trail -25% after +15%", "time stop 60 min", "max 6 open (8 total)", "4% day DD -> halt"],
    "newpairs": ["narrative score >= 70", "RugCheck + dev not sold", "curve 5-60% / 25 buyers", "ticket 1.5% x bank", "max 2 new pairs", "-30% hard stop"],
    "trend": ["QQQ > 200d -> TQQQ", "else -> SHY", "35% of paper acct", "check 15:45 NY", "no price stop", "acct kill -4%/day"],
    "stocks": ["DRIFT + INSIDERS lists", "50% x dial", "rebalance 15:45 NY", "sell if off both lists", "dial < 0.50 -> sell", "acct kill -4%/day"],
    "crypto": ["top-2 12m->1m momentum", "15% x dial", "rebalance 20:05 NY", "BTC / ETH / SOL", "dial < 0.50 -> cash", "acct kill -4%/day"],
}
SCAN_RULES = [  # (label, fail prefixes) -> 6 SCAN rules as stored in scan/rejects-*.jsonl "fails"
    ("age 15m-72h", ("age",)), ("mcap 15K-8M", ("mcap",)), ("liq ≥ $5K/12K", ("liquidity",)),
    ("vol, no wash", ("24h vol", "vol/liq")), ("buys > sells", ("buys", "sells")), ("SOL pair, fresh", ("quote", "stale", "curve", "cooldown")),
]

def hue(s):
    h = 0
    for ch in str(s): h = (h * 31 + ord(ch)) % 360
    return h
def tick(name): return (name or "?").split(" / ")[0].strip()[:12]
LOGO = {}   # tkey -> 'logos/<id>.webp?v=..' (filled by assemble via dash_logos; empty -> initials circle)
def _lk(t): return re.sub(r"\s+", " ", (t or "?").strip()).upper()
def logo_url(name): return LOGO.get(_lk(tick(name)))
def logo(name, cls="lg"):
    t = tick(name); ini = re.sub(r"[^A-Za-z0-9$]", "", t)[:2].upper() or "?"; u = LOGO.get(_lk(t))
    im = f'<img class="lgi" src="{esc(u)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">' if u else ""
    return f'<span class="{cls}" style="--h:{hue(t)}">{esc(ini)}{im}</span>'
def usd(x, dec=2): return ("-" if x < 0 else "") + f"${abs(x):,.{dec}f}"
def susd(x, dec=2): return ("+" if x >= 0 else "-") + f"${abs(x):,.{dec}f}"
def spct(x, dec=2): return ("+" if x >= 0 else "") + f"{x:.{dec}f}%"
def kusd(x):
    if x is None: return "n/a"
    return f"${x/1e6:.2f}M" if x >= 1e6 else f"${x/1e3:.1f}K" if x >= 1e3 else f"${x:.0f}"
def tlabel(t, today):
    try:
        t = t if isinstance(t, dt.datetime) else dt.datetime.fromisoformat(str(t))
        t = t if t.tzinfo else t.replace(tzinfo=UTC); b = t.astimezone(BER)
        return b.strftime("%H:%M") if b.date() == today else b.strftime("%d.%m. %H:%M")
    except Exception: return ""
def _ts(t):
    try:
        t = t if isinstance(t, dt.datetime) else dt.datetime.fromisoformat(str(t))
        return (t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp()
    except Exception: return 0.0

def _bars(ch, prefer=("5m", "1m", "1h")):
    tf = (ch or {}).get("tf") or {}
    for k in prefer:
        if len(tf.get(k) or []) >= 12: return tf[k]
    for k in prefer:
        if tf.get(k): return tf[k]
    return []
def _down(vals, n):
    if len(vals) <= n: return vals
    step = len(vals) / n
    return [vals[min(len(vals) - 1, int(i * step))] for i in range(n - 1)] + [vals[-1]]
def _sig(x): return float(f"{x:.5g}") if x else 0.0
def spark_pts(ch, entry_loc=None, n=44):
    b = _bars(ch, ("1m", "5m", "1h"))
    if entry_loc: b2 = [x for x in b if x[0] >= entry_loc - 600]; b = b2 if len(b2) >= 8 else b[-48:]
    else: b = b[-48:]
    return _down([x[4] for x in b], n)
def spark_svg(vals, w=84, h=30):
    if len(vals) < 2: return f'<svg class="spk" viewBox="0 0 {w} {h}"></svg>'
    lo, hi = min(vals), max(vals); r = (hi - lo) or (abs(hi) * 0.01 or 1)
    pts = " ".join(f"{i*(w-2)/(len(vals)-1)+1:.1f},{h-2-(v-lo)/r*(h-4):.1f}" for i, v in enumerate(vals))
    col = "#22e33a" if vals[-1] >= vals[0] else "#ff4d2e"
    return f'<svg class="spk" viewBox="0 0 {w} {h}" preserveAspectRatio="none"><polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>'
def candles_compact(bars, n=48):
    b = bars[-n:]
    return [[_sig(x[1]), _sig(x[2]), _sig(x[3]), _sig(x[4])] + ([round(float(x[5] or 0), 1)] if len(x) > 5 else []) for x in b]
def svg_candles(bars, w=320, h=190):
    b = bars[-60:]
    grid = "".join(f'<line x1="0" x2="{w}" y1="{h*i/5:.0f}" y2="{h*i/5:.0f}" stroke="#151515"/>' for i in range(1, 5))
    grid += "".join(f'<line y1="0" y2="{h}" x1="{w*i/6:.0f}" x2="{w*i/6:.0f}" stroke="#121212"/>' for i in range(1, 6))
    if len(b) < 2:
        return f'<svg class="anch" viewBox="0 0 {w} {h}" preserveAspectRatio="none">{grid}<text x="{w/2}" y="{h/2}" text-anchor="middle" fill="#555" font-size="11">no candles yet</text></svg>'
    ls = sorted(x[3] for x in b); hs_ = sorted(x[2] for x in b); q = max(0, int(len(b) * 0.04))
    lo = min(ls[q], min(x[4] for x in b[-10:])); hi = max(hs_[-1 - q], max(x[4] for x in b[-10:])); r = (hi - lo) or (hi * 0.01 or 1)
    Y = lambda v: min(h - 4, max(4, 8 + (h - 22) * (1 - (v - lo) / r)))
    cw = w / len(b); out = []
    for i, x in enumerate(b):
        o, hh, l, c = x[1], x[2], x[3], x[4]; col = "#22e33a" if c >= o else "#ff4d2e"; cx = i * cw + cw / 2
        y1, y2 = sorted((Y(o), Y(c)))
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{Y(hh):.1f}" y2="{Y(l):.1f}" stroke="{col}" stroke-width="1"/>'
                   f'<rect x="{cx-cw*0.34:.1f}" y="{y1:.1f}" width="{max(1, cw*0.68):.1f}" height="{max(1, y2-y1):.1f}" fill="{col}"/>')
    vmax = max((x[5] if len(x) > 5 else 0) for x in b) or 0
    if vmax:
        for i, x in enumerate(b):
            vh = (x[5] / vmax) * 26; col = "#1d7a2c" if x[4] >= x[1] else "#8a2d1e"
            out.append(f'<rect x="{i*cw+cw*0.16:.1f}" y="{h-vh:.1f}" width="{max(1, cw*0.68):.1f}" height="{vh:.1f}" fill="{col}" opacity=".55"/>')
    return f'<svg class="anch" viewBox="0 0 {w} {h}" preserveAspectRatio="none">{grid}{"".join(out)}</svg>'

def svg_mini(bars, w=90, h=56):
    # compact side-column candles (SAVIP v2 size fix): last 24 bars, one path per colour, no grid/volume
    b = bars[-24:]
    if len(b) < 2:
        return f'<svg class="ansv" viewBox="0 0 {w} {h}" preserveAspectRatio="none"></svg>'
    lo = min(x[3] for x in b); hi = max(x[2] for x in b); r = (hi - lo) or (hi * 0.01 or 1)
    Y = lambda v: round(4 + (h - 8) * (1 - (v - lo) / r), 1)
    cw = w / len(b); P = {"g": [], "r": []}
    for i, x in enumerate(b):
        o, hh, l, c = x[1], x[2], x[3], x[4]; k = "g" if c >= o else "r"; cx = round(i * cw + cw / 2, 1)
        y1, y2 = sorted((Y(o), Y(c))); bw = round(max(1, cw * .6), 1)
        P[k].append(f"M{cx} {Y(hh)}V{Y(l)}M{round(cx-bw/2,1)} {y1}h{bw}v{round(max(1,y2-y1),1)}h-{bw}z")
    return (f'<svg class="ansv" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<path d="{"".join(P["g"])}" stroke="#22e33a" fill="#22e33a" stroke-width=".8"/><path d="{"".join(P["r"])}" stroke="#ff4d2e" fill="#ff4d2e" stroke-width=".8"/></svg>')

# ---------- analysed candidates: real candles (DexScreener pool -> mint, pump.fun 1m candles) ----------
def cand_candles(pools, dc):
    c = dc._load("_sv_cands"); now = time.time(); mints = c.setdefault("mint", {}); bars = c.setdefault("bars", {}); changed = False
    need = [p for p in pools if p and p not in mints]
    if need and now - c.get("ds_ts", 0) >= 45:
        try:
            import requests
            r = requests.get("https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(need[:20]), timeout=6)
            for p in (r.json().get("pairs") or []):
                mints[p["pairAddress"]] = (p.get("baseToken") or {}).get("address")
            for p in need[:20]: mints.setdefault(p, None)
        except Exception: pass
        c["ds_ts"] = now; changed = True
    calls = 0
    for p in pools:
        m = mints.get(p); e = bars.get(p) or {}
        if not m or now - e.get("ts", 0) < 180 or calls >= 2: continue
        calls += 1
        try:
            b = dc._pf_candles(m, "1m", now - 2 * 3600, 120)
            bars[p] = {"ts": now, "b": [[t, _sig(o), _sig(h), _sig(l), _sig(cl), round(v, 1)] for t, o, h, l, cl, v in b][-90:]}
        except Exception as ex:
            bars[p] = {"ts": now, "b": e.get("b") or [], "err": type(ex).__name__}
        changed = True
    for p in list(bars):
        if now - bars[p].get("ts", 0) > 3 * 3600: bars.pop(p, None); changed = True
    if len(mints) > 400:
        for p in list(mints)[:-300]: mints.pop(p, None)
    if changed: dc._save("_sv_cands", c)
    return {p: (bars.get(p) or {}).get("b") or [] for p in pools}

def rule_results(cand, judge=None):
    fails = cand.get("fails") or []; out = []
    tx15 = cand.get("tx_m15") or {}; vol, liq = cand.get("vol_h24"), cand.get("liquidity_usd")
    vals = [f'{cand["age_h"]:.1f}h' if cand.get("age_h") is not None else "n/a", kusd(cand.get("mcap_usd")),
            ("~" if cand.get("venue") == "bonding_curve" else "") + kusd(liq), (f"{vol/liq:.0f}x" if vol and liq else kusd(vol)),
            f'{tx15.get("buys", "?")}/{tx15.get("sells", "?")}', "curve" if cand.get("venue") == "bonding_curve" else "PumpSwap"]
    for i, (lab, pre) in enumerate(SCAN_RULES):
        f = [x for x in fails if any(str(x).lower().startswith(p) for p in pre)]
        out.append({"n": i + 1, "label": lab, "val": vals[i], "ok": not f, "why": f[0] if f else ""})
    return out

def _logos(G, hold_items, meme, rej_rec, orders):
    """Register every coin/stock name the page shows, resolve real logos (cached), fill LOGO. Never raises."""
    LOGO.clear()
    if os.environ.get("DESK_NO_LOGOS"): return
    try:
        import dash_logos
        L = dash_logos.Logos()
        tok = {}
        for o in (meme.get("open") or []) + list(reversed(meme.get("closed") or []))[:30]:
            if o.get("pool") and o.get("token"): tok[o["pool"]] = o["token"]
        for h in hold_items:
            if h["ck"].startswith("m_"): pl = h["ck"][2:]; L.add_sol(h["name"], tok.get(pl), pl)
            else: L.add_alp(h["name"])
        for o in (meme.get("open") or []) + list(reversed(meme.get("closed") or []))[:30]: L.add_sol(o.get("name"), o.get("token"), o.get("pool"))
        for l in G["tail"](f"{DESK}/logs/meme_trades.jsonl", 80):
            try: r = json.loads(l); L.add_sol(r.get("name"), r.get("token"), r.get("pool"))
            except Exception: pass
        for c in ((rej_rec or {}).get("passed_candidates") or [])[:5] + ((rej_rec or {}).get("rejects") or [])[:4]: L.add_sol(c.get("name"), c.get("token") or c.get("mint"), c.get("pool"))
        try:
            for k, v in json.load(open(f"{DESK}/meme_watchlist.json")).items(): L.add_sol(v.get("name"), v.get("token") or v.get("mint"), v.get("pool") or k)
        except Exception: pass
        for o in orders[:40]:
            try: L.add_alp(o.symbol)
            except Exception: pass
        LOGO.update(L.resolve(os.environ.get("DESK_DASH_OUT") or f"{DESK}/dashboard"))
    except Exception as e:
        print(f"WARNING: logos skipped: {type(e).__name__}: {str(e)[:120]}")

def assemble(G):
    """G = globals() of build_dashboard.py after the data gathering. Returns {"data", "frag"}."""
    NOW = G["NOW"]; today = NOW.astimezone(BER).date(); meme = G.get("meme") or {}; charts = G.get("charts") or {}
    dc = G["_dc"]; hold_items = G.get("hold_items") or []; rej_rec = G.get("rej_rec"); judge_rec = G.get("judge_rec")
    acct = G.get("acct"); orders = G.get("orders") or []; dial = G.get("dial"); bots = G.get("bots") or []
    alp = G.get("alp") or {}; np_ = G.get("_np") or {}
    _logos(G, hold_items, meme, rej_rec, orders)
    # ---- main screen: open position with the biggest |PnL %|, else the latest buy ----
    main_ck = None
    if hold_items: main_ck = max(hold_items, key=lambda h: abs(h["upl_pct"]))["ck"]
    # ---- holdings rows (keep .tc[data-ck] tap-to-expand: DexScreener / TradingView live chart + 'Mein Einstieg' + facts) ----
    order = {"meme": 0, "newpairs": 1, "trend": 2, "stocks": 3, "crypto": 4}
    items = sorted(hold_items, key=lambda h: (h["ck"] != main_ck, order.get(h["sleeve"], 9), -abs(h["upl_pct"])))
    rows = []
    for i, h in enumerate(items):
        ch = charts.get(h["ck"]); sp = spark_pts(ch, (ch or {}).get("entry", {}).get("t") if ch else None)
        h["spark"] = sp
        st = h.get("status") or "in a trade"
        rows.append(
            f'<div class="tc hr{" hl" if h["ck"] == main_ck else ""}{" xtra" if i >= 6 else ""}" data-ck="{esc(h["ck"])}"{(' data-sp="' + ",".join(f"{v:.6g}" for v in sp) + '"') if h["ck"].startswith("m_") and sp else ""}><div class="hr-r">{logo(h["name"])}'
            f'<div class="hr-n"><b>{esc(tick(h["name"]))}</b>{"<span class=msb>MAIN SCREEN</span>" if h["ck"] == main_ck else ""}'
            f'<div class="hr-by">by {BY.get(h["sleeve"], "SCAN")} · <em class="{"it" if st == "in a trade" else ""}">{esc(st)}</em></div></div>'
            f'{spark_svg(sp)}<div class="hr-v"><b>{usd(h["value"])}</b><span class="pl {"pos" if h["upl"] >= 0 else "neg"}">{spct(h["upl_pct"])}</span></div></div>'
            f'<div class="hr-d"><div class="hr-pl">P&amp;L <b class="{"pos" if h["upl"] >= 0 else "neg"}">{susd(h["upl"])}</b> · Einsatz {usd(h["cost"])}</div>{h["det"]}</div>'
            '<div class="chint"><span class="a"></span><span class="b">▾ schließen</span></div><div class="tc-chart"></div></div>')
    n_desks_hold = len({h["sleeve"] for h in hold_items})
    hold_html = ("".join(rows) if rows else '<div class="none">Bots are flat · no open positions right now.</div>')
    if len(rows) > 6: hold_html += f'<button type="button" class="hmore" data-n="{len(rows) - 6}">+ {len(rows) - 6} more positions</button>'
    hold_head = f'Bots are holding · {n_desks_hold} desk{"s" if n_desks_hold != 1 else ""}'
    # ---- desks ----
    by_sleeve = {}
    for h in items: by_sleeve.setdefault(h["sleeve"], []).append(h)
    closed = meme.get("closed") or []
    bot_st = {n: (st, note) for n, st, note in [(b[0], b[2], b[3]) for b in bots]}
    src = (rej_rec or {}).get("sources") or {}
    jd = ((judge_rec or {}).get("decisions") or [{}])[0] if judge_rec else {}
    kill = alp.get("kill") or {}
    try: day_n = (today - dt.date.fromisoformat(G["bank"]["started"])).days + 1
    except Exception: day_n = 1
    # recent trade events (real) for bubbles / activity
    trades = []
    for l in G["tail"](f"{DESK}/logs/meme_trades.jsonl", 80):
        try: r = json.loads(l)
        except Exception: continue
        if r.get("type") == "BUY": trades.append({"t": _ts(r.get("entry_time")), "side": "buy", "name": tick(r.get("name")), "usd": r.get("cost_usd") or 0, "sleeve": r.get("sleeve") or "meme", "venue": r.get("venue")})
        elif r.get("type") == "SELL":
            cost = r.get("cost_usd") or 0
            trades.append({"t": _ts(r.get("exit_time")), "side": "sell", "name": tick(r.get("name")), "usd": r.get("pnl") or 0, "pct": ((r.get("pnl") or 0) / cost * 100) if cost else 0,
                           "sleeve": r.get("sleeve") or "meme", "reason": (r.get("exit_reason") or "").split(":")[0], "partial": r.get("partial")})
    for o in orders:
        try:
            if not o.filled_at or float(o.filled_qty or 0) <= 0: continue
            sym = o.symbol.replace("/", ""); px = float(o.filled_avg_price or 0) * float(o.filled_qty or 0)
            trades.append({"t": o.filled_at.timestamp(), "side": str(o.side.value), "name": o.symbol, "usd": px, "sleeve": G["_sleeve"](sym), "alpaca": True})
        except Exception: pass
    trades.sort(key=lambda x: -x["t"])
    desks = []
    for did, lab, title, lg, venue, dbots in DESKS:
        hs = by_sleeve.get(did, []); th = THEME[did]
        main = hs[0] if hs else None; note = "open"
        if main: ticker, pct, pnl_usd = tick(main["name"]), main["upl_pct"], sum(x["upl"] for x in hs); ck = main["ck"]
        else:
            ck = None; last = next((c for c in reversed(closed) if (c.get("sleeve") or "meme") == did), None) if did in ("meme", "newpairs") else None
            if last:
                cost = last.get("cost_usd") or 0; ticker, pct, pnl_usd, note = tick(last.get("name")), (last["pnl"] / cost * 100 if cost else 0), last["pnl"], "last trade"
                ch = dc._load("m_" + str(last.get("pool"))); mb = ((ch.get("m1") or {}).get("bars")) or []
                cand = candles_compact(dc.resample(mb, 120) if len(mb) > 96 else mb, 72)
            else: ticker, pct, pnl_usd, note, cand = "CASH", 0.0, 0.0, "flat", []
        ctf = ct = None
        if main:
            _bb = _bars(charts.get(ck), ("5m", "1m", "1h")); cand = candles_compact(_bb, 72)
            _tfm = {k: v for k, v in ((charts.get(ck) or {}).get("tf") or {}).items() if v is _bb}
            ctf = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400, "1D": 86400}.get(next(iter(_tfm), ""), None)
            ct = (_bb[-1][0] if _bb else None)
        mon = [_down(h.get("spark") or [], 24) for h in hs[1:7]] or ([_down(hs[0].get("spark") or [], 24)] if hs else [])
        coins = [tick(h["name"]) for h in hs[:6]] or [tick(c.get("name")) for c in list(reversed(closed))[:6] if (c.get("sleeve") or "meme") == did][:6]
        coins = list(dict.fromkeys(coins))[:6]
        best = max(hs, key=lambda h: h["upl_pct"]) if hs else None
        # speech bubbles = real recent events / states
        say = {}
        if did in ("meme", "newpairs"):
            if did == "meme" and rej_rec: say["SCAN"] = f'{rej_rec.get("pools_seen", "?")} seen · {rej_rec.get("passed", "?")} passed'
            if did == "newpairs" and np_: say["SCAN"] = f'{np_.get("new_launches", 0)} launches · {np_.get("narrative_pass", 0)} narrative'
            if did == "meme" and jd.get("decision"): say["JUDGE"] = (f'{jd["decision"].lower()}: ' + (jd.get("reason") or "")[:34])
            elif did == "newpairs": say["JUDGE"] = (np_.get("bought") and f'bought {np_["bought"]}') or f'{np_.get("safety_pass", 0)} passed safety'
            say["SIZE"] = f'ticket {"3%" if did == "meme" else "1.5%"} x ${meme.get("equity", 0):.0f} bank'
            tr = next((t for t in trades if not t.get("alpaca") and (t["sleeve"] or "meme") == did), None)
            if tr: say["FILLS"] = (f'bought {tr["name"]} ${tr["usd"]:.2f}' if tr["side"] == "buy" else
                                   (f'stop hit · {tr["name"]} {susd(tr["usd"])}' if "stop" in (tr.get("reason") or "").lower() else
                                    f'take profit · {tr["name"]} {susd(tr["usd"])}' if "take-profit" in (tr.get("reason") or "").lower() else f'sold {tr["name"]} {susd(tr["usd"])}'))
            say["RISK"] = ("HALT: 4% day DD" if G.get("meme_halt") else "DD guard ok · stops 5x/min")
        else:
            tr = next((t for t in trades if t.get("alpaca") and t["sleeve"] == did), None)
            if tr: say["FILLS"] = f'{tr["side"]} {tr["name"]} {usd(tr["usd"], 0)}'
            say["RISK"] = f'kill switch {kill.get("result", "ready")[:26]}'
            if did == "trend": say["TREND"] = (f'{ticker} {spct(pct)} · 200d rule' if main else "flat · waiting 15:45 NY")
            if did == "stocks": say["STOCKS"] = f'{len(hs)} names · {susd(pnl_usd, 0)} open'
            if did == "crypto":
                sc = (alp.get("crypto") or {}).get("scores") or {}
                say["CRYPTO"] = ("momentum " + " ".join(f"{k} {v:+.2f}" for k, v in list(sc.items())[:2])) if sc else "cash · no momentum"
        if dial:
            say["QUANT"] = (f'dial {dial.get("date", "")} · TREND fixed 35%' if did == "trend" else
                            f'dial {did if did in ("stocks", "crypto") else "meme"} {dial["dial"].get(did if did in ("stocks", "crypto") else "meme", 0):.2f} · {dial.get("date", "")}')
        if not any(t for t in trades[:1] if NOW.timestamp() - t["t"] < 3600): say.setdefault("CHIEF", "no rule, no buy")
        botl = [{"n": b, "st": (bot_st.get(b) or ("active", ""))[0], "say": say.get(b, "")} for b in dbots]
        desks.append({"id": did, "label": lab, "title": title, "logo": lg, "venue": venue, "theme": th, "ticker": ticker, "pct": round(pct, 2),
                      "pnl": round(pnl_usd, 2), "note": note, "n_open": len(hs), "ck": ck, "candles": cand, "mon": mon, "coins": coins,
                      "rules": ([r[0] for r in SCAN_RULES] if did == "meme" else RULES[did]), "exits": RULES[did], "day": day_n, "tlogo": logo_url(ticker), "clogos": [logo_url(cn) for cn in coins],
                      "value": round(sum(x["value"] for x in hs), 2), "last": (cand[-1][3] if cand else None), "bots": botl, "floats": [round(h["upl_pct"], 1) for h in hs[:8]], "mnames": [tick(h["name"]) for h in hs[1:7]] or [tick(h["name"]) for h in hs[:1]],
                      "hp": [[tick(h["name"]), round(h["upl_pct"], 2)] for h in hs[:6]], "ctf": ctf, "ct": ct,
                      "top": (f'{tick(best["name"])} {spct(best["upl_pct"], 1)}' if best else "—"),
                      "radar": (f'{src.get("wallet_signal_mints", 0)} whale mints 6h' if did in ("meme", "newpairs") else f'acct {spct((kill.get("change") or 0) * 100)} vs yday'),
                      "tape": f'{lab} DESK · DAY {day_n} · {len(hs)} OPEN · EVERY ORDER PASSES {len(RULES[did])} RULES · PAPER ONLY · {venue.upper()} · {ticker} {spct(pct, 1)}'})
    main_desk = 0
    if main_ck:
        for i, d in enumerate(desks):
            if d["ck"] == main_ck: main_desk = i
    else:
        lb = next((t for t in trades if t["side"] == "buy"), None)
        if lb:
            for i, d in enumerate(desks):
                if d["id"] == lb["sleeve"]: main_desk = i
    # ---- analysis panel: latest scan run, top passed candidates + closest rejects, real rule results ----
    cands = []
    if rej_rec:
        jmap = {d.get("pool"): d for d in ((judge_rec or {}).get("decisions") or []) if d.get("pool")}
        for c in (rej_rec.get("passed_candidates") or [])[:3]: cands.append(dict(c, _j=jmap.get(c.get("pool"))))
        for c in (rej_rec.get("rejects") or [])[:2]: cands.append(dict(c, _j=None))
    try: cb = cand_candles([c.get("pool") for c in cands], dc)
    except Exception: cb = {}
    an_blocks = []
    for i, c in enumerate(cands):
        rr = rule_results(c); j = c.get("_j") or {}
        nm = tick(c.get("name")); passed = all(r["ok"] for r in rr)
        verdict = (f'JUDGE {j.get("decision", "?")} · {j.get("reason", "")[:60]}' if j else ("SCAN PASS · waiting for JUDGE" if passed else f'DROP · rule {next(r["n"] for r in rr if not r["ok"])}'))
        rhtml = "".join(f'<div class="ru"><i>{r["n"]}</i><span>{esc(r["label"])}</span><em>{esc(r["val"])}</em><b class="{"ps" if r["ok"] else "dr"}">{"PASS" if r["ok"] else "DROP"}</b></div>' for r in rr)
        if j: rhtml += f'<div class="ru jr"><i>J</i><span>judge</span><em>{esc((j.get("reason") or "")[:22])}</em><b class="{"ps" if j.get("decision") in ("PICK", "WATCH") else "dr"}">{esc((j.get("decision") or "?")[:7])}</b></div>'
        url = f'https://dexscreener.com/solana/{c.get("pool")}'
        def _n(v, f):
            try: return f(v) if v is not None else "n/a"
            except Exception: return "n/a"
        stats = [("Market cap", _n(c.get("mcap_usd"), kusd)), ("1h change", _n(c.get("pc_h1"), lambda v: spct(float(v), 1))), ("24h vol", _n(c.get("vol_h24"), kusd)),
                 ("Liquidity", _n(c.get("liquidity_usd"), kusd)), ("Tx 1h", _n(c.get("tx_h1"), lambda v: f"{int(v):,}")), ("Age", _n(c.get("age_h"), lambda v: f"{float(v):.1f}h"))]
        anb = (f'<div class="anb"><span class="anbt">{logo(nm)}<b>{esc(nm)}</b><small>{"curve" if c.get("venue") == "bonding_curve" else "PumpSwap"}</small></span>'
               + "".join(f'<span><i>{k}</i><b class="{("pos" if str(v).startswith("+") else "neg") if k == "1h change" and v != "n/a" else ""}">{esc(v)}</b></span>' for k, v in stats) + '</div>')
        side = "".join(f'<div class="ansm">{svg_mini(cb.get(o.get("pool")) or [])}<em>{esc(tick(o.get("name")))}</em></div>'
                       for o in [x for x in cands if x is not c][:4])
        an_blocks.append(f'<div class="anc{" on" if i == 0 else ""}">{anb}<div class="anm">{svg_candles(cb.get(c.get("pool")) or [])}<div class="anx"><span>1m · {esc(nm)}/SOL</span><span>{tlabel(dt.datetime.fromtimestamp(_ts(rej_rec.get("scanned_at")) or time.time(), UTC), today)} Berlin</span></div></div><div class="ans">{side}</div><div class="anr">{rhtml}</div>'
                         f'<a class="ann" href="{esc(url)}" target="_blank" rel="noopener">{logo(nm)}<b>{esc(nm)}</b><small>{"curve" if c.get("venue") == "bonding_curve" else "PumpSwap"} · mcap {kusd(c.get("mcap_usd"))} · 1m</small></a>'
                         f'<div class="anv {"ps" if passed and (not j or j.get("decision") in ("PICK", "WATCH")) else "dr"}">{esc(verdict)}</div></div>')
    an_meta = {"scanned": (rej_rec or {}).get("pools_seen", 0), "dropped": (rej_rec or {}).get("rejected_total", 0), "at": (rej_rec or {}).get("scanned_at")}
    an_html = (("".join(an_blocks) + (f'<div class="andots">{"".join("<i></i>" for _ in an_blocks)}</div>' if len(an_blocks) > 1 else ""))
               if an_blocks else '<div class="none">No scan run recorded yet.</div>')
    an_head = f'{an_meta["scanned"]} scanned · <em>{an_meta["dropped"]} dropped</em>'
    # ---- activity: real buys / sells / drops / passes / watchlist adds ----
    acts = []
    for t in trades[:6]:
        dlab = {"meme": "MEME", "newpairs": "NEW PAIRS", "trend": "TREND", "stocks": "STOCKS", "crypto": "CRYPTO"}.get(t["sleeve"], "MEME")
        if t["side"] == "buy":
            acts.append((t["t"], t["name"], f'Bought {t["name"]}', f'{dlab} desk · via {"Alpaca paper" if t.get("alpaca") else ("pump.fun curve" if t.get("venue") == "bonding_curve" else "PumpSwap")}', usd(t["usd"]), "buy"))
        elif t.get("alpaca"): acts.append((t["t"], t["name"], f'Sold {t["name"]}', f'{dlab} desk · via Alpaca paper', usd(t["usd"]), "buy"))
        else: acts.append((t["t"], t["name"], f'Sold {t["name"]}', f'{spct(t.get("pct", 0), 1)} · {t.get("reason") or "exit"}{" · part" if t.get("partial") else ""} · {dlab}', susd(t["usd"]), "pos" if t["usd"] >= 0 else "neg"))
    if rej_rec:
        rt = _ts(rej_rec.get("scanned_at"))
        for c in (rej_rec.get("rejects") or [])[:2]:
            rr = rule_results(c); bad = next((r for r in rr if not r["ok"]), None)
            if bad: acts.append((rt, c.get("name"), f'Dropped {tick(c.get("name"))}', f'rule {bad["n"]} · {bad["why"][:34]}', "skip", "skip"))
        jmap = {d.get("pool"): d for d in ((judge_rec or {}).get("decisions") or []) if d.get("pool")}
        for c in (rej_rec.get("passed_candidates") or [])[:2]:
            j = jmap.get(c.get("pool")) or {}; dcs = j.get("decision")
            acts.append((rt + 1, c.get("name"), f'Passed {tick(c.get("name"))}', f'6/6 rules · ' + (f'judge {dcs.lower()}: {(j.get("reason") or "")[:24]}' if dcs else "to judge"),
                         "watch" if dcs in ("WATCH", None) else ("pick" if dcs == "PICK" else "skip"), "watch" if dcs in ("WATCH", "PICK", None) else "skip"))
    # USER ORDER 2026-10-21: rule 7 (first-candle launch pump) / rule 8 (bot-wash) skips from the Judge and the new-pairs sleeve
    def _rule_txt(why):
        i = (why or "").find("rule 7 ·"); j = (why or "").find("rule 8 ·"); k = min([x for x in (i, j) if x >= 0], default=-1)
        return why[k:].split(";")[0][:44] if k >= 0 else None
    if rej_rec:
        for d in ((judge_rec or {}).get("decisions") or []):
            rt_ = _rule_txt(d.get("reason"))
            if rt_: acts.append((_ts(rej_rec.get("scanned_at")) + 2, d.get("name"), f'Dropped {tick(d.get("name"))}', f'{rt_} · MEME', "skip", "skip"))
    for c in (np_.get("candidates") or []):
        rt_ = _rule_txt(c.get("reason"))
        if rt_: acts.append((_ts(np_.get("run_at")), c.get("symbol") or c.get("name"), f'Dropped {tick(c.get("symbol") or c.get("name"))}', f'{rt_} · NEW PAIRS', "skip", "skip"))
    try:
        wl = json.load(open(f"{DESK}/meme_watchlist.json"))
        for v in sorted(wl.values(), key=lambda v: v.get("added_at", ""))[-3:]:
            acts.append((_ts(v.get("added_at")), v.get("name"), f'Watch {tick(v.get("name"))}', (v.get("last_reason") or "waiting for a dip")[:40], "watch", "watch"))
    except Exception: pass
    if np_.get("bought"): acts.append((_ts(np_.get("run_at")), np_["bought"], f'Bought {tick(np_["bought"])}', "NEW PAIRS desk · via pump.fun", "new pair", "buy"))
    acts.sort(key=lambda a: -a[0])
    act_html = "".join(f'<div class="ar"><span class="arl">{logo(nm)}{"<i class=axb>✕</i>" if cls == "skip" else ""}</span><div class="ar-m"><b>{esc(a)}</b><small>{esc(b)} · {tlabel(dt.datetime.fromtimestamp(t, UTC), today)}</small></div><em class="ac-{cls}">{esc(r)}</em></div>'
                       for t, nm, a, b, r, cls in acts[:8]) or '<div class="none">No activity yet.</div>'
    hcc = [h["name"] for h in sorted(hold_items, key=lambda h: -abs(h["upl_pct"]))]
    # ---- live block (SAVIP live): what the browser needs to re-mark open meme positions itself from DexScreener (public, keyless).
    # Only public market facts + the sim book (qty / cost); no keys, no account ids. value = qty x price, P&L = value - cost (same as the server mark).
    lpos = []
    for o in (meme.get("open") or []):
        try:
            last_px = float(o.get("last_price") or o.get("entry_price") or 0); q = float(o.get("qty") or 0)
            lpos.append({"ck": "m_" + str(o.get("pool")), "mint": o.get("token"), "pool": o.get("pool"), "name": tick(o.get("name")),
                         "qty": q, "cost": round(float(o.get("cost_usd") or 0), 6), "last": last_px, "v": round(q * last_px, 6),
                         "desk": o.get("sleeve") or "meme", "entry": float(o.get("entry_price") or 0)})
        except Exception: pass
    ev = next((t for t in trades if t["t"]), None)
    live = {"pos": lpos, "evt": ({"id": f'{int(ev["t"])}-{ev["side"]}-{ev["name"]}', "t": ev["t"], "side": ev["side"], "name": ev["name"], "usd": round(ev["usd"] or 0, 2),
                                 "desk": ev.get("sleeve"), "reason": ev.get("reason") or "", "alpaca": bool(ev.get("alpaca"))} if ev else None),
            "alp_at": NOW.timestamp(), "built": NOW.timestamp(), "ui_v": ui_version()}
    data = {"live": live, "desks": desks, "main": main_desk, "hcc": hcc[:4], "hcc_n": len(hcc), "analysis": an_meta, "n_open": len(hold_items),
            "alp": {"equity": acct["equity"] if acct else None, "last_equity": acct["last_equity"] if acct else None}}
    frag = {"open": hold_html, "hold_head": hold_head, "hold_n": f'{len(hold_items)} open', "analysis": an_html, "an_head": an_head, "activity2": act_html}
    return {"data": data, "frag": frag}

# ======================================================================= CSS
SV_CSS = r"""
:root{--bg:#000;--p1:#0a0a0a;--p2:#0d0d0d;--ln:#1f1f1f;--tx:#fff;--mu:#8a8a8a;--gr:#22e33a;--rd:#ff4d2e;--a:#22e33a;--a2:#169c28;--glow:rgba(34,227,58,.45);--card:#0d0d0d;--line:#1f1f1f;--mut:#8a8a8a;--g:#22e33a;--r:#ff4d2e;--gbg:rgba(34,227,58,.12);--rbg:rgba(255,77,46,.12)}
html,body{background:#000}[hidden]{display:none!important}
body.sv{font-family:Inter,-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:#000;color:#fff;font-size:14px;-webkit-text-size-adjust:100%;-webkit-font-smoothing:antialiased}
.sv .app{max-width:760px;margin:0 auto;padding:10px 10px 26px}
.sv .pos{color:var(--gr)!important}.sv .neg{color:var(--rd)!important}
.hd{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:2px 2px 8px}
.brand{display:flex;align-items:center;gap:9px;min-width:0}.brand svg{flex:0 0 auto}
.brand b{font-size:21px;font-weight:900;letter-spacing:-.3px;white-space:nowrap}.brand .pp2{font-size:10px;font-weight:800;color:#000;background:var(--gr);border-radius:6px;padding:2px 6px;letter-spacing:.5px}
.hdr{display:flex;align-items:center;gap:7px}.vi{display:flex;gap:5px}.vi svg{display:block}
.hdot{width:7px;height:7px;border-radius:50%;background:var(--gr);box-shadow:0 0 8px var(--gr);margin:0 1px 0 4px;animation:hb 1.6s infinite}
@keyframes hb{50%{opacity:.35}}
#clk{font-size:28px;font-weight:900;letter-spacing:-.5px;font-variant-numeric:tabular-nums;line-height:1}#clz{font-size:10px;color:var(--mu);font-weight:700;align-self:flex-end;margin-bottom:3px}
.stl{display:flex;justify-content:space-between;gap:8px;color:#5c5c5c;font-size:11px;margin:-2px 2px 8px}.stl .live{font-size:11px;color:#7a7a7a}.stl .live i{width:6px;height:6px;background:var(--gr);box-shadow:0 0 6px var(--gr)}
.pn{background:var(--p1);border:1px solid var(--ln);border-radius:14px;padding:12px;margin-top:8px;position:relative;min-width:0}
.sph{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:9px;min-height:18px}
.sph>b{font-size:14px;font-weight:700;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sph>span{font-size:11.5px;color:var(--mu);white-space:nowrap}.sph em{font-style:normal;color:var(--rd)}
.sph .lvd{color:var(--mu)}.sph .lvd:before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--rd);margin-right:5px;vertical-align:1px;animation:hb 1.4s infinite}
/* floor */
.floor{padding:10px}.fgrid{display:grid;grid-template-columns:repeat(6,1fr);gap:6px}
.dtile{position:relative;border:1px solid #1b1b1b;border-radius:10px;overflow:hidden;background:#040505;cursor:pointer;aspect-ratio:720/404;grid-column:span 2;-webkit-tap-highlight-color:transparent;transition:border-color .2s}
.dtile.bg2{grid-column:span 3}.dtile:hover{border-color:#333}.dtile canvas,.fone canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.tl{position:absolute;left:6px;bottom:5px;display:flex;align-items:center;gap:5px;font-size:11px;font-weight:800;text-shadow:0 1px 3px #000;background:rgba(0,0,0,.55);border-radius:6px;padding:2px 6px 2px 3px}
.dtile.bg2 .tl{font-size:12.5px}.tl .lg{width:15px;height:15px;font-size:7px}.tl em{font-style:normal}.tl small{color:#777;font-weight:600;font-size:9px}
.tdn{position:absolute;left:7px;top:5px;font-size:8.5px;font-weight:800;letter-spacing:.8px;color:#9a9a9a;text-shadow:0 1px 2px #000}
.fone{position:relative;border-radius:10px;overflow:hidden;background:#040505;aspect-ratio:720/404;border:1px solid #161616}
.flh{display:flex;align-items:center;gap:7px;min-width:0}.flh b{font-size:14px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fback{font:700 11px Inter,-apple-system,sans-serif;color:#000;background:#fff;border:0;border-radius:7px;padding:4px 8px;cursor:pointer;white-space:nowrap}
.fnav{position:absolute;right:8px;bottom:8px;z-index:2;display:flex;gap:4px}.fnav button{font:800 11px Inter,sans-serif;color:#ddd;background:rgba(0,0,0,.7);border:1px solid #2a2a2a;border-radius:8px;width:28px;height:26px;cursor:pointer}
.msr{display:inline-flex;align-items:center;gap:5px}.msr .lg{width:15px;height:15px;font-size:7px}.msr b{color:#fff;font-weight:700}
/* balance */
.bal{padding:12px 12px 6px}.bh{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.sbt{font-size:12px;color:var(--mu)}.bsw{display:flex;gap:4px;margin-top:2px}
.rg{display:flex;gap:2px}.rg button,.bsw button{font:800 11px Inter,-apple-system,sans-serif;color:#9a9a9a;background:none;border:0;border-radius:7px;padding:5px 8px;cursor:pointer}
.rg button.on{background:var(--gr);color:#000;box-shadow:0 0 12px rgba(34,227,58,.35)}
.bsw button{padding:3px 8px;border:1px solid #242424;font-size:10.5px}.bsw button.on{color:#000;background:#fff;border-color:#fff}
.bv{font-size:44px;font-weight:900;letter-spacing:-1.5px;line-height:1.05;margin-top:2px;font-variant-numeric:tabular-nums}
.sbd{font-size:13px;font-weight:700;margin-top:2px}.sbd span{color:var(--mu);font-weight:600}
.b2{font-size:11.5px;color:var(--mu);margin-top:3px;cursor:pointer}.b2 b{color:#d8d8d8}
#balc{width:100%;height:118px;display:block;margin-top:4px;touch-action:pan-y}.btip{position:absolute;right:14px;top:58px;font-size:11px;color:#bbb;text-align:right;pointer-events:none}
/* holdings */
.low{display:grid;grid-template-columns:1fr;gap:0}
.rcol{min-width:0}
.sv .tc.hr{border-radius:11px;padding:8px 6px;border:1px solid transparent;background:transparent;cursor:pointer;-webkit-tap-highlight-color:transparent;min-width:0}
.hr+.hr{margin-top:2px}.sv .hr.hl{background:#141414;border-color:#232323}.sv .hr.open{background:#101010;border-color:#262626}
.hr.xtra{display:none}.hold.all .hr.xtra{display:block}
.hr-r{display:grid;grid-template-columns:34px minmax(0,1fr) 78px auto;align-items:center;gap:9px}
.lg{width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:900;color:#fff;letter-spacing:-.3px;
background:radial-gradient(circle at 30% 28%,hsl(var(--h),85%,62%),hsl(var(--h),70%,30%));box-shadow:inset 0 0 0 1px rgba(255,255,255,.12);flex:0 0 auto}
.hr-n{min-width:0}.hr-n b{font-size:16px;font-weight:800;letter-spacing:-.2px}.msb{font-size:8px;font-weight:800;letter-spacing:.6px;border:1px solid #cfcfcf;border-radius:999px;padding:1px 5px;margin-left:6px;vertical-align:3px;color:#eee}
.hr-by{font-size:11px;color:var(--mu);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.hr-by em{font-style:normal}.hr-by em.it{color:var(--gr)}
.spk{width:78px;height:30px;display:block}
.hr-v{text-align:right;white-space:nowrap}.hr-v b{display:block;font-size:15px;font-weight:800;font-variant-numeric:tabular-nums}
.pl{display:inline-block;font-size:11.5px;font-weight:800;border-radius:6px;padding:1px 6px;margin-top:2px;font-variant-numeric:tabular-nums}
.pl.pos{background:rgba(34,227,58,.13)}.pl.neg{background:rgba(255,77,46,.14)}
.hr-d{display:none;cursor:default;padding:8px 2px 0}.hr.open .hr-d{display:block}.hr-pl{font-size:12.5px;color:var(--mu);margin-bottom:4px}
.sv .hr .tc-g{grid-template-columns:1fr 1fr}.sv .kv2 span{color:#777}.sv .kv2 b{font-size:13px}.sv .tc-x{border-top-color:#222;font-size:12.5px}
.sv .hr .chint{display:none}.sv .hr.open .chint{display:block;text-align:right;color:#777;font-size:11.5px}
.sv .hr .tc-chart{margin:6px 0 0}.hmore{width:100%;margin-top:6px;font:700 12px Inter,-apple-system,sans-serif;color:#bbb;background:#101010;border:1px solid #222;border-radius:10px;padding:9px;cursor:pointer}
.hold.all .hmore{display:none}
/* analysis */
.ana{padding:10px}.an{position:relative}.anc{display:none;position:relative;border-radius:10px;overflow:hidden;background:#050505;border:1px solid #171717;height:236px}.anc.on{display:block}
.anch{position:absolute;inset:0;width:100%;height:100%}
.anr{position:absolute;left:8px;top:10px;background:rgba(8,8,8,.82);border:1px solid #232323;border-radius:8px;padding:5px 8px;backdrop-filter:blur(2px);-webkit-backdrop-filter:blur(2px);max-width:calc(100% - 16px)}
.ru{display:grid;grid-template-columns:12px minmax(0,1fr) auto 38px;gap:6px;align-items:center;font-size:10.5px;line-height:1.55;color:#ddd}
.ru i{font-style:normal;color:#777}.ru span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ru em{font-style:normal;color:#8a8a8a;font-variant-numeric:tabular-nums;white-space:nowrap;max-width:92px;overflow:hidden;text-overflow:ellipsis}
.ru b{font-size:10px;font-weight:900;text-align:right}.ru b.ps{color:var(--gr)}.ru b.dr{color:var(--rd)}.ru.jr{border-top:1px solid #222;margin-top:2px;padding-top:2px}
.ann{position:absolute;left:8px;bottom:22px;display:flex;align-items:center;gap:6px;text-decoration:none;color:#fff}.ann .lg{width:20px;height:20px;font-size:8px}.ann b{font-size:13px;font-weight:900;text-shadow:0 1px 3px #000}.ann small{font-size:9.5px;color:#888}
.anv{position:absolute;left:8px;right:8px;bottom:5px;font-size:9.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.anv.ps{color:var(--gr)}.anv.dr{color:#ff7a5c}
.andots{display:flex;justify-content:center;gap:5px;margin-top:7px}.andots i{width:5px;height:5px;border-radius:50%;background:#333}.andots i.on{background:#fff}
/* activity */
.act{padding:10px 10px 6px}.ar{display:grid;grid-template-columns:26px minmax(0,1fr) auto;align-items:center;gap:8px;padding:6px 2px}.ar+.ar{border-top:1px solid #141414}
.ar .lg{width:24px;height:24px;font-size:8.5px}.ar-m b{display:block;font-size:13px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ar-m small{display:block;font-size:10.5px;color:var(--mu);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ar em{font-style:normal;font-size:13px;font-weight:800;white-space:nowrap;font-variant-numeric:tabular-nums}.ac-skip{color:#ff6a2e}.ac-watch{color:var(--gr)}.ac-buy{color:#fff}.ac-pos{color:var(--gr)}.ac-neg{color:var(--rd)}
/* collapsed legacy sections in the same black theme */
.sv .more2{margin-top:14px}.sv .more2>h3{color:#5a5a5a;font-size:11px;letter-spacing:2px}
.sv details.sec{background:var(--p1);border:1px solid var(--ln);border-radius:14px}.sv details.sec>summary{color:#e6e6e6;font-size:14px}.sv details.sec>summary:after{color:var(--gr)}
.sv .card,.sv .card2,.sv .tile2,.sv .tc,.sv .bot{background:#0d0d0d;border-color:#1f1f1f}.sv .tc.tc-pos,.sv .tc.tc-neg{background:#0d0d0d}
.sv .card2{border-radius:14px}.sv .tiles .tile{background:#0d0d0d;border-color:#1f1f1f}
.sv .tag,.sv .rchip b,.sv .rt a,.sv .lead,.sv .tsl a,.sv .tt,.sv details summary{color:#9be8a6}.sv .lead{border-color:#1d5e27}
.sv .chip.on{background:rgba(34,227,58,.12);border-color:var(--gr);color:#b8f5c0}.sv .s-active{background:var(--gr);color:#000}.sv .s-idle{border-color:var(--gr);color:#b8f5c0}
.sv .badge-n,.sv .paper,.sv .vd-pick{background:var(--gr);color:#000}.sv .bar b{background:linear-gradient(90deg,#169c28,#22e33a)}
.sv td,.sv th{border-bottom-color:#1a1a1a}.sv .ln{border-bottom-color:#1a1a1a}.sv .seg{background:#151515}.sv .seg button.on,.sv .tfb.on{background:var(--gr);color:#000;border-color:var(--gr)}
.sv .tfb,.sv .cl a,.sv .lvb{background:#151515;border-color:#262626;color:#ddd}.sv .clh{color:#777}.sv .err{border-color:#5a2a20;color:#ff8a70;background:#120806}
.sv .foot{color:#444}.sv .cr{border-bottom-color:#1a1a1a}.sv .tf,.sv .tr span{color:#777}
.sv .chbox{border-top-color:#222}
@media(min-width:700px){.sv .app{max-width:780px}.low{grid-template-columns:minmax(0,1.38fr) minmax(0,1fr);gap:8px}.anc{height:226px}}
@media(min-width:1100px){.sv .app{max-width:1440px;padding:14px 18px 30px}
 .lay{display:grid;grid-template-columns:minmax(0,1.32fr) minmax(0,1fr);gap:0 10px;align-items:start}
 .lcol{min-width:0}.low{grid-template-columns:1fr;gap:0}.anc{height:250px}#balc{height:170px}}
@media(min-width:1400px){.rcol{display:grid;grid-template-columns:1fr 1fr;gap:0 8px}}
@media(max-width:420px){.brand b{font-size:18px}#clk{font-size:24px}.bv{font-size:38px}.vi{display:none}.hr-r{grid-template-columns:32px minmax(0,1fr) 62px auto;gap:7px}.spk{width:62px}.hr-n b{font-size:15px}.hr-v b{font-size:14px}}
@media(prefers-reduced-motion:reduce){.hdot,.sph .lvd:before{animation:none}}

.lg{position:relative;overflow:hidden;flex:none}.lg .lgi{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:inherit;background:#0d0d0d}
.hcc{display:flex;align-items:center;margin-right:4px}.hcc .lg{width:22px;height:22px;font-size:8px;box-shadow:0 0 0 2px #000;margin-left:-7px}.hcc .lg:first-child{margin-left:0}
.hcc .more{font-size:10px;color:#8a8a8a;font-weight:700;margin-left:4px}
.fone{aspect-ratio:auto!important;overflow:visible!important;background:none!important;border:0!important;border-radius:0!important}
.fone .fcv{position:relative;aspect-ratio:720/404;border-radius:10px;overflow:hidden;background:#040505;border:1px solid #161616}
.fone .fnav{position:static;display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:8px}
.fone .fnav span{font:800 11px Inter,-apple-system,sans-serif;color:#9a9a9a;letter-spacing:.6px;text-transform:uppercase}
.fone .fnav button{width:44px;height:30px;font-size:15px}
.hcc2{display:none!important}


/* ===== SAVIP v2 1:1 pass (2026-10-21): geometry measured on the reference frames at 747 px ===== */
html,body,body.sv{background:#010205}
.sv .app{max-width:1040px;padding:0 7px 26px}
.sv .hd{margin:0 -7px;height:44px;padding:0 12px;background:linear-gradient(180deg,#0f1015,#17181d);border-bottom:1px solid #1f2026;gap:8px}
.brand{gap:7px}.brand b{font-size:21px;font-weight:800;letter-spacing:-.2px}.brand .pp2{font-size:8.5px;padding:2px 5px;border-radius:9px;letter-spacing:.6px;background:#d946b0;color:#fff}
.hdr{gap:6px}.vi{gap:8px;align-items:center}.vi svg{width:20px;height:20px}
.hdv{width:1px;height:22px;background:#2a2b31;margin:0 3px 0 4px}
.hdot{width:6px;height:6px;margin:0 2px 0 0;box-shadow:0 0 7px var(--gr)}
#clk{font-size:27px;font-weight:800;letter-spacing:-.3px}#clz{font-size:8.5px;letter-spacing:.8px;color:#8d8e94;margin-bottom:4px}
.hcc{margin-right:2px}.hcc .lg{width:20px;height:20px;box-shadow:0 0 0 2px #121318}
.pn{background:#0b0c11;border:1px solid #15161b;border-radius:12px;margin-top:6px}
.sph{margin-bottom:0}.sph>b,.flh b{font-size:13px;font-weight:700}.sph>span{font-size:10.5px;color:#8b8c92}
/* floor: fixed scene ratio body (734x412), grid of 2 big + 3 small tiles centred inside, single scene edge to edge */
.floor{padding:0!important;overflow:hidden}.floor .sph{height:27px;padding:0 11px 0 10px;align-items:center}
.fbd{position:relative;aspect-ratio:734/412;width:100%}
.fgrid{position:absolute;inset:0;padding:0 6px;align-content:center;gap:6px}
.dtile{aspect-ratio:720/404;border:1px solid #1c1d25;border-radius:8px;background:#03050b}
.tl{left:7px;bottom:6px;background:none;padding:0;gap:4px;font-size:10.5px;text-shadow:0 1px 3px #000,0 0 6px #000}.dtile.bg2 .tl{font-size:12px}.tl .lg{width:14px;height:14px}
.tdn{font-size:7.5px;color:#7d7e86;left:6px;top:4px;letter-spacing:.7px}
.fone{position:absolute!important;inset:0}.fone .fcv{position:absolute;inset:0;aspect-ratio:auto;border:0;border-radius:0;background:#03050b}
.fone .fnav{position:absolute;left:8px;bottom:8px;margin:0;gap:5px;justify-content:flex-start;z-index:2}.fone .fnav span{display:none}
.fone .fnav button{width:26px;height:22px;font-size:12px;border-radius:7px;background:rgba(0,0,0,.6);border:1px solid #2a2b31;color:#ddd}
.fback{font-size:10px;padding:3px 7px;border-radius:6px;margin-right:2px}
.msr{gap:4px}.msr b{font-weight:800}.msr .lg{width:13px;height:13px}
/* balance */
.bal{padding:13px 13px 0!important;height:186px;overflow:hidden}
.bh{align-items:center}.sbt{font-size:12px;color:#9b9ca2}
.bctl{display:flex;align-items:center;gap:10px}.bsw{margin:0;gap:2px}
.rg{gap:3px}.rg button,.bsw button{font:800 9.5px Inter,-apple-system,sans-serif;color:#a2a3a8;padding:3px 8px;border-radius:9px;border:0;background:none}
.rg button.on{background:#19c919;color:#000;box-shadow:none}.bsw button.on{background:none;color:#fff;box-shadow:inset 0 0 0 1px #4a4b52}
.bv{font-size:46px;font-weight:800;letter-spacing:-1.2px;line-height:1;margin-top:7px}
.sbd{font-size:12.5px;font-weight:600;margin-top:5px}.sbd span{color:#9b9ca2;font-weight:500}
.b2{display:none}
#balc{position:absolute;left:5px;bottom:0;width:calc(100% - 10px);height:98px;margin:0}.btip{top:14px;right:150px}
/* lower row: holdings | analysis + activity */
.hold{padding:10px 6px 6px!important}.hold .sph{padding:0 4px;margin-bottom:8px}#f-hold_n{display:none}
.sv .tc.hr{padding:9px 9px 9px 9px;border-radius:12px}.hr+.hr{margin-top:3px}.sv .hr.hl{background:#13141a;border-color:#1f2027}
.hr-r{grid-template-columns:34px minmax(0,1fr) 82px auto;gap:10px}.hr-r>.lg{width:34px;height:34px}
.hr-n b{font-size:15.5px}.msb{font-size:7.5px;padding:1px 5px;border-color:#d8d8d8;margin-left:5px}.hr-by{font-size:10.5px;color:#8c8d93;margin-top:1px}
.spk{width:82px;height:30px}.hr-v b{font-size:14.5px}.pl{font-size:11px;padding:1px 6px;border-radius:5px;margin-top:3px}
.ana{padding:10px 6px 6px!important}.ana .sph,.act .sph{padding:0 4px;margin-bottom:8px}.ana .sph>b,.act .sph>b{font-size:13.5px;font-weight:800}
.anc{height:176px;border-radius:7px;background:#05060a;border:1px solid #1a1b21}
.anb{position:absolute;left:0;right:62px;top:0;height:21px;display:flex;align-items:center;gap:7px;padding:0 6px;border-bottom:1px solid #15161c;background:#090a0f;overflow:hidden;white-space:nowrap}
.anb span{display:flex;flex-direction:column;line-height:1.05}.anb i{font-style:normal;font-size:5.5px;color:#6e7078}.anb b{font-size:7px;font-weight:800;color:#e8e8e8}
.anb .anbt{flex-direction:row;align-items:center;gap:3px;margin-right:2px}.anb .anbt b{font-size:8px}.anb .anbt small{font-size:5.5px;color:#777}.anb .lg{width:11px;height:11px;font-size:5px}
.anm{position:absolute;left:0;right:62px;top:22px;bottom:0}.anm .anch{position:absolute;left:0;top:0;width:100%;height:calc(100% - 10px)}
.anx{position:absolute;left:4px;right:4px;bottom:1px;display:flex;justify-content:space-between;font-size:5.5px;color:#5d5f67}
.ans{position:absolute;right:0;top:0;bottom:0;width:61px;border-left:1px solid #15161c;background:#07080c;display:flex;flex-direction:column}
.ansm{position:relative;flex:1;border-bottom:1px solid #121318;overflow:hidden}.ansm .ansv{position:absolute;inset:0;width:100%;height:100%}.ansm em{position:absolute;left:3px;top:2px;font-style:normal;font-size:5.5px;color:#888;font-weight:700}
.anr{left:118px;top:30px;padding:4px 7px;border-radius:6px;background:rgba(8,9,13,.86);border:1px solid #1d1e25}
.ru{grid-template-columns:10px minmax(0,1fr) auto 30px;gap:5px;font-size:10px;line-height:1.5}.ru span{color:#f0f0f0;font-weight:600}.ru em{font-size:8.5px;max-width:52px}.ru b{font-size:9.5px}
.ann{left:7px;bottom:8px}.ann .lg{width:16px;height:16px}.ann b{font-size:12.5px}.ann small{display:none}
.anv,.andots{display:none!important}
.act{padding:10px 10px 4px!important}.act .sph .lvd{font-size:10.5px}
.ar{grid-template-columns:24px minmax(0,1fr) auto;gap:8px;padding:4px 0}.ar+.ar{border-top:0}
.arl{position:relative;width:22px;height:22px}.arl .lg{width:22px;height:22px;font-size:8px}
.axb{position:absolute;right:-3px;bottom:-3px;width:11px;height:11px;border-radius:50%;background:#ff5a1f;color:#fff;font:900 7px/11px Inter,sans-serif;text-align:center;font-style:normal;box-shadow:0 0 0 1.5px #0b0c11}
.ar-m b{font-size:12.5px}.ar-m small{font-size:10px;color:#8a8b91}.ar em{font-size:12px}
.sv .stl{margin:12px 4px 0}
@media(min-width:700px){.low{grid-template-columns:minmax(0,1.453fr) minmax(0,1fr);gap:7px}.anc{height:176px}}
@media(min-width:1100px){.sv .app{max-width:1040px;padding:0 7px 30px}.lay{display:block}.low{grid-template-columns:minmax(0,1.453fr) minmax(0,1fr);gap:7px}.rcol{display:block}.anc{height:230px}#balc{height:98px}}
@media(max-width:420px){.brand b{font-size:17px}.brand svg{width:22px;height:22px}#clk{font-size:24px}.hdv{display:none}.hcc .lg:nth-child(n+4),.hcc .more{display:none}.hcc .lg{width:16px;height:16px;margin-left:-5px}
 .bv{font-size:40px}.bal{height:178px}.bctl{gap:4px}.rg button,.bsw button{padding:3px 6px}}
.bal{padding:10px 13px 0!important}.bh{height:16px}.bv{margin-top:2px}.sbd{margin-top:4px}
.hold{padding-top:9px!important}.hold .sph{margin-bottom:5px}.sv .tc.hr{padding:7px 9px}
.ana{padding-top:9px!important}.ana .sph{margin-bottom:5px}.anc{height:171px}
.act{padding-top:9px!important}.act .sph{margin-bottom:4px}.ar{padding:3px 0;min-height:30px}.ar+.ar{margin-top:2px}
.anr{max-width:158px;left:110px;top:28px}.ru{grid-template-columns:9px minmax(0,1fr) auto 28px}.ru em{max-width:40px}
.fback{background:#1a1b21!important;color:#ddd!important;border:1px solid #2a2b31!important;width:22px;height:20px;padding:0!important;font-size:13px!important;line-height:18px;border-radius:6px!important}
.flh b,#fl-t{color:#fff!important}.bv{font-size:48px}.sbt{font-size:12.5px}.rg button,.bsw button{font-size:10px;padding:4px 9px}.brand b{font-weight:900}
.ru{font-size:9.5px;grid-template-columns:9px minmax(0,1fr) auto 27px}.ru em{max-width:34px;font-size:8px}.anr{max-width:150px}
@media(max-width:420px){.hcc{display:flex!important}.bal{height:206px}.bh{height:auto;flex-wrap:wrap;row-gap:6px}.sbt{white-space:nowrap}.bctl{width:100%;justify-content:space-between}
 .tl small{display:none}.dtile .tl{font-size:9.5px}.dtile.bg2 .tl{font-size:10.5px}.brand .pp2{font-size:7.5px;padding:2px 4px}}
/* SAVIP v3 floor zoom */
.fbd{overflow:hidden}.fone,.fmon{transform-origin:0 0;will-change:transform}.fmon{position:absolute;inset:0;z-index:3;background:#03050b}.fmon canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.fone{z-index:2}.fone .fnav{display:none!important}.fone canvas{touch-action:pan-y}.fmon{touch-action:pan-y}
.dtile{touch-action:manipulation;transition:border-color .15s,box-shadow .15s,transform .12s;outline:0}.dtile.press{transform:scale(.975);border-color:#fff!important}
.dtile:focus-visible{border-color:#fff;box-shadow:0 0 0 1px #fff}
@media(hover:hover){.dtile:hover{border-color:#fff;box-shadow:0 0 0 1px rgba(255,255,255,.85),0 0 16px rgba(255,255,255,.12)}}
.fback{display:inline-flex!important;align-items:center;gap:4px;width:auto!important;height:22px!important;padding:0 10px 0 7px!important;border-radius:999px!important;background:#fff!important;color:#000!important;border:0!important;
 font:800 11px Inter,-apple-system,sans-serif!important;line-height:22px!important;margin-right:6px;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;transition:transform .1s,background .1s}
.fback i{font-style:normal;font-size:12px;line-height:1}.fback.press,.fback:active{transform:scale(.94);background:#d9d9d9!important}.fback[hidden]{display:none!important}
.floor.mz #fl-r .msr{margin-left:0}.floor.mz #fl-r{font-size:0}.floor.mz #fl-r .msr{font-size:10.5px}
/* SAVIP live */
#clk{white-space:nowrap}#clk .ccol{animation:ccol 1s steps(1) infinite}@keyframes ccol{50%{opacity:.35}}
#clk.roll{animation:croll .45s cubic-bezier(.2,.8,.2,1)}@keyframes croll{0%{transform:translateY(-40%);opacity:0}100%{transform:none;opacity:1}}
.hdot{transition:background .3s,box-shadow .3s}.hdot.stale{background:#f5a524!important;box-shadow:0 0 6px #f5a524!important}.hdot.off{background:#6b6b70!important;box-shadow:none!important}
.lvup{animation:lvup 1s ease-out}.lvdn{animation:lvdn 1s ease-out}
@keyframes lvup{0%{background:rgba(34,227,58,.35);color:#fff}100%{}}@keyframes lvdn{0%{background:rgba(255,77,46,.35);color:#fff}100%{}}
.bv.lvup,.bv.lvdn{border-radius:8px}
.bdot{position:absolute;width:9px;height:9px;margin:-4.5px 0 0 -4.5px;border-radius:50%;background:currentColor;pointer-events:none;z-index:2;box-shadow:0 0 10px currentColor}
.bdot:after{content:"";position:absolute;inset:-1px;border-radius:50%;border:2px solid currentColor;animation:bpulse 1.6s ease-out infinite}
@keyframes bpulse{0%{transform:scale(1);opacity:.8}100%{transform:scale(3.2);opacity:0}}
.lvst{display:inline-flex;gap:8px;font-size:9.5px;color:#7d7e85;font-weight:600}.lvst .lvm{color:#22e33a}.hold .sph{align-items:center}
.ar.lvnew{animation:arin .55s cubic-bezier(.2,.8,.2,1) both}@keyframes arin{0%{transform:translateY(-14px);opacity:0;background:rgba(34,227,58,.12)}60%{opacity:1}100%{transform:none;background:transparent}}
.spk .spd{animation:ccol 1.2s steps(1) infinite}
@media(prefers-reduced-motion:reduce){#clk.roll,.ar.lvnew,.bdot:after,#clk .ccol{animation:none}}
"""

def logo_svg(k, s=18):
    if k in ("pill", "pill2"):
        return (f'<svg width="{s}" height="{s}" viewBox="0 0 20 20"><rect width="20" height="20" rx="5" fill="#0f2a14"/><g transform="rotate(-45 10 10)"><rect x="3" y="7" width="14" height="6" rx="3" fill="#fff"/>'
                f'<path d="M10 7h4a3 3 0 0 1 0 6h-4z" fill="#22e33a"/></g></svg>')
    if k == "alpaca": return f'<svg width="{s}" height="{s}" viewBox="0 0 20 20"><rect width="20" height="20" rx="5" fill="#f5c518"/><text x="10" y="14.5" text-anchor="middle" font-size="12" font-weight="900" fill="#000" font-family="Arial">A</text></svg>'
    if k == "btc": return f'<svg width="{s}" height="{s}" viewBox="0 0 20 20"><circle cx="10" cy="10" r="10" fill="#f7931a"/><text x="10" y="14.5" text-anchor="middle" font-size="12" font-weight="900" fill="#fff" font-family="Arial">₿</text></svg>'
    return f'<svg width="{s}" height="{s}" viewBox="0 0 20 20"><rect width="20" height="20" rx="5" fill="#1d4ed8"/><path d="M5 14V10M9 14V6M13 14V9M16 14V5" stroke="#fff" stroke-width="2"/></svg>'
BRAND_SVG = ('<svg width="26" height="26" viewBox="0 0 26 26"><path d="M3 22.5V12a10 10 0 0 1 20 0v10.5l-3.3-2.6-3.3 2.6-3.4-2.6-3.3 2.6-3.4-2.6z" fill="#f4f4f4"/>'
             '<ellipse cx="9.6" cy="12.2" rx="2.1" ry="2.9" fill="#0b0c11"/><ellipse cx="16.4" cy="12.2" rx="2.1" ry="2.9" fill="#0b0c11"/><circle cx="10.3" cy="11.2" r=".8" fill="#fff"/><circle cx="17.1" cy="11.2" r=".8" fill="#fff"/></svg>')

def ui_version():
    """hash of everything that needs a page reload to change (CSS + JS + scene). data.json carries it; the page reloads only when it differs."""
    import hashlib
    try: scene = open(os.environ.get("DESK_SCENE_JS") or f"{DESK}/dash_scene.js").read()
    except Exception: scene = ""
    return hashlib.sha1((SV_CSS + UI_JS + SV_LIVE_JS + SV_RELOAD_JS + scene).encode()).hexdigest()[:12]

def page(G, SV):
    frag = G["frag"]; esc_ = esc
    d0 = SV["data"]["desks"]; md = SV["data"]["main"]
    def tile(i, d):
        pc = d["pct"]
        return (f'<div class="dtile{" bg2" if i < 2 else ""}" data-d="{i}" role="button" tabindex="0" aria-label="{esc_(d["label"])} desk"><canvas></canvas><div class="tdn">{esc_(d["label"])}</div>'
                f'<div class="tl">{logo(d["ticker"])}<b>{esc_(d["ticker"])}</b><em class="{"pos" if pc >= 0 else "neg"}">{spct(pc, 1)}</em>{"<small>" + esc_(d["note"]) + "</small>" if d["note"] != "open" else ""}</div></div>')
    tiles = "".join(tile(i, d) for i, d in enumerate(d0))
    mdd = d0[md] if d0 else None
    msr = (f'main screen: <span class="msr">{logo(mdd["ticker"])}<b>{esc_(mdd["ticker"])}</b> <em class="{"pos" if mdd["pct"] >= 0 else "neg"}" style="font-style:normal">{spct(mdd["pct"], 1)}</em></span>') if mdd else ""
    vi = "".join(f'<span title="{t}">{logo_svg(k, 18)}</span>' for k, t in (("pill", "pump.fun / PumpSwap"), ("alpaca", "Alpaca paper"), ("btc", "Alpaca crypto")))
    LW = G["LW_JS"]
    hcc = "".join(logo(n) for n in SV["data"].get("hcc") or []) + (f'<span class="more">+{SV["data"]["hcc_n"] - 4}</span>' if SV["data"].get("hcc_n", 0) > 4 else "")
    scene = SCENE_JS
    if not os.environ.get("DESK_SCENE_V1"):
        try: scene = open(os.environ.get("DESK_SCENE_JS") or f"{DESK}/dash_scene.js").read()   # SAVIP v2 detailed floor; missing/unreadable -> v1 scene below
        except Exception: scene = SCENE_JS
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="desk-ui" content="{ui_version()}">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<noscript><meta http-equiv="refresh" content="60"></noscript>
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Grok Desk">
<meta name="theme-color" content="#000000"><meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png"><link rel="icon" type="image/png" href="apple-touch-icon.png">
<title>GROKBOT DESK (Paper) · {SV["data"]["n_open"]} open</title><style>{G["CSS"]}{G["LIVE_CSS"]}{G["CSS2"]}{G["CSS3"]}{SV_CSS}</style></head><body class="v2 sv"><div class="app">
<header class="hd"><div class="brand">{BRAND_SVG}<b>GROKBOT DESK</b><span class="pp2">PAPER</span></div>
<div class="hdr"><span class="hcc" title="open positions">{hcc}</span><span class="vi">{vi}</span><i class="hdv"></i><i class="hdot" id="hdot" title="live"></i><b id="clk">{G["NOW"].astimezone(BER).strftime("%H:%M")}</b><small id="clz">{"CEST" if G["NOW"].astimezone(BER).dst() else "MEZ"}</small></div></header>
<div id="f-errors">{frag["errors"]}</div>
<div class="lay"><div class="lcol">
<section class="pn floor" id="floor"><div class="sph"><span class="flh"><button type="button" class="fback" id="fl-back" hidden aria-label="back"><i>←</i><span>Zurück</span></button><b id="fl-t">{len(d0)} desks live</b></span><span id="fl-r">pick a desk</span></div>
<div class="fbd"><div class="fgrid" id="fl-grid">{tiles}</div>
<div class="fone" id="fl-one" hidden><div class="fcv"><canvas aria-label="desk floor, tap a monitor to enlarge it"></canvas></div></div><div class="fmon" id="fl-mon" hidden><canvas aria-label="enlarged monitor"></canvas></div></div>
<div id="fl-msr" hidden>{msr}</div></section>
<section class="pn bal" id="bal"><div class="bh"><div class="sbt" id="bt">Desk balance · {len(d0)} desks</div><div class="bctl"><div class="bsw" id="bsw"><button type="button" data-s="meme" class="on">MEME</button><button type="button" data-s="alp">ALPACA</button></div>
<div class="rg" id="brg"><button type="button" data-r="live" class="on">LIVE</button><button type="button" data-r="1h">1H</button><button type="button" data-r="1d">1D</button><button type="button" data-r="1w">1W</button></div></div></div>
<div class="bv" id="bv">{usd(G["equity"])}</div><div class="sbd" id="bdl"></div><div class="b2" id="b2"></div><canvas id="balc"></canvas><i class="bdot" id="bdot" hidden></i><div class="btip" id="btip"></div></section>
</div><div class="low">
<section class="pn hold" id="hold"><div class="sph"><b id="f-hold_head">{frag["hold_head"]}</b><span id="f-hold_n">{frag["hold_n"]}</span><span class="lvst" id="lvst"></span></div><div id="f-open">{frag["open"]}</div></section>
<div class="rcol"><section class="pn ana"><div class="sph"><b>Judge · analysis</b><span id="f-an_head">{frag["an_head"]}</span></div><div class="an" id="f-analysis">{frag["analysis"]}</div></section>
<section class="pn act"><div class="sph"><b>Activity</b><span class="lvd">live</span></div><div id="f-activity2">{frag["activity2"]}</div></section></div>
</div></div>
<div class="more2"><h3>MEHR (ZUM AUFKLAPPEN)</h3>
<details class="sec" id="d-konten"><summary>Konten &amp; Status (Meme-Bank · Alpaca · Kill-Switch)</summary><div class="body"><div id="f-header">{frag["header"]}</div></div></details>
<details class="sec" id="d-eq"><summary>Equity-Chart (Detail · $/% · Trade-Marker)</summary><div class="body"><section class="card2 eqs" id="eqbox"><div class="eqh"><div class="seg"><button type="button" data-k="s" data-v="meme">Meme-Bank</button><button type="button" data-k="s" data-v="alp">Alpaca</button></div>
<div class="seg"><button type="button" data-k="u" data-v="usd">$</button><button type="button" data-k="u" data-v="pct">%</button></div></div>
<div style="margin-top:8px"><span class="eqv" id="eqv"></span> <span id="eqd" class="eqd"></span><div id="eqz" style="font-size:13.5px;font-weight:600"></div></div>
<div id="eqc"></div><div class="eqr"><div class="seg"><button type="button" data-k="r" data-v="today">Heute</button><button type="button" data-k="r" data-v="7d">7 Tage</button><button type="button" data-k="r" data-v="all">Alles</button></div><div class="eqtt" id="eqtt"></div></div>
<div class="eqn" id="eqnote">Meme-Bank = Desk-Equity aus history.csv (alle 5 Min) · Alpaca = Paper-Konto (Portfolio-History) · Pfeile = größte Trades</div></section></div></details>
<details class="sec" id="d-closed"><summary>Heute geschlossen</summary><div class="body" id="f-closed">{frag["closed"]}</div></details>
<details class="sec" id="d-learn"><summary>Lernt dazu (Self-Learner)<span class="sm" id="f-s_learn">{frag["s_learn"]}</span></summary><div class="body" id="f-learn">{frag["learn"]}</div></details>
<details class="sec" id="d-chart"><summary>Kontostand-Verlauf (Detail)<span class="sm" id="f-s_chart">{frag["s_chart"]}</span></summary><div class="body" id="f-chart">{frag["chart"]}</div></details>
<details class="sec" id="d-shadow"><summary>Shadow-Trades<span class="sm" id="f-s_shadow">{frag["s_shadow"]}</span></summary><div class="body" id="f-shadow">{frag["shadow"]}</div></details>
<details class="sec" id="d-control"><summary>Kontroll-Bot<span class="sm" id="f-s_control">{frag["s_control"]}</span></summary><div class="body" id="f-control">{frag["control"]}</div></details>
<details class="sec" id="d-rejtrack"><summary>Reject-Tracker<span class="sm" id="f-s_rejtrack">{frag["s_rejtrack"]}</span></summary><div class="body" id="f-rejtrack">{frag["rejtrack"]}</div></details>
<details class="sec" id="d-rejects"><summary>Scan-Ablehnungen &amp; Watchlist</summary><div class="body" id="f-rejects">{frag["rejects"]}</div></details>
<details class="sec" id="d-newpairs"><summary>New-Pairs-Scanner</summary><div class="body" id="f-newpairs">{frag["newpairs"]}</div></details>
<details class="sec" id="d-review"><summary>Wochen-Review<span class="sm" id="f-s_review">{frag["s_review"]}</span></summary><div class="body" id="f-review_body">{frag["review_body"]}</div></details>
<details class="sec" id="d-bots"><summary>Bots / Pipeline</summary><div class="body"><div class="bots" id="f-bots">{frag["bots"]}</div></div></details>
<details class="sec" id="d-dial"><summary>Quant-Dial &amp; Gewinnquote</summary><div class="body" id="f-dial">{frag["dial"]}</div></details>
<details class="sec" id="d-schedule"><summary>Zeitplan &amp; Kill-Switch</summary><div class="body" id="f-schedule">{frag["schedule"]}</div></details>
<details class="sec" id="d-positions"><summary>Alpaca-Orders &amp; Rohpositionen</summary><div class="body" id="f-positions">{frag["positions"]}</div></details>
<details class="sec" id="d-activity"><summary>Aktivitäts-Log</summary><div class="body" id="f-activity">{frag["activity"]}</div></details>
<details class="sec" id="d-research"><summary>Research-Status</summary><div class="body" id="f-research">{frag["research"]}</div></details>
<details class="sec" id="d-honest"><summary>Hinweis</summary><div class="body honest"><p>Nur Paper-Trading. Meme: virtuelle Bank (Start {usd(G["start"])}{(" = " + format(G["bank"].get("start_eur"), ".2f" if G["bank"].get("sol_eur_start") else ".0f") + " €" + (" = 1 SOL @ " + format(G["bank"]["sol_eur_start"], ".2f") + " €/SOL" if G["bank"].get("sol_eur_start") else "") + ", Epoche " + str(G["bank"].get("epoch", 1)) + " seit " + G["bank"].get("started_at", "")[:16].replace("T", " ")) if G["bank"].get("start_eur") else ""}), simulierte pump.fun-Fills.{"".join(f" Vorperiode {e['epoch']}: {e['started_at'][:10]} bis {e['ended_at'][:16].replace('T', ' ')}, Start {usd(e['start_usd'])} → Ende {usd(e['end_equity_usd'])} ({e['realized_usd']:+.2f} $ realisiert, {e['closed_trades']} Verkäufe, {e['wins']}W/{e['losses']}L), archiviert in {e['archive']}." for e in G["bank"].get("epochs", []))} TREND/STOCKS/CRYPTO: Alpaca-PAPER-Konto (eigenes Buch, Start $100.000). Vergangene Ergebnisse garantieren nichts.</p></div></details>
</div>
<div class="stl"><span id="live" class="live"><i></i><span id="live-t">live</span></span><span>built <span id="f-gen">{frag["gen"]}</span></span></div>
<div class="foot">Alpaca Paper + pump.fun SIMULIERT · keine Wallets · Live-Zahlen aus data.json alle 15 s · Desk-Floor = Canvas-Pixel-Art aus echten Positionen</div>
</div><script id="embedded" type="application/json">{G["data_js"].replace("</", "<\\/")}</script><script id="charts-embedded" type="application/json">{{}}</script><script>{G["JS"]}</script><script>{SV_LIVE_JS}</script><script>{G["KEEP_JS"]}</script><script>{LW}</script><script>{G["CHART_JS"]}</script><script>{G["EQ_JS"]}</script><script>{scene}</script><script>{UI_JS}</script><script>{SV_RELOAD_JS}</script></body></html>"""

# ======================================================================= JS: pixel-art desk floor (canvas)
SCENE_JS = r"""(function(){
var W=720,H=414,DPR=Math.min(2,window.devicePixelRatio||1);
var SPR={blob:["...XXXX...",".XXXXXXXX.","XXXXXXXXXX","XXWWXXWWXX","XXWKXXWKXX","XXXXXXXXXX","XXXXXXXXXX",".XXXXXXXX.",".XX.XX.XX."],
 ghost:["...XXXX...",".XXXXXXXX.","XXXXXXXXXX","XXKKXXKKXX","XXKKXXKKXX","XXXXXXXXXX","XXXXXXXXXX","XXXXXXXXXX","X.XX..XX.X"],
 spiky:["X...XX...X",".XXXXXXXX.","XXXXXXXXXX","XWWXXXXWWX","XWKXXXXWKX","XXXXXXXXXX",".XXXXXXXX.","XX.XXXX.XX","X........X"]};
var BOT={SCAN:['#2dd4bf','blob'],JUDGE:['#a78bfa','spiky'],SIZE:['#fb923c','blob'],FILLS:['#ff5a1f','spiky'],RISK:['#ef4444','blob'],QUANT:['#60a5fa','blob'],
 CHIEF:['#f2f2f2','ghost'],TREND:['#f5c518','blob'],STOCKS:['#38bdf8','blob'],CRYPTO:['#f59e0b','spiky']};
var SLOTS=[[178,174],[300,174],[422,174],[178,250],[300,250],[422,250]];
function A(hex,a){var n=parseInt(hex.slice(1),16);return'rgba('+(n>>16)+','+((n>>8)&255)+','+(n&255)+','+a+')'}
function R(c,x,y,w,h,f){c.fillStyle=f;c.fillRect(x,y,w,h)}
function SR(c,x,y,w,h,s,lw){c.strokeStyle=s;c.lineWidth=lw||1;c.strokeRect(x+.5,y+.5,w-1,h-1)}
function RR(c,x,y,w,h,r){c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath()}
function T(c,s,x,y,sz,col,al,wt){c.font=(wt||'700')+' '+sz+'px ui-monospace,"SF Mono",Menlo,Consolas,monospace';c.fillStyle=col;c.textAlign=al||'left';c.textBaseline='alphabetic';c.fillText(s,x,y)}
function hue(s){var h=0;s=String(s);for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))%360;return h}
function rnd(seed){var x=seed%2147483647||7;return function(){x=x*16807%2147483647;return(x-1)/2147483646}}
function sprite(c,name,x,y,p,col){var m=SPR[name]||SPR.blob;for(var r=0;r<m.length;r++)for(var q=0;q<m[r].length;q++){var ch=m[r][q];if(ch==='.')continue;
 c.fillStyle=ch==='X'?col:ch==='W'?'#fff':'#0a0a0a';c.fillRect(x+q*p,y+r*p,p+.05,p+.05)}}
function logoK(c,k,x,y,s,th){c.save();
 if(k==='pill'||k==='pill2'){c.translate(x+s/2,y+s/2);c.rotate(-Math.PI/4);var w=s*.86,h=s*.38;RR(c,-w/2,-h/2,w,h,h/2);c.fillStyle='#fff';c.fill();
  c.save();RR(c,-w/2,-h/2,w,h,h/2);c.clip();R(c,0,-h/2,w/2,h,th);c.restore();c.lineWidth=Math.max(1,s/14);c.strokeStyle='#061006';RR(c,-w/2,-h/2,w,h,h/2);c.stroke()}
 else if(k==='alpaca'){RR(c,x,y,s,s,s*.22);c.fillStyle='#f5c518';c.fill();T(c,'A',x+s/2,y+s*.76,s*.66,'#000','center','900')}
 else if(k==='btc'){c.beginPath();c.arc(x+s/2,y+s/2,s/2,0,7);c.fillStyle='#f7931a';c.fill();T(c,'\u20bf',x+s/2,y+s*.74,s*.62,'#fff','center','900')}
 else{RR(c,x,y,s,s,s*.22);c.fillStyle='#1d4ed8';c.fill();var bw=s*.12;[.55,.3,.45,.2].forEach(function(t,i){R(c,x+s*(.17+i*.18),y+s*t,bw,s*(.82-t),'#fff')})}
 c.restore()}
function plant(c,x,y,s){R(c,x-7*s,y+10*s,14*s,12*s,'#16181b');R(c,x-8*s,y+9*s,16*s,3*s,'#222529');
 var L=[[-9,-4,'#1c7a35'],[8,-6,'#1c7a35'],[-4,-12,'#27a447'],[5,-14,'#27a447'],[0,-18,'#33c157'],[-10,-10,'#1f8c3c'],[10,-12,'#1f8c3c']];
 L.forEach(function(l){c.beginPath();c.ellipse(x+l[0]*s,y+l[1]*s+6*s,5*s,9*s,l[0]*.08,0,7);c.fillStyle=l[2];c.fill()})}
function banner(c,x,y,th,k){R(c,x+14,y-6,2,6,'#2a2e33');R(c,x-2,y-2,36,3,'#2a2e33');c.beginPath();c.moveTo(x,y);c.lineTo(x+32,y);c.lineTo(x+32,y+72);c.lineTo(x+16,y+62);c.lineTo(x,y+72);c.closePath();
 c.fillStyle=A(th,.16);c.fill();c.strokeStyle=A(th,.75);c.lineWidth=1.5;c.stroke();logoK(c,k,x+5,y+18,22,th)}
function candles(c,cs,x,y,w,h,th,live,flat){if(!cs||cs.length<2){T(c,flat?'FLAT \u00b7 no position':'waiting for candles',x+w/2,y+h/2+3,flat?11:8,flat?A(th,.6):'#3a3f44','center','800');if(flat)T(c,'all cash \u00b7 rules decide the next buy',x+w/2,y+h/2+16,6,'#4a5056','center');return}
 var lo=1e99,hi=-1e99;cs.forEach(function(b){lo=Math.min(lo,b[2]);hi=Math.max(hi,b[1])});var r=(hi-lo)||hi*.01||1,n=cs.length,cw=w/n;
 c.strokeStyle='rgba(255,255,255,.04)';c.lineWidth=1;for(var i=1;i<4;i++){c.beginPath();c.moveTo(x,y+h*i/4+.5);c.lineTo(x+w,y+h*i/4+.5);c.stroke()}
 cs.forEach(function(b,i){var o=b[0],hh=b[1],l=b[2],cl=b[3],col=cl>=o?'#22e33a':'#ff4d2e',cx=x+i*cw+cw/2,Y=function(v){return y+h*(1-(v-lo)/r)};
  R(c,cx-.5,Y(hh),1,Math.max(1,Y(l)-Y(hh)),col);var y1=Math.min(Y(o),Y(cl)),y2=Math.max(Y(o),Y(cl));R(c,cx-cw*.32,y1,Math.max(1,cw*.64),Math.max(1,y2-y1),col)});
 var lc=cs[n-1][3],ly=y+h*(1-(lc-lo)/r);c.setLineDash([3,3]);c.strokeStyle=A(th,.5);c.beginPath();c.moveTo(x,ly);c.lineTo(x+w,ly);c.stroke();c.setLineDash([])}
function mini(c,kind,s,x,y,w,h,th,seed){R(c,x,y,w,h,'#030506');var rr=rnd(seed);
 if(kind===0&&s&&s.length>1){var lo=Math.min.apply(null,s),hi=Math.max.apply(null,s),r=(hi-lo)||1,up=s[s.length-1]>=s[0],col=up?'#22e33a':'#ff4d2e';
  c.beginPath();s.forEach(function(v,i){var px=x+2+i*(w-4)/(s.length-1),py=y+h-3-(v-lo)/r*(h-8);i?c.lineTo(px,py):c.moveTo(px,py)});c.strokeStyle=col;c.lineWidth=1.2;c.stroke();
  c.lineTo(x+w-2,y+h-2);c.lineTo(x+2,y+h-2);c.closePath();c.fillStyle=A(col,.16);c.fill()}
 else if(kind===1){for(var i=0;i<9;i++){var bh=4+rr()*(h-9);R(c,x+3+i*(w-6)/9,y+h-2-bh,(w-6)/9-1.5,bh,rr()>.35?A(th,.9):'#ff4d2e')}}
 else{for(var gy=0;gy<4;gy++)for(var gx=0;gx<8;gx++){var v=rr();R(c,x+3+gx*(w-6)/8,y+3+gy*(h-6)/4,(w-6)/8-1,(h-6)/4-1,v>.7?A(th,.85):v>.4?A(th,.35):'#0d1a3a')}}
 T(c,kind===0?'PNL':kind===1?'FLOW':'HEAT',x+3,y+7,5,'#59616a')}
function desk(c,x,y,th,i,d){R(c,x+18,y-2,56,32,'#0c0f11');SR(c,x+18,y-2,56,32,'#262b30',1.5);
 var s=(d.mon||[])[i%Math.max(1,(d.mon||[]).length)];mini(c,s&&s.length>1&&i%3!==1?0:(i%3===1?1:2),s,x+21,y+1,50,26,th,hue(d.label)+i*97);
 R(c,x+43,y+30,6,4,'#1a1d21');R(c,x,y+34,92,12,'#14171a');R(c,x,y+34,92,1.5,A(th,.35));R(c,x+3,y+46,4,12,'#0f1113');R(c,x+85,y+46,4,12,'#0f1113');
 R(c,x+28,y+37,26,3,'#262a2f');R(c,x+58,y+37,6,4,'#262a2f');R(c,x+34,y+55,24,6,'#16181c');R(c,x+44,y+61,4,6,'#111315');R(c,x+38,y+66,16,2,'#111315')}
function drawStatic(c,d){var th=d.theme,i;
 R(c,0,0,W,H,'#040506');var g=c.createLinearGradient(0,0,0,160);g.addColorStop(0,'#06080a');g.addColorStop(1,'#0b0e11');R(c,0,0,W,158,g);
 for(i=0;i<W;i+=48)R(c,i,0,1,156,'#0e1114');R(c,0,155,W,3,A(th,.22));
 c.save();c.beginPath();c.rect(0,158,W,H-158);c.clip();c.strokeStyle='rgba(255,255,255,.03)';c.lineWidth=1;c.beginPath();
 for(i=-800;i<W+800;i+=42){c.moveTo(i,158);c.lineTo(i+(H-158)*1.7,H);c.moveTo(i,158);c.lineTo(i-(H-158)*1.7,H)}c.stroke();c.restore();
 var fg=c.createRadialGradient(W/2,300,20,W/2,300,380);fg.addColorStop(0,A(th,.06));fg.addColorStop(1,'rgba(0,0,0,0)');R(c,0,150,W,H-150,fg);
 c.beginPath();c.moveTo(0,40);c.lineTo(62,70);c.lineTo(62,330);c.lineTo(0,372);c.closePath();c.fillStyle='#07090b';c.fill();c.strokeStyle=A(th,.18);c.stroke();
 c.beginPath();c.moveTo(8,96);c.lineTo(54,114);c.lineTo(54,214);c.lineTo(8,204);c.closePath();c.fillStyle='#030405';c.fill();c.strokeStyle='#22272c';c.lineWidth=1.5;c.stroke();
 var rr=rnd(hue(d.label)+5);for(i=0;i<9;i++){var bx=12+i*4.6,sk=(bx-8)*.39,top=104+sk+rr()*40,len=8+rr()*40;R(c,bx,top,3,Math.min(len,200+sk-top),rr()>.45?'#22e33a':'#ff4d2e')}
 RR(c,74,14,62,56,9);c.fillStyle='#0d1012';c.fill();c.strokeStyle=A(th,.45);c.lineWidth=1.5;c.stroke();logoK(c,d.logo,88,20,34,th);
 T(c,d.venue,105,84,9,'#e9e9e9','center','800');T(c,d.title,105,94,5.5,'#7d858c','center');
 banner(c,146,24,th,d.logo);banner(c,524,24,th,d.logo);
 c.save();c.shadowColor=th;c.shadowBlur=16;RR(c,186,16,320,134,6);c.fillStyle='#0a0c0e';c.fill();c.restore();RR(c,186,16,320,134,6);c.strokeStyle=A(th,.6);c.lineWidth=2;c.stroke();
 R(c,192,22,308,122,'#020303');
 var pc=(d.pct>=0?'+':'')+d.pct.toFixed(1)+'%',hd=[['TICKER',d.ticker],['P&L',pc],['OPEN',String(d.n_open)],['DAY',String(d.day)],['DESK',d.label]];
 hd.forEach(function(h,k){var hx=196+k*60;R(c,hx,25,56,15,'#0a0d0f');T(c,h[0],hx+3,31,4.6,'#5d666e');T(c,h[1].slice(0,10),hx+3,38,6.2,k===1?(d.pct>=0?'#22e33a':'#ff4d2e'):'#e8e8e8','left','800')});
 candles(c,d.candles,198,46,296,90,th,false,d.note==='flat');
 T(c,d.label+' DESK \u00b7 '+d.ticker+' '+pc+(d.note==='open'?' TONIGHT':' \u00b7 '+d.note.toUpperCase()),346,161,6.4,A(th,.95),'center','800');
 (d.coins||[]).slice(0,6).forEach(function(cn,k){var cx=556+k*27,cy=32;c.beginPath();c.arc(cx,cy,11,0,7);c.fillStyle='hsl('+hue(cn)+',70%,38%)';c.fill();c.strokeStyle='#e8e8e8';c.lineWidth=1.5;c.stroke();
  T(c,cn.replace(/[^A-Za-z0-9]/g,'').slice(0,3).toUpperCase(),cx,cy+2.4,6.2,'#fff','center','900')});
 RR(c,566,62,56,24,3);c.fillStyle='#050607';c.fill();c.strokeStyle='#2a2f34';c.lineWidth=1;c.stroke();R(c,570,90,48,10,'#101316');T(c,'LOCAL TIME',594,97.5,5.4,'#b8c0c8','center','800');
 R(c,628,58,88,80,'#07090a');SR(c,628,58,88,80,'#262b30',1);T(c,'DAY '+d.day+' \u00b7 '+(d.rules||[]).length+' RULES',633,67,5.4,'#e6e6e6','left','800');
 c.save();c.beginPath();c.rect(629,59,86,78);c.clip();(d.rules||[]).forEach(function(r,k){T(c,(k+1)+' '+r.slice(0,25),633,78+k*9.6,4.1,k%2?'#8fd99a':A(th,.95))});c.restore();
 R(c,550,160,108,12,'#14171a');R(c,550,160,108,1.5,A(th,.4));R(c,553,172,4,12,'#0f1113');R(c,651,172,4,12,'#0f1113');R(c,600,138,30,20,'#0c0f11');SR(c,600,138,30,20,'#262b30',1);
 mini(c,1,null,602,140,26,16,th,hue(d.label)+3);R(c,636,154,14,6,'#2a2e33');R(c,560,155,16,5,'#d8d8d8');R(c,562,153,12,2,'#bdbdbd');
 R(c,566,188,76,10,'#101316');T(c,'HEAD OF THE FLOOR',604,195.5,5.4,'#b8c0c8','center','800');
 plant(c,166,132,1.0);plant(c,690,118,1.05);plant(c,262,338,.95);plant(c,444,338,.95);plant(c,156,330,.8);
 for(i=0;i<6;i++)desk(c,SLOTS[i][0],SLOTS[i][1],th,i,d);
 R(c,32,176,54,34,'#0e1113');SR(c,32,176,54,34,'#23282d',1);R(c,32,176,54,2,A(th,.3));logoK(c,d.logo,51,186,16,th);
 ['#f5c518','#a78bfa','#2dd4bf','#ff5a1f'].forEach(function(cl,k){sprite(c,k===2?'ghost':'blob',36+k*12,166,1,cl)});
 R(c,14,296,48,50,'#0d1012');SR(c,14,296,48,50,'#262b30',1);c.beginPath();for(i=0;i<16;i++){var a=i/16*6.283,rr2=i%2?9:14;c.lineTo(38+Math.cos(a)*rr2*1.3,312+Math.sin(a)*rr2*.8)}c.closePath();c.fillStyle='#f2f2f2';c.fill();
 T(c,'PAPER',38,314.5,6.4,'#000','center','900');R(c,18,334,40,8,'#16191c');T(c,'PAPER ONLY',38,340.2,4.8,'#c9d0d6','center','800');
 R(c,584,240,44,22,'#101316');SR(c,584,240,44,22,'#262b30',1);R(c,580,262,52,10,'#16191c');T(c,'TOP RUNNER',606,269,5.2,'#e6e6e6','center','800');
 c.beginPath();c.ellipse(604,320,26,9,0,0,7);c.fillStyle='#0c0f12';c.fill();R(c,572,330,66,20,'#101316');SR(c,572,330,66,20,'#262b30',1);R(c,574,350,62,10,'#16191c');T(c,'WHALE RADAR',605,357.2,5.2,'#e6e6e6','center','800');
 R(c,601,306,5,24,'#3a4046');
 R(c,664,196,44,136,'#0b0d10');SR(c,664,196,44,136,'#2a2f35',1.5);for(i=0;i<9;i++){R(c,668,206+i*13,36,10,'#101418');SR(c,668,206+i*13,36,10,'#1c2126',1)}
 logoK(c,d.logo,679,200-14,12,th);T(c,d.venue,686,342,5.6,'#c9d0d6','center','800');
 c.beginPath();c.moveTo(282,328);c.lineTo(414,328);c.lineTo(420,358);c.lineTo(276,358);c.closePath();c.fillStyle='#14161a';c.fill();R(c,278,322,140,10,'#1a1d22');
 R(c,272,326,10,32,'#191c20');R(c,414,326,10,32,'#191c20');for(i=1;i<3;i++)R(c,282+i*44,334,1.5,18,'#0c0e10');
 R(c,300,364,96,18,'#121519');R(c,300,364,96,1.5,A(th,.4));R(c,304,382,4,8,'#0e1012');R(c,388,382,4,8,'#0e1012');logoK(c,d.logo,340,366,13,th);plant(c,318,356,.45)}
function bubble(c,txt,x,y,a){c.save();c.globalAlpha=a;c.font='700 7px ui-monospace,"SF Mono",Menlo,monospace';var w=Math.min(190,c.measureText(txt).width+10),bx=Math.max(4,Math.min(W-w-4,x-w/2)),by=y-16;
 R(c,bx,by,w,13,'#050607');SR(c,bx,by,w,13,'#d9d9d9',1);R(c,x-2,by+13,4,3,'#d9d9d9');T(c,txt.length>40?txt.slice(0,39)+'\u2026':txt,bx+5,by+9.2,7,'#f0f0f0');c.restore()}
function drawDyn(c,d,t,v){var th=d.theme,i;
 c.save();c.beginPath();c.rect(190,3,316,11);c.clip();var tape=(d.tape||'')+'   \u00b7   ';c.font='700 7px ui-monospace,Menlo,monospace';var tw=c.measureText(tape).width||300,off=(t*26)%tw;
 for(i=-1;i<3;i++)T(c,tape,190-off+i*tw,11.5,7,th);c.restore();
 var cs=d.candles||[];if(cs.length>1){var lo=1e99,hi=-1e99;cs.forEach(function(b){lo=Math.min(lo,b[2]);hi=Math.max(hi,b[1])});var r=(hi-lo)||1,lb=cs[cs.length-1],cw=296/cs.length,
  cx=198+(cs.length-.5)*cw,ly=46+90*(1-(lb[3]-lo)/r);c.save();c.globalAlpha=.5+.5*Math.sin(t*4);c.beginPath();c.arc(cx,ly,3,0,7);c.fillStyle=lb[3]>=lb[0]?'#22e33a':'#ff4d2e';c.shadowColor=c.fillStyle;c.shadowBlur=8;c.fill();c.restore()}
 for(i=0;i<6;i++){var s=SLOTS[i];R(c,s[0]+21,s[1]+1+((t*14+i*7)%26),50,1,A(th,.22))}
 var bots=d.bots||[],pos=[];bots.slice(0,6).forEach(function(b,k){var cfg=BOT[b.n]||['#9ca3af','blob'],s=SLOTS[k],bob=Math.sin(t*2.3+k*1.7)*1.8,bx=s[0]+(k%2?62:4),by=s[1]+38+bob;
  c.save();c.globalAlpha=.35;R(c,bx+3,s[1]+62,20,2,'#000');c.restore();sprite(c,cfg[1],bx,by,2.6,cfg[0]);T(c,b.n,bx+13,by-3,5.6,cfg[0],'center','900');pos.push([bx+13,by-6,b])});
 var hb=Math.sin(t*1.8)*1.5;sprite(c,'ghost',590,124+hb,2.8,'#f2f2f2');c.strokeStyle='#2b2f33';c.lineWidth=2.2;c.beginPath();c.arc(604,134+hb,15,Math.PI*1.08,Math.PI*1.92);c.stroke();
 R(c,587,131+hb,4,8,'#2b2f33');R(c,617,131+hb,4,8,'#2b2f33');T(c,'CHIEF',604,121+hb,5.6,'#f2f2f2','center','900');
 var chief=bots.filter(function(b){return b.n==='CHIEF'})[0];pos.push([604,118+hb,chief||{n:'CHIEF',say:''}]);
 var speak=pos.filter(function(p){return p[2]&&p[2].say});if(speak.length){var ph=t/3.4,k2=Math.floor(ph)%speak.length,fr=ph-Math.floor(ph),al=fr<.12?fr/.12:fr>.88?(1-fr)/.12:1;
  bubble(c,speak[k2][2].say,speak[k2][0],speak[k2][1],al);if(speak.length>3){var k3=(k2+2)%speak.length;bubble(c,speak[k3][2].say,speak[k3][0],speak[k3][1],al*.85)}}
 var ry=Math.sin(t*1.6)*1.5;c.beginPath();c.moveTo(606,196+ry);c.quadraticCurveTo(616,212+ry,612,232+ry);c.lineTo(600,232+ry);c.quadraticCurveTo(596,212+ry,606,196+ry);c.fillStyle='#e9edf1';c.fill();
 c.beginPath();c.arc(606,212+ry,3,0,7);c.fillStyle=th;c.fill();R(c,595,226+ry,4,8,'#b9c0c6');R(c,613,226+ry,4,8,'#b9c0c6');
 var fl=6+Math.random()*5;c.beginPath();c.moveTo(601,233+ry);c.lineTo(606,233+ry+fl);c.lineTo(611,233+ry);c.fillStyle=Math.random()>.5?'#ff9f1a':'#ffd23f';c.fill();
 T(c,d.top||'',606,256,5.6,d.top&&d.top.indexOf('-')>0?'#ff4d2e':th,'center','800');
 c.save();c.translate(604,300);c.rotate(-.5);c.beginPath();c.ellipse(0,0,17,10,0,0,7);c.fillStyle='#c9d0d6';c.fill();c.beginPath();c.ellipse(1,-1,13,7,0,0,7);c.fillStyle='#8d969e';c.fill();R(c,-1,-14,2,12,'#c9d0d6');c.restore();
 for(i=0;i<3;i++){var rr3=((t*16+i*9)%27)+4;c.beginPath();c.arc(618,284,rr3,-1.2,.1);c.strokeStyle=A(th,Math.max(0,.8-rr3/31));c.lineWidth=1.6;c.stroke()}
 T(c,d.radar||'',605,345,5,'#9aa3ab','center','700');
 for(i=0;i<9;i++)for(var j=0;j<4;j++){var on=Math.sin(t*(2+j*.7)+i*1.9+j*3.1)>.1;R(c,672+j*5,209+i*13,3,3,on?(j===3&&i%3===0?'#ff4d2e':th):'#1a2a1d')}
 var Z=new Date(),hm='';try{hm=Z.toLocaleTimeString('de-DE',{timeZone:'Europe/Berlin',hour:'2-digit',minute:'2-digit'})}catch(e){hm=('0'+Z.getHours()).slice(-2)+':'+('0'+Z.getMinutes()).slice(-2)}
 T(c,hm,594,79,12,'#22e33a','center','800');
 v.fl=v.fl||[];if(!v.nf||t>v.nf){v.nf=t+2.1+Math.random()*1.4;var fls=d.floats&&d.floats.length?d.floats:[d.pct];var val=fls[(v.fc=(v.fc||0)+1)%fls.length];
  var anchor=pos.length?pos[Math.floor(Math.random()*Math.min(6,pos.length))]:[346,90];v.fl.push({x:anchor[0]+(Math.random()*20-10),y:anchor[1]-8,v:val,t0:t})}
 v.fl=v.fl.filter(function(f){return t-f.t0<2.2});v.fl.forEach(function(f){var p=(t-f.t0)/2.2;c.save();c.globalAlpha=p<.15?p/.15:1-p;var col=f.v>=0?'#22e33a':'#ff4d2e';c.shadowColor=col;c.shadowBlur=6;
  T(c,(f.v>=0?'+':'')+Number(f.v).toFixed(1)+'%',f.x,f.y-p*28,9,col,'center','900');c.restore()})}
var views=[],last=0,running=false;
function size(v){var r=v.cv.getBoundingClientRect(),w=Math.round(r.width*DPR),h=Math.round(r.height*DPR);if(!w||!h)return false;
 if(v.cv.width!==w||v.cv.height!==h||!v.st||v.dirty){v.cv.width=w;v.cv.height=h;v.k=w/W;v.ky=h/H;var st=v.st||document.createElement('canvas');st.width=w;st.height=h;var sc=st.getContext('2d');
  sc.setTransform(v.k,0,0,v.ky,0,0);try{drawStatic(sc,v.d)}catch(e){if(window.console)console.warn('floor static',e)}v.st=st;v.dirty=false}return true}
function vis(el){var r=el.getBoundingClientRect();return r.width>0&&r.bottom>0&&r.top<(window.innerHeight||800)}
function frame(now){requestAnimationFrame(frame);if(document.hidden)return;var single=views.some(function(v){return v.single&&vis(v.cv)});if(now-last<(single?42:70))return;last=now;var t=now/1000;
 views.forEach(function(v){if(!v.d||!vis(v.cv)||!size(v))return;var c=v.cv.getContext('2d');c.setTransform(1,0,0,1,0,0);c.drawImage(v.st,0,0);c.setTransform(v.k,0,0,v.ky,0,0);
  try{drawDyn(c,v.d,t,v)}catch(e){if(!v.err){v.err=1;if(window.console)console.warn('floor dyn',e)}}})}
window.DeskFloor={set:function(list){views=list;views.forEach(function(v){v.dirty=true});if(!running){running=true;requestAnimationFrame(frame)}},
 update:function(desks){views.forEach(function(v){if(desks[v.idx]){v.d=desks[v.idx];v.dirty=true}})},views:function(){return views}};
})();"""

# ======================================================================= JS: header clock, floor views, balance chart, analysis, holdings
SV_LIVE_JS = r"""(function(){
// SAVIP live: poll v.json every 10 s and fetch data.json (revalidating, cache:'no-cache') only when its generated_ts changed;
// a cache-busted fetch only when the data looks stuck. Paused while the tab is hidden; failures keep the last data.
var D=JSON.parse(document.getElementById('embedded').textContent),last=D.generated_ts,busy=false,st=window.deskLive={lastOk:Date.now(),fail:0,gen:last};
var ind=document.getElementById('live'),txt=document.getElementById('live-t');
function ago(){if(!txt)return;var s=Math.max(0,Math.round(Date.now()/1000-last)),a=s<90?s+'s':s<5400?Math.round(s/60)+'m':Math.round(s/3600)+'h',off=st.fail>=2&&Date.now()-st.lastOk>45000;
 txt.textContent=(off?'offline \u00b7 ':'')+'aktualisiert vor '+a;if(ind)ind.className='live'+(s>240||off?' stale':'')}
function apply(d){var f=d.fragments||{};if(window.deskPre)try{window.deskPre()}catch(e){}
 Object.keys(f).forEach(function(k){var el=document.getElementById('f-'+k);if(!el||el.innerHTML===f[k])return;
  var open={},sc={};el.querySelectorAll('details').forEach(function(x,i){open[i]=x.open});el.querySelectorAll('.log,.tscroll').forEach(function(x,i){sc[i]=[x.scrollTop,x.scrollLeft]});
  if(k==='open'&&window.deskSwap)try{if(window.deskSwap(el,f[k]))return}catch(e){}
  var ex=[].map.call(el.querySelectorAll('.tc.open[data-ck]'),function(x){return x.dataset.ck});
  el.innerHTML=f[k];
  el.querySelectorAll('details').forEach(function(x,i){if(i in open)x.open=open[i]});el.querySelectorAll('.log,.tscroll').forEach(function(x,i){if(sc[i]){x.scrollTop=sc[i][0];x.scrollLeft=sc[i][1]}});
  ex.forEach(function(ck){var c=el.querySelector('.tc[data-ck="'+ck+'"]');if(c)c.classList.add('open')})});
 if(window.deskPost)try{window.deskPost(null,d)}catch(e){}
 last=d.generated_ts;st.gen=last;ago();if(window.deskUiCheck)window.deskUiCheck(d)}
// v.json (~80 bytes, uploaded in the same publish as data.json) is polled every 10 s; data.json (~65 KB compressed) only when it changed
var noV=false,lastV=0;function vpoll(){if(busy||document.hidden)return;if(noV){if(Date.now()-lastV>=30000){lastV=Date.now();poll()}return}
 fetch('v.json',{cache:'no-cache',credentials:'same-origin'}).then(function(r){if(r.status===404){noV=true;throw new Error('no v.json')}if(!r.ok)throw new Error('http '+r.status);return r.json()})
 .then(function(v){st.lastOk=Date.now();st.fail=0;if(v&&v.g&&v.g!==last)poll();else ago()}).catch(function(){if(!noV){st.fail++;ago()}})}
function poll(bust){if(busy||document.hidden)return;busy=true;var u='data.json'+(bust?'?_='+Date.now():'');
 fetch(u,{cache:bust?'no-store':'no-cache',credentials:'same-origin'}).then(function(r){if(!r.ok)throw new Error('http '+r.status);return r.json()})
 .then(function(d){busy=false;st.lastOk=Date.now();st.fail=0;if(d.generated_ts!==last)apply(d);else if(!bust&&Date.now()/1000-last>200)poll(true);ago()})
 .catch(function(){busy=false;st.fail++;ago()})}
var T=null;function start(){clearInterval(T);vpoll();T=setInterval(vpoll,10000)}
setTimeout(function(){document.body.classList.add('noanim')},2500);
ago();setInterval(function(){if(!document.hidden)ago()},1000);start();
document.addEventListener('visibilitychange',function(){if(document.hidden){clearInterval(T);T=null}else start()});
window.addEventListener('online',function(){poll(true)});
})();"""
# reload only when the page code (CSS/JS/scene) changed on the server; at most once per 15 min, never mid-interaction
SV_RELOAD_JS = r"""(function(){var m=document.querySelector('meta[name="desk-ui"]'),mine=m?m.content:'',K='desk_ui_reload';
window.deskUiCheck=function(d){var v=d&&d.savip&&d.savip.live&&d.savip.live.ui_v;if(!v||!mine||v===mine)return;var lastR=+(sessionStorage.getItem(K)||0);
 if(Date.now()-lastR<900000)return;if(Date.now()-(window.__deskTouch||0)<30000)return;if(window.deskFloorBusy&&window.deskFloorBusy()===1)return;if(window.deskChartOpen&&window.deskChartOpen())return;
 try{sessionStorage.setItem(K,String(Date.now()))}catch(e){}location.reload()};
['pointerdown','keydown','wheel','touchstart'].forEach(function(ev){document.addEventListener(ev,function(){window.__deskTouch=Date.now()},{passive:true})});
// safety net: very long-open tabs reload once every 6 h when idle
setInterval(function(){if(!document.hidden&&performance.now()>21600000&&Date.now()-(window.__deskTouch||0)>120000)location.reload()},60000)})();"""

UI_JS = r"""(function(){
var D=null;try{D=JSON.parse(document.getElementById('embedded').textContent)}catch(e){}
var SV=(D&&D.savip)||{desks:[]},K='sv_ui_v1',st={view:-1,mon:'',s:'meme',r:'live',all:0};try{var o=JSON.parse(sessionStorage.getItem(K)||'{}');for(var k in o)st[k]=o[k]}catch(e){}
function save(){try{sessionStorage.setItem(K,JSON.stringify(st))}catch(e){}}
function $(i){return document.getElementById(i)}
function hue(s){var h=0;s=String(s);for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))%360;return h}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function lg(t,u){var ini=String(t).replace(/[^A-Za-z0-9$]/g,'').slice(0,2).toUpperCase()||'?';return'<span class="lg" style="--h:'+hue(t)+'">'+esc(ini)+(u&&/^logos\/[A-Za-z0-9_-]+\.webp(\?v=[0-9a-f]+)?$/.test(u)?'<img class="lgi" src="'+u+'" alt="" decoding="async" onerror="this.remove()">':'')+'</span>'}
function sp(x,d){return(x>=0?'+':'')+Number(x).toFixed(d==null?2:d)+'%'}
function money(x){return(x<0?'-':'')+'$'+Math.abs(x).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
// clock (Berlin, MEZ / CEST)
function clock(){var z=new Date(),hm,tz='';try{hm=z.toLocaleTimeString('de-DE',{timeZone:'Europe/Berlin',hour:'2-digit',minute:'2-digit'});
 tz=(new Intl.DateTimeFormat('de-DE',{timeZone:'Europe/Berlin',timeZoneName:'short'}).formatToParts(z).filter(function(p){return p.type==='timeZoneName'})[0]||{}).value||''}catch(e){hm=z.toTimeString().slice(0,5)}
 var ck=$('clk');if(ck.dataset.hm!==hm){var fst=!ck.dataset.hm;ck.dataset.hm=hm;ck.innerHTML=esc(hm).replace(':','<span class="ccol">:</span>');if(!fst){ck.classList.remove('roll');void ck.offsetWidth;ck.classList.add('roll')}}$('clz').textContent=tz==='MESZ'?'CEST':(tz==='MEZ'?'MEZ':(tz||'MEZ'))}
clock();(function tickc(){if(!document.hidden)clock();setTimeout(tickc,1000-Date.now()%1000+15)})();
// floor: grid (2 big + 3 small) <-> single desk
var grid=$('fl-grid'),one=$('fl-one');
function tiles(){return[].slice.call(grid.querySelectorAll('.dtile'))}
function mount(){var L=[];if(st.view>=0&&SV.desks[st.view])L.push({cv:one.querySelector('canvas'),d:SV.desks[st.view],idx:st.view,single:true});
 else tiles().forEach(function(t){var i=+t.dataset.d;if(SV.desks[i])L.push({cv:t.querySelector('canvas'),d:SV.desks[i],idx:i})});if(window.DeskFloor)DeskFloor.set(L)}
function head(){var d=SV.desks[st.view];if(st.view>=0&&d){var ml=st.mon&&window.DeskFloor&&DeskFloor.label?DeskFloor.label(d,st.mon):'';$('fl-t').textContent=ml?(ml==='main screen'?'Main screen':ml+' monitor'):'Desk floor';$('floor').classList.toggle('mz',!!ml);var nm=$('fl-nm');if(nm)nm.textContent=d.label+' desk \u00b7 '+(st.view+1)+' / '+SV.desks.length;
  $('fl-r').innerHTML='main screen: <span class="msr">'+lg(d.ticker,d.tlogo)+'<b>'+esc(d.ticker)+'</b> <em class="'+(d.pct>=0?'pos':'neg')+'" style="font-style:normal">'+sp(d.pct,1)+'</em></span>'}
 else{$('fl-t').textContent=SV.desks.length+' desks live';var m=SV.desks[SV.main||0];$('fl-r').textContent='pick a desk'}}
function labels(){tiles().forEach(function(t){var d=SV.desks[+t.dataset.d];if(!d)return;var tl=t.querySelector('.tl');
 tl.innerHTML=lg(d.ticker,d.tlogo)+'<b>'+esc(d.ticker)+'</b><em class="'+(d.pct>=0?'pos':'neg')+'">'+sp(d.pct,1)+'</em>'+(d.note!=='open'?'<small>'+esc(d.note)+'</small>':'')})}
// SAVIP v3: tap a desk -> it grows from its tile into the panel; tap a monitor -> it grows into a big chart; Zurueck reverses
var fbd=grid.parentNode,monel=$('fl-mon'),back=$('fl-back'),busy=0,DUR=420,EZ='cubic-bezier(.22,.8,.24,1)';
var RM=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function vS(i){return{cv:one.querySelector('canvas'),d:SV.desks[i],idx:i,single:true}}
function vM(i,k){return{cv:monel.querySelector('canvas'),d:SV.desks[i],idx:i,mon:k,single:true}}
function vG(){return tiles().map(function(t){var i=+t.dataset.d;return{cv:t.querySelector('canvas'),d:SV.desks[i],idx:i}}).filter(function(v){return v.d})}
function setV(L){if(window.DeskFloor){DeskFloor.set(L);if(DeskFloor.now)DeskFloor.now()}}
function rel(r){var B=fbd.getBoundingClientRect();return{x:r.left-B.left,y:r.top-B.top,w:r.width,h:r.height,B:B}}
function tf(R){return'translate('+R.x.toFixed(1)+'px,'+R.y.toFixed(1)+'px) scale('+(R.w/R.B.width).toFixed(4)+','+(R.h/R.B.height).toFixed(4)+')'}
function anim(el,fr,cb){if(RM||!el.animate){cb&&cb();return}var a=el.animate(fr,{duration:DUR,easing:EZ,fill:'both'});a.onfinish=function(){cb&&cb();a.cancel()};a.oncancel=null}
function tileOf(i){return grid.querySelector('.dtile[data-d="'+i+'"]')}
function monRel(k){var r=window.DeskFloor&&DeskFloor.rect&&DeskFloor.rect(k);if(!r)return null;var C=rel(one.querySelector('canvas').getBoundingClientRect()),W=DeskFloor.W||720,H=DeskFloor.H||404;
 return{x:C.x+r.x/W*C.w,y:C.y+r.y/H*C.h,w:r.w/W*C.w,h:r.h/H*C.h,B:C.B}}
function apply(){var sd=st.view>=0&&SV.desks[st.view];if(!sd){st.view=-1;st.mon=''}if(st.mon&&!(window.DeskFloor&&DeskFloor.rect&&DeskFloor.rect(st.mon)))st.mon='';
 grid.hidden=!!sd;one.hidden=!sd||!!st.mon;monel.hidden=!(sd&&st.mon);back.hidden=!sd;head();setV(st.mon?[vM(st.view,st.mon)]:sd?[vS(st.view)]:vG())}
function show(i){st.view=i;st.mon='';save();apply()}
function openDesk(i){var t=tileOf(i);if(busy||!SV.desks[i])return;if(!t||RM){show(i);return}var R=rel(t.getBoundingClientRect());busy=1;st.view=i;st.mon='';save();
 one.hidden=false;back.hidden=false;head();setV([vS(i)].concat(vG()));grid.style.pointerEvents='none';
 anim(grid,[{opacity:1},{opacity:.12}]);anim(one,[{transform:tf(R),borderRadius:'8px'},{transform:'none',borderRadius:'0px'}],function(){grid.hidden=true;grid.style.pointerEvents='';busy=0;setV([vS(i)])})}
function closeDesk(){var i=st.view;if(busy)return;grid.hidden=false;var t=tileOf(i);st.view=-1;st.mon='';save();back.hidden=true;head();if(!t||RM){apply();return}
 var R=rel(t.getBoundingClientRect());busy=1;setV(vG().concat([vS(i)]));
 anim(grid,[{opacity:.12},{opacity:1}]);anim(one,[{transform:'none',borderRadius:'0px'},{transform:tf(R),borderRadius:'8px'}],function(){one.hidden=true;busy=0;setV(vG())})}
function openMon(k){if(busy||st.view<0)return;var R=monRel(k);if(!R)return;var i=st.view;busy=1;st.mon=k;save();monel.hidden=false;head();setV([vM(i,k),vS(i)]);
 if(window.DeskFloor&&DeskFloor.hover)DeskFloor.hover(null);
 if(RM){one.hidden=true;busy=0;setV([vM(i,k)]);return}
 anim(monel,[{transform:tf(R),opacity:.35,borderRadius:'6px'},{transform:'none',opacity:1,borderRadius:'0px'}],function(){one.hidden=true;busy=0;setV([vM(i,k)])})}
function closeMon(){if(busy)return;var k=st.mon,i=st.view;one.hidden=false;st.mon='';save();head();var R=monRel(k);if(!R||RM){apply();return}busy=1;setV([vS(i),vM(i,k)]);
 anim(monel,[{transform:'none',opacity:1,borderRadius:'0px'},{transform:tf(R),opacity:.2,borderRadius:'6px'}],function(){monel.hidden=true;busy=0;setV([vS(i)])})}
function goBack(){if(st.mon)closeMon();else if(st.view>=0)closeDesk()}
function swipe(dir){if(busy||st.view<0||st.mon)return;var n=SV.desks.length;st.view=((st.view+dir)%n+n)%n;save();apply();if(one.animate&&!RM)one.animate([{opacity:.25,transform:'translateX('+(dir*24)+'px)'},{opacity:1,transform:'none'}],{duration:260,easing:EZ})}
// fast taps: act on pointerup (no 300 ms click delay), swallow the synthetic click; keyboard/AT still use click
function tap(el,fn,sw){var s0=null,sup=0;
 el.addEventListener('pointerdown',function(e){if(e.button>0)return;s0={x:e.clientX,y:e.clientY,t:Date.now(),el:e.target.closest('.dtile,.fback')};if(s0.el)s0.el.classList.add('press')},{passive:true});
 function clr(){if(s0&&s0.el)s0.el.classList.remove('press')}
 el.addEventListener('pointercancel',function(){clr();s0=null});
 el.addEventListener('pointerup',function(e){if(!s0)return;clr();var dx=e.clientX-s0.x,dy=e.clientY-s0.y,dt=Date.now()-s0.t;s0=null;
  if(sw&&Math.abs(dx)>50&&Math.abs(dy)<40&&dt<800){sup=Date.now();sw(dx<0?1:-1);return}
  if(Math.abs(dx)<10&&Math.abs(dy)<10&&dt<800){sup=Date.now();fn(e)}});
 el.addEventListener('click',function(e){if(Date.now()-sup<700)return;fn(e)})}
tap(grid,function(e){var t=e.target.closest('.dtile');if(t)openDesk(+t.dataset.d)});
grid.addEventListener('keydown',function(e){var t=e.target.closest('.dtile');if(t&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openDesk(+t.dataset.d)}});
tap(back,function(){goBack()});
tap(one,function(e){var k=window.DeskFloor&&DeskFloor.hit&&DeskFloor.hit(e.clientX,e.clientY);if(k)openMon(k)},swipe);
tap(monel,function(){},null);
one.addEventListener('pointermove',function(e){if(e.pointerType!=='mouse'||!window.DeskFloor||!DeskFloor.hit)return;var k=DeskFloor.hit(e.clientX,e.clientY);DeskFloor.hover(k);one.style.cursor=k?'pointer':'default'});
one.addEventListener('pointerleave',function(){if(window.DeskFloor&&DeskFloor.hover)DeskFloor.hover(null)});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&st.view>=0)goBack()});
window.addEventListener('resize',function(){if(window.DeskFloor)DeskFloor.views().forEach(function(v){v.dirty=true})});
window.deskFloorBusy=function(){return busy||st.mon};
labels();apply();
// balance (meme bank equity from history.csv / Alpaca paper portfolio history), LIVE = today since 00:00 Berlin
var cv=$('balc'),first=true,hov=null;
function series(){var e=(D&&D.equity)||{},s=e[st.s]||{pts:[],start:0},pts=s.pts||[],now=e.now||(pts.length?pts[pts.length-1][0]:0);
 var t0=st.r==='live'?(e.today0||now-86400):st.r==='1h'?now-3600:st.r==='1d'?now-86400:now-7*86400;
 var p=pts.filter(function(x){return x[0]>=t0}),pre=pts.filter(function(x){return x[0]<t0});if(pre.length)p.unshift([t0,pre[pre.length-1][1]]);
 if(!p.length&&pts.length)p=[pts[pts.length-1]];if(p.length===1)p=[[t0,p[0][1]],[now,p[0][1]]];return{p:p,t0:t0,now:now,start:s.start,cur:pts.length?pts[pts.length-1][1]:s.start}}
function drawBal(){var S=series(),p=S.p;if(!cv||!p.length)return;var r=cv.getBoundingClientRect(),dpr=Math.min(2,window.devicePixelRatio||1),w=Math.round(r.width*dpr),h=Math.round(r.height*dpr);if(!w||!h)return;
 cv.width=w;cv.height=h;var c=cv.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);var W=r.width,H=r.height;c.clearRect(0,0,W,H);
 var cur=S.cur,f0=p.length?p[0][1]:cur,dR=cur-f0,col=dR>=-1e-9?'#22e33a':'#ff4d2e';
 var lab={live:'today',"1h":'last hour',"1d":'last 24h',"1w":'last 7 days'}[st.r];
 $('bdl').innerHTML='<span class="'+(dR>=0?'pos':'neg')+'">'+(dR>=0?'\u25b2 ':'\u25bc ')+money(Math.abs(dR))+' ('+sp(f0?dR/f0*100:0)+')</span> <span>'+lab+'</span>';
 var A=SV.alp||{},meme=((D&&D.equity)||{}).meme||{},mp=meme.pts||[],mc=mp.length?mp[mp.length-1][1]:meme.start;
 $('b2').innerHTML=st.s==='meme'?(A.equity!=null?'Alpaca paper <b>'+money(A.equity)+'</b> \u00b7 <span class="'+(A.equity-A.last_equity>=0?'pos':'neg')+'">'+sp(A.last_equity?(A.equity/A.last_equity-1)*100:0)+'</span> vs prev. close \u00b7 tap to switch':'Alpaca paper unreachable')
  :('Meme bank <b>'+money(mc||0)+'</b> \u00b7 <span class="'+(mc-meme.start>=0?'pos':'neg')+'">'+sp(meme.start?(mc/meme.start-1)*100:0)+'</span> '+((D&&D.bank&&D.bank.start_eur)?'since reset ('+D.bank.start_eur+' \u20ac'+(D.bank.sol_eur_start?' = 1 SOL':'')+', '+D.bank.started_label+')':'since start')+' \u00b7 tap to switch');
 $('bt').textContent='Desk balance \u00b7 '+(st.s==='meme'?SV.desks.length+' desks':'Alpaca paper');
 if(first){first=false;var t1=Date.now();(function an(){var k=Math.min(1,(Date.now()-t1)/900),e=1-Math.pow(1-k,3);$('bv').textContent=money(cur*e);if(k<1)requestAnimationFrame(an)})()}else tw($('bv'),cur,money);
 var lo=1e99,hi=-1e99;p.forEach(function(x){lo=Math.min(lo,x[1]);hi=Math.max(hi,x[1])});var pad=(hi-lo)*.15||Math.max(.01,Math.abs(hi)*.004);lo-=pad;hi+=pad;
 var t0=p[0][0],t1=Math.max(p[p.length-1][0],t0+1),X=function(t){return 4+(W-14)*(t-t0)/(t1-t0)},Y=function(v){return 10+(H-18)*(1-(v-lo)/(hi-lo))};
 c.beginPath();p.forEach(function(x,i){var px=X(x[0]),py=Y(x[1]);if(!i)c.moveTo(px,py);else{var q=p[i-1],qx=X(q[0]),qy=Y(q[1]);c.quadraticCurveTo(qx,qy,(qx+px)/2,(qy+py)/2);if(i===p.length-1)c.lineTo(px,py)}});
 var g=c.createLinearGradient(0,0,0,H);g.addColorStop(0,col==='#22e33a'?'rgba(34,227,58,.22)':'rgba(255,77,46,.2)');g.addColorStop(1,'rgba(0,0,0,0)');
 c.save();c.lineTo(X(p[p.length-1][0]),H);c.lineTo(X(p[0][0]),H);c.closePath();c.fillStyle=g;c.fill();c.restore();
 c.beginPath();p.forEach(function(x,i){var px=X(x[0]),py=Y(x[1]);if(!i)c.moveTo(px,py);else{var q=p[i-1],qx=X(q[0]),qy=Y(q[1]);c.quadraticCurveTo(qx,qy,(qx+px)/2,(qy+py)/2);if(i===p.length-1)c.lineTo(px,py)}});
 c.save();c.shadowColor=col;c.shadowBlur=14;c.strokeStyle=col;c.lineWidth=2.6;c.lineJoin='round';c.stroke();c.restore();c.strokeStyle=col;c.lineWidth=1.6;c.stroke();
 var lx=X(p[p.length-1][0]),ly=Y(p[p.length-1][1]);var bd=$('bdot');if(bd){bd.hidden=false;bd.style.left=(cv.offsetLeft+lx-1)+'px';bd.style.top=(cv.offsetTop+ly)+'px';bd.style.color=col}c.save();c.shadowColor=col;c.shadowBlur=12;c.beginPath();c.arc(lx-1,ly,4.2,0,7);c.fillStyle=col;c.fill();c.restore();
 if(hov!=null){var best=null;p.forEach(function(x){var d=Math.abs(X(x[0])-hov);if(!best||d<best[0])best=[d,x]});if(best){var bx=X(best[1][0]);c.strokeStyle='rgba(255,255,255,.25)';c.lineWidth=1;c.beginPath();c.moveTo(bx,0);c.lineTo(bx,H);c.stroke();
  var dd=new Date(best[1][0]*1000);$('btip').textContent=('0'+dd.getUTCDate()).slice(-2)+'.'+('0'+(dd.getUTCMonth()+1)).slice(-2)+'. '+('0'+dd.getUTCHours()).slice(-2)+':'+('0'+dd.getUTCMinutes()).slice(-2)+' \u00b7 '+money(best[1][1])}}else $('btip').textContent=''}
function seg(){[].forEach.call($('brg').children,function(b){b.classList.toggle('on',b.dataset.r===st.r)});[].forEach.call($('bsw').children,function(b){b.classList.toggle('on',b.dataset.s===st.s)})}
$('brg').addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;st.r=b.dataset.r;save();seg();drawBal()});
$('bsw').addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;st.s=b.dataset.s;save();seg();drawBal()});
$('b2').addEventListener('click',function(){st.s=st.s==='meme'?'alp':'meme';save();seg();drawBal()});
function hv(e){var r=cv.getBoundingClientRect();hov=(e.touches?e.touches[0].clientX:e.clientX)-r.left;window.__deskTouch=Date.now();drawBal()}
cv.addEventListener('mousemove',hv);cv.addEventListener('touchstart',hv,{passive:true});cv.addEventListener('touchmove',hv,{passive:true});
cv.addEventListener('mouseleave',function(){hov=null;drawBal()});cv.addEventListener('touchend',function(){setTimeout(function(){hov=null;drawBal()},1500)});
seg();drawBal();var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(drawBal,120)});
// analysis rotation (latest scan run: passed candidates + closest rejects)
var ai=0;function anShow(){var a=[].slice.call(document.querySelectorAll('#f-analysis .anc'));if(!a.length)return;ai=ai%a.length;a.forEach(function(x,i){x.classList.toggle('on',i===ai)});
 [].forEach.call(document.querySelectorAll('#f-analysis .andots i'),function(x,i){x.classList.toggle('on',i===ai)})}
setInterval(function(){if(document.hidden)return;ai++;anShow()},6500);
$('f-analysis').addEventListener('click',function(e){if(e.target.closest('a'))return;ai++;anShow()});anShow();
// holdings: show all
var hold=$('hold');if(st.all)hold.classList.add('all');
hold.addEventListener('click',function(e){if(e.target.closest('.hmore')){st.all=1;save();hold.classList.add('all')}});
// live data hook (LIVE_JS polls data.json every 15 s and calls deskPost)
var prev=window.deskPost;window.deskPost=function(x,d){if(prev)try{prev(x,d)}catch(e){}if(d&&d.savip){D=d;SV=d.savip;labels();head();if(window.DeskFloor)DeskFloor.update(SV.desks);drawBal();anShow()}};

// ---------- SAVIP live (2026-10-21): browser re-marks open meme positions from DexScreener's public keyless API (CORS *),
// recomputes value / P&L exactly like the server mark (value = qty x price, P&L = value - cost), ticks counters, fires floor bubbles.
// No keys and no account data leave the page; requests go out with credentials:'omit' and no referrer.
var LV={px:{},ref:{},sp:{},ok:0,fail:0,alerts:{},evt:null,lp:[],srv:null,srvNow:0,anv:null,acts:null};
function tw(el,to,fmt){if(!el)return;var fr=el._v;if(fr==null){var t=parseFloat(String(el.textContent).replace(/[^0-9.\-]/g,''));fr=isFinite(t)?t:to}
 el._v=to;if(Math.abs(fr-to)<1e-12){el.textContent=fmt(to);return}var t0=performance.now(),D0=600;
 el.classList.remove('lvup','lvdn');void el.offsetWidth;el.classList.add(to>fr?'lvup':'lvdn');clearTimeout(el._ft);el._ft=setTimeout(function(){el.classList.remove('lvup','lvdn')},1100);
 cancelAnimationFrame(el._raf);(function st(now){var k=Math.min(1,(now-t0)/D0),e=1-Math.pow(1-k,3);el.textContent=fmt(fr+(to-fr)*e);if(k<1)el._raf=requestAnimationFrame(st)})(t0)}
function LVd(){return(D&&D.savip&&D.savip.live)||{}}
function offs(){var e=D&&D.equity;return e&&e.now&&D.generated_ts?Math.round((e.now-D.generated_ts)/900)*900:0}
function mints(){var m={};(LVd().pos||[]).forEach(function(p){if(p.mint&&/^[1-9A-HJ-NP-Za-km-z]{32,50}$/.test(p.mint))m[p.mint]=1});return Object.keys(m).slice(0,30)}
function pick(arr,mint,pool){var b=null;(arr||[]).forEach(function(p){if(!p||!p.baseToken||p.baseToken.address!==mint)return;if(pool&&p.pairAddress===pool){b=p;b._x=1}else if(!b||(!b._x&&((p.liquidity||{}).usd||0)>((b.liquidity||{}).usd||0)))b=p});return b}
function dexPoll(){var m=mints();if(!m.length||document.hidden)return;var ctl=window.AbortController?new AbortController():null,to=setTimeout(function(){if(ctl)ctl.abort()},6000);
 fetch('https://api.dexscreener.com/tokens/v1/solana/'+m.join(',')+'?t='+Math.floor(Date.now()/8000),{signal:ctl?ctl.signal:undefined,credentials:'omit',referrerPolicy:'no-referrer',mode:'cors'})
 .then(function(r){if(!r.ok)throw new Error('http '+r.status);return r.json()})
 .then(function(arr){clearTimeout(to);LV.ok=Date.now();LV.fail=0;(LVd().pos||[]).forEach(function(p){var pr=pick(arr,p.mint,p.pool),px=pr&&parseFloat(pr.priceUsd);if(px>0)LV.px[p.mint]=px});applyLive();netDot()})
 .catch(function(){clearTimeout(to);LV.fail++;netDot()})}
function sparkTail(row,ck,px){var base=(row.dataset.sp||'').split(',').map(parseFloat).filter(isFinite);var a=LV.sp[ck]=LV.sp[ck]||[];if(!a.length||a[a.length-1]!==px)a.push(px);if(a.length>40)a.shift();
 var v=base.concat(a).slice(-60);if(v.length<2)return;var svg=row.querySelector('svg.spk');if(!svg)return;var w=84,h=30,lo=Math.min.apply(null,v),hi=Math.max.apply(null,v),r=(hi-lo)||Math.abs(hi)*.01||1;
 var pts=v.map(function(q,i){return(i*(w-2)/(v.length-1)+1).toFixed(1)+','+(h-2-(q-lo)/r*(h-4)).toFixed(1)}).join(' '),col=v[v.length-1]>=v[0]?'#22e33a':'#ff4d2e';
 svg.innerHTML='<polyline points="'+pts+'" fill="none" stroke="'+col+'" stroke-width="1.6" stroke-linejoin="round" vector-effect="non-scaling-stroke"/><circle class="spd" cx="'+(w-1)+'" cy="'+(h-2-(v[v.length-1]-lo)/r*(h-4)).toFixed(1)+'" r="1.8" fill="'+col+'"/>'}
function candleTick(d,px){var cs=d.candles;if(!cs||!cs.length||!d.ctf||!d.ct)return;var now=Date.now()/1000+offs(),last=cs[cs.length-1];
 if(now>=d.ct+d.ctf){var n=Math.floor((now-d.ct)/d.ctf);d.ct+=n*d.ctf;cs.push([last[3],px,px,px,0]);if(cs.length>72)cs.shift()}
 else{last[3]=px;if(px>last[1])last[1]=px;if(px<last[2])last[2]=px}d.last=px}
function alertDesk(id,bot,txt){LV.alerts[id]={n:bot,txt:txt,t:Date.now()/1000};attachAlerts()}
function attachAlerts(){(SV.desks||[]).forEach(function(d){var a=LV.alerts[d.id];if(a&&Date.now()/1000-a.t<8)d.alert=a;else delete d.alert})}
function eqMerge(){var e=D&&D.equity&&D.equity.meme;if(!e)return;if(LV.srv!==e._srv){e._srv=e.pts.slice();LV.srv=e._srv;LV.srvNow=D.equity.now;LV.lp=LV.lp.filter(function(x){return x[0]>LV.srvNow})}
 e.pts=e._srv.concat(LV.lp);if(LV.lp.length)D.equity.now=Math.max(LV.srvNow,LV.lp[LV.lp.length-1][0])}
function applyLive(){var L=LVd(),pos=L.pos||[],tot=0,by={};
 pos.forEach(function(p){var px=LV.px[p.mint]||p.last,val=p.qty*px,pnl=val-p.cost,pct=p.cost?pnl/p.cost*100:0;p.lpx=px;p.lv=val;p.lpnl=pnl;p.lpct=pct;tot+=val-p.v;(by[p.desk]=by[p.desk]||[]).push(p);
  var row=document.querySelector('.hr[data-ck="'+p.ck+'"]');if(row){var b=row.querySelector('.hr-v b'),pl=row.querySelector('.hr-v .pl'),pd=row.querySelector('.hr-pl b');
   tw(b,val,money);if(pl){tw(pl,pct,function(x){return sp(x)});pl.className='pl '+(pnl>=0?'pos':'neg')}
   if(pd){tw(pd,pnl,function(x){return(x>=0?'+':'-')+'$'+Math.abs(x).toFixed(2)});pd.className=pnl>=0?'pos':'neg'}if(LV.px[p.mint])sparkTail(row,p.ck,px)}
  var r0=LV.ref[p.mint];if(!r0)LV.ref[p.mint]=px;else if(Math.abs(px/r0-1)>=.05){alertDesk(p.desk,'RISK',p.name+' '+sp((px/r0-1)*100,1)+' move');LV.ref[p.mint]=px}});
 (SV.desks||[]).forEach(function(d){var ps=by[d.id];if(!ps||d.note!=='open')return;var m=ps.filter(function(p){return p.name===d.ticker})[0]||ps[0];
  d.pct=+m.lpct.toFixed(2);d.pnl=ps.reduce(function(a,p){return a+p.lpnl},0);d.value=ps.reduce(function(a,p){return a+p.lv},0);d.floats=ps.map(function(p){return+p.lpct.toFixed(1)});
  d.hp=ps.map(function(p){return[p.name,+p.lpct.toFixed(2)]});if(LV.px[m.mint])candleTick(d,m.lpx)});
 var e=D&&D.equity&&D.equity.meme;if(e&&e.pts&&e.pts.length){eqMerge();var srvEq=e._srv[e._srv.length-1][1],nowL=Math.floor(Date.now()/1000)+offs();
  if(!LV.lp.length||nowL-LV.lp[LV.lp.length-1][0]>=4){LV.lp.push([nowL,+(srvEq+tot).toFixed(4)]);if(LV.lp.length>900)LV.lp.shift()}else LV.lp[LV.lp.length-1][1]=+(srvEq+tot).toFixed(4);eqMerge()}
 attachAlerts();labels();head();if(window.DeskFloor)DeskFloor.update(SV.desks);drawBal()}
function netDot(){var el=$('hdot'),now=Date.now(),dl=window.deskLive||{},dOk=dl.lastOk||0,dex=mints().length,off=(dl.fail>=2&&now-dOk>45000)||(dex&&LV.fail>=3);
 var stale=!off&&((now-dOk>150000)||(dex&&LV.ok&&now-LV.ok>40000));if(el){el.className='hdot'+(off?' off':stale?' stale':'');el.title=off?'offline \u00b7 showing last data':stale?'stale':'live'}}
function ageTxt(s){s=Math.max(0,Math.round(s));return s<90?s+'s':s<5400?Math.round(s/60)+'m':Math.round(s/3600)+'h'}
function lvst(){var el=$('lvst');if(!el)return;var L=LVd(),now=Date.now()/1000,h='';
 if(mints().length)h+='<span class="lvm">meme '+(LV.ok?'live \u00b7 '+ageTxt(now-LV.ok/1000):'\u2026')+'</span>';
 if(L.alp_at)h+='<span>alpaca \u00b7 '+ageTxt(now-L.alp_at)+'</span>';el.innerHTML=h;netDot()}
// meme equity is exactly known even with nothing open (cash) -> keep the LIVE line running to "now"
function eqIdle(){if(document.hidden||mints().length)return;var e=D&&D.equity&&D.equity.meme;if(!e||!e.pts||!e.pts.length)return;eqMerge();var nowL=Math.floor(Date.now()/1000)+offs(),v=e._srv[e._srv.length-1][1];
 LV.lp.push([nowL,v]);if(LV.lp.length>900)LV.lp.shift();eqMerge();if(st.s==='meme')drawBal()}
// new data.json: slide in new activity rows, count up scan counters, bubble on new trades
var pre0=window.deskPre;window.deskPre=function(){if(pre0)try{pre0()}catch(e){}LV.acts={};[].forEach.call(document.querySelectorAll('#f-activity2 .ar'),function(r){LV.acts[r.textContent]=1});
 var ah=$('f-an_head');LV.anv=ah?(ah.textContent.match(/\d+/g)||[]).map(Number):null};
var post0=window.deskPost;window.deskPost=function(x,d){if(d&&d.savip&&d.savip.live){var ev=d.savip.live.evt;if(ev&&LV.evt&&ev.id!==LV.evt){var t=ev.side==='buy'?'bought '+ev.name+' $'+Math.abs(ev.usd).toFixed(2):(/stop/i.test(ev.reason)?'stop hit \u00b7 ':/take/i.test(ev.reason)?'take profit \u00b7 ':'sold ')+ev.name+' '+(ev.usd>=0?'+':'-')+'$'+Math.abs(ev.usd).toFixed(2);
   alertDesk(ev.desk||'meme',ev.alpaca?'RISK':'FILLS',t)}if(ev)LV.evt=ev.id}
 if(post0)try{post0(x,d)}catch(e){}
 if(LV.acts){[].forEach.call(document.querySelectorAll('#f-activity2 .ar'),function(r,i){if(!LV.acts[r.textContent]&&Object.keys(LV.acts).length){r.classList.add('lvnew');r.style.animationDelay=(i*70)+'ms'}})}
 var ah=$('f-an_head');if(ah&&LV.anv&&LV.anv.length===2){var nv=(ah.textContent.match(/\d+/g)||[]).map(Number);if(nv.length===2&&(nv[0]!==LV.anv[0]||nv[1]!==LV.anv[1])){var a0=LV.anv,t0=performance.now();
   (function c(now){var k=Math.min(1,(now-t0)/900),e=1-Math.pow(1-k,3);ah.innerHTML=Math.round(a0[0]+(nv[0]-a0[0])*e)+' scanned \u00b7 <em>'+Math.round(a0[1]+(nv[1]-a0[1])*e)+' dropped</em>';if(k<1)requestAnimationFrame(c)})(t0)}}
 if(d&&d.savip&&d.savip.live)applyLive();lvst()};
LV.evt=(LVd().evt||{}).id||null;
var dexT=null,idleT=null;function lvStart(){clearInterval(dexT);clearInterval(idleT);dexPoll();dexT=setInterval(dexPoll,8000);idleT=setInterval(eqIdle,5000)}
function lvStop(){clearInterval(dexT);clearInterval(idleT);dexT=idleT=null}
document.addEventListener('visibilitychange',function(){if(document.hidden)lvStop();else{lvStart();clock()}});
setInterval(function(){if(!document.hidden)lvst()},1000);
if(!document.hidden)lvStart();applyLive();lvst();
})();"""
