#!/usr/bin/env python3
"""Build ~/.desk/dashboard/index.html (single file, inline CSS/SVG, no JS deps, no secrets)."""
import os, re, glob, json, html, shutil, datetime as dt
from zoneinfo import ZoneInfo

DESK = os.path.expanduser("~/.desk")
BER, NY, UTC = ZoneInfo("Europe/Berlin"), ZoneInfo("America/New_York"), dt.timezone.utc
NOW = dt.datetime.now(UTC)
esc = html.escape

def load_env():
    if os.environ.get("ALPACA_KEY") and os.environ.get("ALPACA_SECRET"): return   # 2026-10-22 github: env (Actions secrets) first
    p = f"{DESK}/alpaca.env"
    for line in open(p):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.replace("export ", "").strip()] = v.strip().strip('"\'')

def tail(path, n, max_bytes=4_000_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - max_bytes)); b = f.read()
        lines = b.decode("utf-8", "replace").splitlines()
        if size > max_bytes and lines: lines = lines[1:]   # drop partial first line
        return lines[-n:]
    except FileNotFoundError: return []

def next_ny(hh, mm, weekdays):
    t = NOW.astimezone(NY)
    for d in range(0, 10):
        c = (t + dt.timedelta(days=d)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if c > t and c.isoweekday() in weekdays:
            return c
def fmt_ber(x): return x.astimezone(BER).strftime("%a %d %b %H:%M") + " Berlin"
def money(x): return f"${x:,.2f}"

# ---------- gather (each block fails soft) ----------
errors = []
dial = None
files = sorted(glob.glob(f"{DESK}/dial/*.json"))
if files:
    try: dial = json.load(open(files[-1]))
    except Exception as e: errors.append(f"dial: {e}")

acct = positions = orders = bank_state = None
try:
    load_env()
    assert os.environ.get("ALPACA_PAPER", "1") == "1"
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    import sys; sys.path.insert(0, DESK); import desk_bank
    tc = TradingClient(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"], paper=True)
    a = tc.get_account()
    acct = {"status": str(a.status.value), "equity": float(a.equity), "cash": float(a.cash), "last_equity": float(a.last_equity)}
    positions = [{"symbol": p.symbol, "qty": float(p.qty), "mv": float(p.market_value), "upl": float(p.unrealized_pl), "entry": float(p.avg_entry_price or 0),
                  "price": float(p.current_price or 0), "cost": float(p.cost_basis or 0)} for p in tc.get_all_positions()]
    orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=15))
    bank_state = desk_bank.state(tc)
except Exception as e:
    errors.append(f"alpaca: {type(e).__name__}: {e}")
if os.environ.get("DESK_DASH_OUT") and os.environ.get("DESK_DASH_TEST_ALP"):   # test builds only: inject fake Alpaca positions
    positions = (positions or []) + json.load(open(os.environ["DESK_DASH_TEST_ALP"]))
bank = json.load(open(f"{DESK}/bank.json"))
start = float(bank["start_capital"])

# ---------- meme sleeve (SIMULATED pump.fun fills) merged into desk ----------
meme = None
try:
    import meme as meme_mod
    meme = meme_mod.meme_state()
    if os.environ.get("DESK_DASH_OUT") and os.environ.get("DESK_DASH_TEST_OPEN"):   # test builds only: inject fake open positions
        meme["open"] = meme["open"] + json.load(open(os.environ["DESK_DASH_TEST_OPEN"]))
except Exception as e:
    errors.append(f"meme: {e}")
alp_pnl = (bank_state["equity"] - bank_state["start_capital"]) if bank_state else 0.0
if bank_state is None:
    bank_state = {"start_capital": start, "cash": start, "holdings": {}, "realized": 0.0, "unrealized": 0.0, "equity": start,
                  "wins": 0, "losses": 0, "fills": [], "closed_trades": [], "open_orders": []}
    errors.append("Alpaca desk-bank P&L unavailable this build")
if meme:
    mp = meme["equity"] - meme["start"]
    bank_state["equity"] += mp; bank_state["realized"] += meme["realized"]; bank_state["unrealized"] += meme["unrealized"]
    bank_state["cash"] += meme["realized"] - sum(o["cost_usd"] for o in meme["open"])
    bank_state["wins"] += meme["wins"]; bank_state["losses"] += meme["losses"]
    for c in meme["closed"]:
        bank_state["closed_trades"].append({"time": dt.datetime.fromisoformat(c["exit_time"]), "pnl": c["pnl"], "symbol": c["name"]})
    for o in meme["open"]:
        bank_state["holdings"][f'{o["name"]} (SIMULATED)'] = {"qty": o["qty"], "avg_cost": o["entry_price"], "price": o.get("last_price") or o["entry_price"],
            "market_value": o["qty"] * (o.get("last_price") or o["entry_price"]), "unrealized": o["qty"] * (o.get("last_price") or o["entry_price"]) - o["cost_usd"]}
meme_pnl = (meme["equity"] - meme["start"]) if meme else 0.0
# ---------- Alpaca PAPER sleeves (TREND/STOCKS/CRYPTO on the paper account, separate book from the $100 meme bank) ----------
def _js(p):
    try: return json.load(open(f"{DESK}/{p}"))
    except Exception: return None
alp = {"stocks": _js("stocks_state.json"), "crypto": _js("crypto_state.json"), "kill": _js("kill_state.json"), "kill_flag": _js("alp_kill.json"),
       "drift": _js("lists/drift.json"), "insiders": _js("lists/insiders.json")}
def _lsum(d):
    if not d: return {"status": "missing", "n": None, "names": None, "reason": "not built yet"}
    return {"status": d.get("status"), "n": len(d["names"]) if d.get("names") is not None else None, "generated_at": d.get("generated_at"),
            "names": [x["symbol"] for x in d["names"]][:16] if d.get("names") is not None else None, "reason": d.get("reason")}
alp_lists = {"DRIFT": _lsum(alp["drift"]), "INSIDERS": _lsum(alp["insiders"])}
def _sleeve(sym): return "trend" if sym in ("TQQQ", "SHY") else ("crypto" if sym.endswith("USD") and len(sym) <= 7 else "stocks")
alp_pos = {}
for p_ in positions or []: alp_pos.setdefault(_sleeve(p_["symbol"]), []).append(p_)
alp_mv = {k: sum(x["mv"] for x in v) for k, v in alp_pos.items()}
kill_today = bool(alp["kill_flag"] and alp["kill_flag"].get("date") == NOW.astimezone(NY).date().isoformat())
try:
    import sys as _s; _s.path.insert(0, DESK); import jev as _jev; jev_on = _jev.active()
except Exception: jev_on = False
import subprocess
try: gate_next = subprocess.run([f"{DESK}/venv/bin/python", f"{DESK}/meme_gate.py", "--next"], capture_output=True, text=True, timeout=20).stdout.strip()
except Exception: gate_next = ""

# ---------- history snapshot ----------
hist_path = f"{DESK}/history.csv"
def _last_hist_ts():
    try:
        l = tail(hist_path, 1)[0]
        return dt.datetime.fromisoformat(l.split(",")[0])
    except Exception: return None
_lh = _last_hist_ts()
if bank_state and not os.environ.get("DESK_DASH_OUT") and (_lh is None or (NOW - _lh).total_seconds() >= 270):   # test builds never write history
    new = not os.path.exists(hist_path)
    with open(hist_path, "a") as f:
        if new: f.write("timestamp_berlin,desk_equity,desk_cash,realized,unrealized\n")
        f.write(f"{NOW.astimezone(BER).isoformat(timespec='seconds')},{bank_state['equity']:.4f},{bank_state['cash']:.4f},{bank_state['realized']:.4f},{bank_state['unrealized']:.4f}\n")
hist = []
for line in tail(hist_path, 5000)[0:]:
    if line.startswith("timestamp"): continue
    try:
        t, e = line.split(",")[:2]; hist.append((dt.datetime.fromisoformat(t), float(e)))
    except Exception: pass

equity = bank_state["equity"] if bank_state else (hist[-1][1] if hist else start)
pnl = equity - start; pnl_pct = pnl / start * 100

# ---------- logs ----------
runner_log = tail(f"{DESK}/logs/runner.log", 400)
quant_log = tail(f"{DESK}/logs/quant.log", 100) + tail(f"{DESK}/logs/meme.log", 300) + tail(f"{DESK}/logs/alpaca_sleeves.log", 200)
tag_re = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \w+) (\[[A-Z]+\].*)$")
activity = []
for l in runner_log + quant_log:
    m = tag_re.match(l)
    if m and not m.group(2).startswith("[RUNNER]"):
        activity.append((m.group(1), m.group(2)))
activity.sort(key=lambda x: x[0], reverse=True)
last_dry = None
for l in reversed(runner_log):
    m = re.search(r"-> target (\w+)", l)
    if m:
        last_dry = (l[:24], m.group(1)); break

# ---------- schedule ----------
nxt_run = next_ny(15, 45, {1, 2, 3, 4, 5}); nxt_dial = next_ny(6, 0, set(range(1, 8)))
cron_txt = "\n".join(l for l in os.popen("crontab -l 2>/dev/null").read().splitlines() if not l.lstrip().startswith("#"))
cron_ok = os.popen("pgrep -x cron").read().strip() != ""
runner_sched = "run_strategy.sh" in cron_txt and cron_ok
stocks_sched = "run_alp.sh stocks" in cron_txt and cron_ok; crypto_sched = "run_alp.sh crypto" in cron_txt and cron_ok
kill_sched = "run_alp.sh kill" in cron_txt and cron_ok; lists_sched = "run_alp.sh lists" in cron_txt and cron_ok
nxt_cry = next_ny(20, 5, set(range(1, 8))); nxt_lists = next_ny(7, 30, {1, 2, 3, 4, 5})
dial_sched = "run_dial.sh" in cron_txt and cron_ok

# ---------- bots / pipeline ----------
deg = dial.get("degraded", []) if dial else []
fills = bank_state["fills"] if bank_state else []
holdings = bank_state["holdings"] if bank_state else {}
meme_sched = "meme_gate.py" in cron_txt and cron_ok and not os.path.exists(f"{DESK}/.meme_schedule_ended")
risk_sched = "run_meme.sh risk" in cron_txt and cron_ok
mlog = tail(f"{DESK}/logs/meme.log", 300)
def last_tag(tag):
    for l in reversed(mlog):
        if f"[{tag}]" in l: return l[11:16] + " " + l.split(f"[{tag}]", 1)[1].strip()[:40]
    return None
n_open = len(meme["open"]) if meme else 0; n_closed = len(meme["closed"]) if meme else 0
bots = [  # name, variant, status, note
    ("QUANT", "solid", "degraded" if deg else ("active" if dial and dial_sched else ("idle" if dial else "not set up")),
     f"dial {dial['date']} meme {dial['dial']['meme']}" if dial else "no dial yet"),
    ("SCAN", "outline", "active" if meme_sched else "idle", last_tag("SCAN") or "GeckoTerminal + pump.fun feeds + DexScreener"),
    ("JUDGE", "mask", "active" if meme_sched else "idle", (last_tag("JUDGE") or "buyers/flow gates + RugCheck") + " · PumpSwap only (curve → shadow)" + (" · Jev ON" if jev_on else " · Jev off (no key)")),
    ("SIZE", "outline", "active" if meme_sched else "idle", f"3% x bank x dial · max 3 open (+ NEW PAIRS 1.5%, max 2; 4 overall) · bank {money(meme['equity']) if meme else 'n/a'}"),
    ("FILLS", "mouth", "active" if n_open or n_closed else ("idle" if meme_sched else "not set up"), f"pump.fun simulated · {n_open} open/{n_closed} closed"),
    ("TREND", "solid", "halted" if kill_today else ("active" if runner_sched else "idle"),
     f"TQQQ/SHY 35% · 15:45 NY · {money(alp_mv.get('trend', 0))} · last {last_dry[1] if last_dry else '—'}"),
    ("STOCKS", "outline", "halted" if kill_today else ("active" if stocks_sched else "idle"),
     f"50%×dial · DRIFT {alp_lists['DRIFT']['n'] if alp_lists['DRIFT']['n'] is not None else 'null'} · INSIDERS {alp_lists['INSIDERS']['n'] if alp_lists['INSIDERS']['n'] is not None else 'null'} · {money(alp_mv.get('stocks', 0))}"),
    ("CRYPTO", "outline2", "halted" if kill_today else ("active" if crypto_sched else "idle"),
     f"15%×dial · 20:05 NY · targets {', '.join((dial or {}).get('crypto_targets', {}).get('weights', {}) or ['cash'])} · {money(alp_mv.get('crypto', 0))}"),
    ("RISK", "sweat", "active" if risk_sched else "idle", "fast exits 5×/min (~12 s, DexScreener + chain, 0 GT) · SL -30% curve / -20% PumpSwap · trail -25% (armed ≥ +15%; -20% once peak ≥ +100%) · TP ½ +50% + ¼ +100% · 60 min · vol decay · 24h cooldown · 4% DD"
     + (" · acct kill FIRED today" if kill_today else " · acct kill 4%/30 min" if kill_sched else "")),
    ("CHIEF", "outline2", "active" if meme_sched else ("idle" if os.path.exists(f"{DESK}/.meme_schedule_ended") else "not set up"),
     ("cadence " + gate_next.split()[0].split("=")[1].replace("min", " min")) if gate_next.startswith("cadence=") and "None" not in gate_next else "schedule ended"),
]
A, A2 = "#5b4bdb", "#4c3fb5"
def blob(variant, status):
    solid = variant in ("solid", "mask", "mouth", "sweat")
    body = (f'<path d="M30 6 C46 6 52 16 52 30 C52 46 45 56 30 56 C15 56 8 46 8 31 C8 16 14 6 30 6Z" '
            + (f'fill="{A}"/>' if solid else f'fill="#1c1c1e" stroke="{A}" stroke-width="3"/>'))
    eyes = '<rect x="20" y="22" width="6" height="12" rx="3" fill="#fff"/><rect x="34" y="22" width="6" height="12" rx="3" fill="#fff"/>'
    extra = ""
    if variant == "mask":
        eyes = ('<rect x="12" y="21" width="36" height="12" rx="6" fill="#fff"/>'
                '<rect x="20" y="24" width="6" height="6" rx="3" fill="#1c1c1e"/><rect x="34" y="24" width="6" height="6" rx="3" fill="#1c1c1e"/>')
    if variant == "mouth": extra = '<path d="M19 42 H41" stroke="#fff" stroke-width="3.5" stroke-linecap="round"/>'
    if variant == "sweat": extra = '<path d="M47 10 C50 15 51 17 49 19 C47 21 44 19 45 16 C45 14 46 12 47 10Z" fill="#fff"/>'
    if variant == "outline2": extra = f'<path d="M24 41 Q30 45 36 41" stroke="{A}" stroke-width="3" fill="none" stroke-linecap="round"/>'
    return f'<svg viewBox="0 0 60 60" width="54" height="54" class="blob {"dim" if status == "not set up" else ""}">{body}{eyes}{extra}</svg>'

# ---------- chart ----------
def chart(points, trades, w=760, h=260, padl=14, padr=110, padt=26, padb=26):
    if not points:
        return '<div class="empty">No balance snapshots yet — first snapshot is written on the next rebuild.</div>'
    vals = [v for _, v in points]; lo, hi = min(vals + [start]), max(vals + [start])
    if hi - lo < 0.5: lo, hi = lo - 0.5, hi + 0.5
    t0, t1 = points[0][0].timestamp(), points[-1][0].timestamp(); span = (t1 - t0) or 1
    X = lambda t: padl + (w - padl - padr) * ((t.timestamp() - t0) / span if len(points) > 1 else 1)
    Y = lambda v: h - padb - (h - padt - padb) * (v - lo) / (hi - lo)
    pts = [(X(t), Y(v)) for t, v in points]
    if len(pts) == 1: pts = [(padl, pts[0][1])] + pts
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = line + f" L{pts[-1][0]:.1f},{h-padb} L{pts[0][0]:.1f},{h-padb} Z"
    sy = Y(start); lx, ly = pts[-1]
    badges = ""
    for tr in trades[-12:]:
        tt = tr["time"]; tt = tt if tt.tzinfo else tt.replace(tzinfo=UTC)
        if not points or tt.timestamp() < t0: bx = padl
        else: bx = X(tt)
        near = min(points, key=lambda p: abs(p[0].timestamp() - tt.timestamp()))[1]
        by = Y(near) - 18; win = tr["pnl"] >= 0
        lab = f'{"CLOSED" if win else "STOPPED"} {"+" if win else "-"}${abs(tr["pnl"]):.2f}'
        bw = 8 + 6.6 * len(lab)
        badges += (f'<g><rect x="{bx-bw/2:.1f}" y="{by-11:.1f}" width="{bw:.1f}" height="18" rx="9" '
                   + (f'fill="{A}"/>' if win else f'fill="#1c1c1e" stroke="{A}" stroke-dasharray="3 2"/>')
                   + f'<text x="{bx:.1f}" y="{by+2:.1f}" text-anchor="middle" class="bt">{lab}</text>'
                   f'<line x1="{bx:.1f}" x2="{bx:.1f}" y1="{by+7:.1f}" y2="{Y(near):.1f}" stroke="{A}" stroke-opacity=".6"/></g>')
    tip = money(points[-1][1])
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" preserveAspectRatio="xMidYMid meet">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{A}" stop-opacity=".45"/>'
            f'<stop offset="1" stop-color="{A}" stop-opacity="0"/></linearGradient>'
            f'<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3.5" result="b"/>'
            '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
            f'<line x1="{padl}" x2="{w-padr}" y1="{sy:.1f}" y2="{sy:.1f}" stroke="#3a3a3c" stroke-dasharray="4 5"/>'
            f'<text x="{padl+2}" y="{sy-6:.1f}" class="ax">START {money(start)}</text>'
            f'<text x="{padl+2}" y="{padt-10}" class="ax">HI {money(hi)}</text><text x="{padl+2}" y="{h-8}" class="ax">LO {money(lo)}</text>'
            f'<path d="{area}" fill="url(#g)" class="area"/>'
            f'<path d="{line}" fill="none" stroke="{A}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round" pathLength="1" class="draw" filter="url(#glow)"/>'
            f'{badges}<circle cx="{lx:.1f}" cy="{ly:.1f}" r="9" fill="{A}" opacity=".35" class="pulse"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4.5" fill="#fff" stroke="{A}" stroke-width="2.5"/>'
            f'<g><rect x="{lx+12:.1f}" y="{ly-13:.1f}" width="{padr-18}" height="26" rx="13" fill="{A}"/>'
            f'<text x="{lx+12+(padr-18)/2:.1f}" y="{ly+4.5:.1f}" text-anchor="middle" class="tip">{tip}</text></g></svg>'
            f'<div class="sub">{len(points)} snapshot(s) · {points[0][0].strftime("%d %b %H:%M")} → {points[-1][0].strftime("%d %b %H:%M")} Berlin</div>')

def ring(wins, losses):
    n = wins + losses; r = 30; C = 2 * 3.14159 * r; frac = wins / n if n else 0
    return (f'<svg viewBox="0 0 76 76" width="76" height="76"><circle cx="38" cy="38" r="{r}" stroke="#2c2c2e" stroke-width="8" fill="none"/>'
            f'<circle cx="38" cy="38" r="{r}" stroke="{A}" stroke-width="8" fill="none" stroke-linecap="round" class="ringarc" '
            f'stroke-dasharray="{C*frac:.1f} {C:.1f}" transform="rotate(-90 38 38)"/>'
            f'<text x="38" y="43" text-anchor="middle" class="ringt">{f"{frac*100:.0f}%" if n else "—"}</text></svg>')

# ---------- scan rejects ----------
rej_rec = judge_rec = None; rej_runs = 0
for rf in sorted(glob.glob(f"{DESK}/scan/rejects-*.jsonl"))[-2:][::-1]:
    lines = tail(rf, 400)
    for l in reversed(lines):
        try: r = json.loads(l)
        except Exception: continue
        if r.get("type") == "scan" and rej_rec is None: rej_rec = r
        if r.get("type") == "judge" and judge_rec is None: judge_rec = r
    if rej_rec: break
if rej_rec and judge_rec and judge_rec.get("run_id") != rej_rec.get("run_id"): judge_rec = None
def kusd(x): return "n/a" if x is None else (f"${x/1e6:.2f}M" if x >= 1e6 else f"${x/1e3:.1f}k" if x >= 1e3 else f"${x:.0f}")
def bs(t): return f'{(t or {}).get("buys", "?")}/{(t or {}).get("sells", "?")}'
def age_s(h): return "n/a" if h is None else (f"{h*60:.0f}m" if h < 1 else f"{h:.1f}h")
rej_html = '<div class="empty">No scan run recorded yet.</div>'
if rej_rec:
    summ = sorted(rej_rec["by_reason"].items(), key=lambda kv: -kv[1])
    summ_html = "".join(f'<span class="rchip">{esc(k)} <b>{v}</b></span>' for k, v in summ) or '<span class="sub">none</span>'
    def row(c, verdict, why):
        nm = (c.get("name") or "?").split(" / ")[0]
        _u = c.get("url") or f'https://www.geckoterminal.com/solana/pools/{c.get("pool")}'
        return (f'<tr><td><a href="{esc(_u)}" target="_blank" rel="noopener">{esc(nm[:22])}</a>'
                f'<div class="vn">{"bonding curve" if c.get("venue") == "bonding_curve" else "PumpSwap"}</div>'
                + (f'<div class="vn" style="color:#e8cf6a" title="bought in last 6h by vetted wallet(s) {esc(", ".join((c.get("wallet") or {}).get("wallets") or []))}; ranking boost only, all gates still apply">Wallet: {c["wallet"]["n"]} of {c["wallet"]["of"]}</div>' if c.get("wallet") else "") + '</td>'
                f'<td>{kusd(c.get("mcap_usd"))}</td><td title="{"derived from pump.fun curve: real SOL x SOL price" if c.get("liq_derived") else "GeckoTerminal reserve"}">{"~" if c.get("liq_derived") else ""}{kusd(c.get("liquidity_usd"))}</td><td>{kusd(c.get("vol_h24"))}</td>'
                f'<td>{age_s(c.get("age_h"))}</td><td>{bs(c.get("tx_m15"))}</td><td>{bs(c.get("tx_h1"))}</td>'
                f'<td class="why"><span class="vd vd-{verdict.lower()}">{verdict}</span> {why}</td></tr>')
    jmap = {d.get("pool"): d for d in (judge_rec or {}).get("decisions", []) if d.get("pool")}
    jrows = "".join(row(c, {"PICK": "PICK", "WATCH": "WATCH"}.get(jmap.get(c["pool"], {}).get("decision"), "JUDGE"),
                        esc(jmap.get(c["pool"], {}).get("reason", "no judge record for this run (scan-only run)")))
                    for c in rej_rec.get("passed_candidates", []))
    rrows = "".join(row(c, "SCAN", "<br>".join(esc(f) for f in c["fails"])) for c in rej_rec.get("rejects", [])[:25])
    hdr = '<tr><th>TOKEN</th><th>MCAP</th><th>LIQ</th><th>VOL 24H</th><th>AGE</th><th>B/S M15</th><th>B/S H1</th><th>REJECTED BY</th></tr>'
    jnone = ('<div class="sub">JUDGE gates (rank order, first pass is bought, max 1/run): unique buyers h1 ≥ 50 · buys/sells m15 ≥ 1.2 · '
             'buyers/buy h1 ≥ 0.25 · price h1 +10..+300% (watchlisted: ≥ 0%) · then RugCheck: no mint/freeze authority, transfer fee 0, not rugged, no danger risks, '
             'PumpSwap LP locked ≥ 95%, creator ≤ 5%, largest non-pool holder ≤ 15%, insiders ≤ 10 (unreachable → no buy) · then DIP: price 12–40% below its 60-min high and m5 ≥ −10%, '
             'otherwise → WATCHLIST (60 min) and re-checked every scan · 24h COOLDOWN after a stop-out / losing close</div>')
    jrc = {}
    for d in (judge_rec or {}).get("decisions", []):
        k = (d.get("reason") or "").split(":")[0].split(" (")[0]
        if d.get("pool"): jrc[k] = jrc.get(k, 0) + 1
    if jrc: jnone += '<div class="rchips mt">' + "".join(f'<span class="rchip">{esc(k)} <b>{v}</b></span>' for k, v in sorted(jrc.items(), key=lambda kv: -kv[1])) + '</div>'
    if judge_rec and not jmap:
        jnone += f'<div class="sub">JUDGE: {esc(judge_rec["decisions"][0].get("reason", ""))}</div>'
    try: _wl = {k: v for k, v in json.load(open(f"{DESK}/meme_watchlist.json")).items() if dt.datetime.fromisoformat(v["expires_at"]) > dt.datetime.now(dt.timezone.utc)}
    except Exception: _wl = {}
    try: _cd = {k: v for k, v in json.load(open(f"{DESK}/meme_cooldown.json")).items() if dt.datetime.fromisoformat(v["until"]) > dt.datetime.now(dt.timezone.utc)}
    except Exception: _cd = {}
    _cdn = sorted({v["name"].split(" / ")[0] for v in _cd.values()})
    _src = rej_rec.get("sources") or {}
    wl_rows = "".join(f'<tr><td>{esc((v.get("name") or "?").split(" / ")[0][:22])}<div class="vn">{"bonding curve" if v.get("venue") == "bonding_curve" else "PumpSwap"}</div></td>'
                      f'<td>{esc(fmt_ber(dt.datetime.fromisoformat(v["added_at"])))}</td><td>{esc(fmt_ber(dt.datetime.fromisoformat(v["expires_at"])))}</td>'
                      f'<td class="why">{esc(v.get("last_reason", ""))}</td></tr>' for v in sorted(_wl.values(), key=lambda v: v["added_at"]))
    wl_html = (f'<details class="mt"><summary>WATCHLIST · {len(_wl)} waiting for a dip</summary>'
               + (f'<div class="tscroll"><table class="rt"><tr><th>TOKEN</th><th>ADDED</th><th>EXPIRES</th><th>LAST CHECK</th></tr>{wl_rows}</table></div>' if wl_rows else '<div class="empty">empty</div>')
               + '</details>')
    rej_html = (f'<div class="sub"><b>WATCHLIST {len(_wl)}</b> · <b>COOLDOWN {len(_cdn)}</b>{(" (" + esc(", ".join(_cdn)) + ")") if _cdn else ""}'
                f'{(" · " + str(rej_rec.get("cooldown_rejected") or 0) + " pool(s) rejected by cooldown this run") if rej_rec.get("cooldown_rejected") else ""}</div>'
                + (f'<div class="sub">universe: GeckoTerminal {_src.get("geckoterminal_pools", "?")} + extra {_src.get("extra_pools_added", 0)} '
                   f'(pump.fun/DexScreener: {_src.get("extra_mints", "?")} new mints → {_src.get("prefilter_kept", "?")} prefiltered → GT-enriched) · {rej_rec.get("gt_calls", "?")} GT calls</div>' if _src else "") +
                (f'<div class="sub">wallet signal: {_src.get("wallet_signal_mints", 0)} mint(s) bought by vetted wallets in 6h · {_src.get("wallet_signal_matched", 0)} seen in this scan (rank boost only, all gates apply)</div>' if "wallet_signal_mints" in _src else "") +
                f'<div class="sub">run {esc(rej_rec["scanned_at"])} · {rej_rec["pools_seen"]} pools seen · {rej_rec["passed"]} passed SCAN · '
                f'{rej_rec["rejected_total"]} rejected · source {esc(rej_rec["source"])} · ~ = bonding-curve liquidity derived from curve (real SOL × SOL price)</div>'
                + ("".join(f'<div class="sub">{"bonding curve" if v == "bonding_curve" else "PumpSwap"}: {st["evaluated"]} evaluated · {st["passed"]} passed · {st["rejected"]} rejected'
                  + (f' · GT liquidity 0/null on {st["gt_liq_zero_or_null"]}, now ~derived' if v == "bonding_curve" else "") + '</div>'
                  for v, st in (rej_rec.get("venue_stats") or {}).items())) +
                f'<div class="lbl mt">REJECTION REASONS (a pool can fail several)</div><div class="rchips">{summ_html}</div>{jnone}'
                f'<details open class="mt"><summary>passed SCAN → JUDGE / RugCheck verdicts ({len(rej_rec.get("passed_candidates", []))})</summary>'
                + (f'<div class="tscroll"><table class="rt">{hdr}{jrows}</table></div>' if jrows else '<div class="empty">No candidate passed SCAN in this run.</div>') +
                f'</details>{wl_html}<details open class="mt"><summary>top {min(25, len(rej_rec.get("rejects", [])))} SCAN rejects · fewest failed filters first</summary>'
                + (f'<div class="tscroll"><table class="rt">{hdr}{rrows}</table></div>' if rrows else '<div class="empty">No rejects stored.</div>') + '</details>')

# ---------- NEW PAIRS sleeve card (newpairs.py, 2026-10-20) ----------
try: _np = json.load(open(f"{DESK}/scan/newpairs_latest.json"))
except Exception: _np = None
def _np_rows(rs, judged=True):
    out = ""
    for r in rs:
        tr = r.get("traction") or {}
        trt = (f'buyers {tr.get("buyers", "?")} · B/S {tr.get("buys", "?")}/{tr.get("sells", "?")}' + (f' · curve {tr["progress"]:.0f}%' if tr.get("progress") is not None else "")) if tr else ""
        dec = r.get("decision", "—") if judged else "narrative < threshold"
        out += (f'<tr><td>{esc(r.get("symbol", "?"))}<div class="vn">{esc((r.get("name") or "")[:24])}</div></td><td>{r.get("age_min", 0):.1f}m</td>'
                f'<td><b>{r.get("score")}</b>{(" · " + esc(r["tier"])) if r.get("tier") else ""}</td><td class="why">{esc(", ".join(r.get("matched") or []) or "—")}<div class="vn">{esc(" · ".join(r.get("why") or [])[:160])}</div></td>'
                f'<td class="why"><b>{esc(dec)}</b> {esc((r.get("reason") or "")[:180])}<div class="vn">{esc(trt)}</div></td></tr>')
    return out
_npo = [o for o in (meme or {}).get("open", []) if o.get("sleeve") == "newpairs"]
_npc = [c for c in (meme or {}).get("closed", []) if c.get("sleeve") == "newpairs"][-8:]
_np_pos = "".join(f'<tr><td>{esc(o["name"].split(" / ")[0])}<div class="vn">NEW PAIR</div></td><td><b>{esc((o.get("tier") or "").upper())}</b> · {o.get("narrative_score")}</td>'
                  f'<td>{money(o["cost_usd"])}</td><td class="{"up" if (o.get("last_price") or 0) >= o["entry_price"] else "down"}">{((o.get("last_price") or o["entry_price"]) / o["entry_price"] - 1) * 100:+.0f}%</td>'
                  f'<td class="why">{esc(", ".join(o.get("narrative") or []))}<div class="vn">exits: ' + esc(" / ".join(f"{int(f*100)}% @ +{int(g*100)}%" for g, f in (o.get("exit") or {}).get("tp", [])) + f' · trail -{int((o.get("exit") or {}).get("trail", 0.25)*100)}% after +{int((o.get("exit") or {}).get("trail_arm", 0.15)*100)}% · time stop {(o.get("exit") or {}).get("time_stop_min", 30)} min' + (" if not in profit" if (o.get("exit") or {}).get("time_stop_only_if_not_profit") else "")) + '</div></td></tr>' for o in _npo)
_np_pos += "".join(f'<tr><td>{esc(c["name"].split(" / ")[0])}<div class="vn">closed{" (part)" if c.get("partial") else ""}</div></td><td>{esc((c.get("tier") or "").upper())}</td><td>{money(c["cost_usd"])}</td>'
                   f'<td class="{"up" if c["pnl"] >= 0 else "down"}">{c["pnl"]:+.2f}</td><td class="why">{esc((c.get("exit_reason") or "")[:120])}</td></tr>' for c in reversed(_npc))
if _np:
    np_html = (f'<div class="sub">run {esc(_np.get("run_at", "")[11:19])} · <b>{_np.get("new_launches", 0)}</b> new launches this minute · <b>{_np.get("in_window_2_15m", 0)}</b> aged 2–15 min · '
               f'<b>{_np.get("narrative_pass", 0)}</b> narrative ≥ {_np.get("threshold")} · <b>{_np.get("safety_pass", 0)}</b> passed safety · {esc(_np.get("trending", ""))}'
               + (f' · BUY {esc(_np["bought"])}' if _np.get("bought") else (f' · {esc(_np["buy_note"])}' if _np.get("buy_note") else "")) + '</div>'
               '<div class="sub">score = 7×weight (famous people/crypto w7–10, classic memes w5–8, trending X topics w1–10 +10, generic animals/AI/events w4–7; description ×0.7) '
               '+ socials (own X +10, X post +6, website +6, TG +3; none −20) − copycat −30 − impersonation −25/−15 − spam/bot −10 · pass ≥ 70 · STRONG ≥ 85 · '
               'safety: RugCheck gates + dev not sold + not serial launcher (≤ 2 other coins/24h) + ≥ 25 unique buyers + buys > sells + curve 5–60% + first-2-block snipers ≤ 10% · '
               'ticket 1.5% × bank × dial · max 2 new pairs (4 overall) · NORMAL: ½ @ +50%, ¼ @ +100%, trail −25% after +15% (−20% once peak ≥ +100%), 30-min time stop only if not in profit (else trailing; 12 h cap) · STRONG: ⅓ @ +100%, ⅓ @ +300%, trail −35% after +50%, 3 h time stop only if not in profit (12 h cap) · all: −30% hard stop, dev-sell / volume-collapse / RugCheck-danger exits</div>'
               + (f'<div class="lbl mt">NEW-PAIR POSITIONS</div><div class="tscroll"><table class="rt"><tr><th>TOKEN</th><th>TIER</th><th>COST</th><th>P&amp;L</th><th>NARRATIVE / EXITS</th></tr>{_np_pos}</table></div>' if _np_pos else "")
               + f'<details open class="mt"><summary>candidates (narrative ≥ {_np.get("threshold")}) · {len(_np.get("candidates") or [])}</summary>'
               + (f'<div class="tscroll"><table class="rt"><tr><th>TOKEN</th><th>AGE</th><th>SCORE</th><th>MATCHED</th><th>VERDICT</th></tr>{_np_rows(_np.get("candidates") or [])}</table></div>' if _np.get("candidates") else '<div class="empty">No fresh launch with a strong enough narrative right now.</div>')
               + '</details>'
               + f'<details class="mt"><summary>near misses (narrative 45–69) · {len(_np.get("near_misses") or [])}</summary>'
               + (f'<div class="tscroll"><table class="rt"><tr><th>TOKEN</th><th>AGE</th><th>SCORE</th><th>MATCHED</th><th>VERDICT</th></tr>{_np_rows(_np.get("near_misses") or [], False)}</table></div>' if _np.get("near_misses") else '<div class="empty">none</div>')
               + '</details>' + (f'<div class="sub">errors: {esc("; ".join(_np.get("errors") or []))}</div>' if _np.get("errors") else ""))
else:
    np_html = '<div class="empty">NEW PAIRS sleeve has not run yet.</div>'

# ---------- SHADOW book (upgrade 3): virtual trades the desk did not take ----------
shadow_sum = None
try:
    import shadow as _sh; shadow_sum = _sh.summary()
except Exception as e: errors.append(f"shadow: {type(e).__name__}: {e}")
if shadow_sum and shadow_sum["rows"]:
    def _pc(x): return "—" if x is None else f"{x*100:+.0f}%"
    def _pc0(x): return "—" if x is None else f"{x*100:.0f}%"
    _sr = "".join(f'<tr><td>{esc(r["cat"])}</td><td>{r["open"]}</td><td>{r["closed"]}</td><td>{_pc0(r["win_rate"])}</td>'
                  f'<td class="{"up" if r["pnl"] >= 0 else "down"}">{r["pnl"]:+.2f}</td><td>{_pc(r["avg_pct"])}</td><td class="{"up" if r["open_pnl"] >= 0 else "down"}">{r["open_pnl"]:+.2f}</td></tr>' for r in shadow_sum["rows"][:30])
    shadow_html = (f'<div class="sub"><b>{shadow_sum["closed"]}</b> closed · win rate <b>{_pc0(shadow_sum["win_rate"])}</b> · realized <b>{shadow_sum["pnl"]:+.2f}</b> · '
                   f'<b>{shadow_sum["open"]}</b> open ({shadow_sum["open_pnl"]:+.2f}) · virtual only, never in the bank · same fills + exit rules as the real book</div>'
                   f'<div class="tscroll"><table class="rt"><tr><th>BLOCKED BY</th><th>OPEN</th><th>CLOSED</th><th>WIN</th><th>P&amp;L $</th><th>AVG</th><th>OPEN P&amp;L</th></tr>{_sr}</table></div>')
else:
    shadow_html = '<div class="empty">No shadow trades yet (capacity-blocked, curve-blocked and single-gate misses are recorded here).</div>'

# ---------- 2026-10-20 21:2x REDESIGN: OFFENE TRADES / HEUTE GESCHLOSSEN / Kopf (German, mobile-first; display only) ----------
import sys as _s3; _s3.path.insert(0, DESK)
try: from leads import lead_id as _lead_id
except Exception: _lead_id = lambda m: ("L" + str(m)[:6]) if m else None
TODAY_BER = NOW.astimezone(BER).date()
def de_num(x, dec=2):
    return f"{x:,.{dec}f}".replace(",", "\u2009").replace(".", ",").replace("\u2009", ".")
def de_usd(x, dec=2, sign=False):
    s = de_num(abs(x), dec) + "\u00a0$"
    return (("+" if x > 0 else "−" if x < 0 else "±") + s) if sign else (("−" if x < 0 else "") + s)
def de_pct(x, dec=1, sign=True):   # x as fraction
    v = x * 100; s = de_num(abs(v), dec) + "\u00a0%"
    return (("+" if v > 0 else "−" if v < 0 else "±") + s) if sign else s
def de_px(p):
    if p is None: return "—"
    import math
    if p >= 100: return de_num(p, 2)
    if p >= 1: return de_num(p, 3)
    dec = min(12, max(4, -int(math.floor(math.log10(p))) + 3)) if p > 0 else 4
    return de_num(p, dec)
def de_dur(minutes):
    m = int(max(0, minutes))
    if m < 60: return f"{m}\u00a0Min"
    h, m = divmod(m, 60)
    if h < 24: return f"{h}\u00a0Std {m:02d}\u00a0Min"
    d, h = divmod(h, 24); return f"{d}\u00a0T {h}\u00a0Std"
def de_time(t):
    t = t if isinstance(t, dt.datetime) else dt.datetime.fromisoformat(str(t))
    t = t if t.tzinfo else t.replace(tzinfo=UTC); b = t.astimezone(BER)
    return b.strftime("%H:%M") if b.date() == TODAY_BER else b.strftime("%d.%m. %H:%M")
def pn(x): return "pos" if x > 1e-9 else "neg" if x < -1e-9 else "zero"
REASON_DE = [("stop-loss", "Stop-Loss"), ("trailing stop", "Trailing-Stop"), ("take-profit", "Take-Profit"), ("time stop", "Zeit-Stop"),
             ("max hold", "Max. Haltedauer"), ("volume decay", "Volumen-Einbruch"), ("dev sold", "Dev verkauft"), ("dev-sell", "Dev verkauft"),
             ("rugcheck", "RugCheck-Gefahr"), ("daily drawdown", "Tages-Drawdown")]
def reason_de(r):
    rl = (r or "").lower()
    for k, v in REASON_DE:
        if rl.startswith(k) or k in rl[:40]: return v
    return (r or "—").split(":")[0][:28]
_SLEEVE_LBL = {"meme": "MEME", "newpairs": "NEW PAIRS", "trend": "TREND", "stocks": "STOCKS", "crypto": "CRYPTO"}
_SLEEVE_SUB = {"meme": "Solana · Hauptsleeve (Paper-Sim)", "newpairs": "pump.fun Neustarts (Paper-Sim)", "trend": "Alpaca Paper · TQQQ/SHY 3× Nasdaq",
               "stocks": "Alpaca Paper · DRIFT + INSIDERS", "crypto": "Alpaca Paper · BTC/ETH/SOL"}
open_cards = {k: [] for k in _SLEEVE_LBL}; open_rows = []; hold_items = []   # hold_items -> SAVIP holdings rows (dash_savip.py)
chart_meme_req, chart_alp_req = [], []   # tap-to-expand charts (dash_charts.py, display only)
def _with_chart(card, ck):
    i = card.index(">"); card = card[:i] + f' data-ck="{esc(ck)}"' + card[i:]
    return card[:-6] + '<div class="chint"><span class="a">▸ Chart anzeigen</span><span class="b">▾ Chart schließen</span></div><div class="tc-chart"></div></div>'
   # open_rows -> data.json (machine-readable)
def _kv(k, v, cls=""): return f'<div class="kv2"><span>{k}</span><b class="{cls}">{v}</b></div>'
# --- meme main + new pairs (meme_positions.json via meme.meme_state) ---
_partials = {}
for c in (meme or {}).get("closed", []):
    if c.get("partial"): _partials[(c.get("token"), c.get("entry_time"))] = _partials.get((c.get("token"), c.get("entry_time")), 0.0) + c["pnl"]
for o in (meme or {}).get("open", []):
    try:
        oc = dict(o); ex = meme_mod.exit_plan(oc) or {}
        sl_ = "newpairs" if o.get("sleeve") == "newpairs" else "meme"
        entry = o["entry_price"]; last = o.get("last_price") or entry
        peak = max(o.get("peak_price") or o.get("entry_mid") or entry, last)
        chg, peak_g = last / entry - 1, peak / entry - 1
        sl = o.get("stop_loss") or meme_mod.STOP_LOSS.get(o.get("venue"), 0.20)
        t_arm, t_stop = ex.get("trail_arm", meme_mod.TRAIL_ARM), ex.get("trail", meme_mod.TRAIL_STOP)
        tight = ex.get("trail_tight")
        if tight and peak_g >= tight[0]: t_stop = min(t_stop, tight[1])
        held = (NOW - dt.datetime.fromisoformat(o["entry_time"])).total_seconds() / 60
        ts_min = ex.get("time_stop_min", meme_mod.TIME_STOP_MIN); ts_only_loss = ex.get("time_stop_only_if_not_profit", False)
        if ex.get("trail_after_time_stop") and held >= ts_min and chg > 0: peak_g = max(peak_g, t_arm)
        armed = peak_g >= t_arm
        hard_px = entry * (1 - sl); trail_px = peak * (1 - t_stop) if armed else None
        if trail_px and trail_px > hard_px:
            stop_px = trail_px; stop_txt = f'Trailing {de_px(trail_px)} <i>(−{t_stop*100:.0f}\u00a0% vom Peak · {de_pct(trail_px/last-1, 0)} vom Kurs)</i>'
        else:
            stop_px = hard_px; stop_txt = (f'Stop {de_px(hard_px)} <i>(−{sl*100:.0f}\u00a0% · {de_pct(hard_px/last-1, 0)} vom Kurs)</i>'
                                           + (f'<br><i>Trailing −{t_stop*100:.0f}\u00a0% ab Peak +{t_arm*100:.0f}\u00a0%</i>' if not armed else ""))
        ladder = ex.get("tp") or []; hits = o.get("tp_hits") if o.get("tp_hits") is not None else oc.get("tp_hits", [])
        nxt = ladder[len(hits)] if len(hits) < len(ladder) else None
        tp_px = entry * (1 + nxt[0]) if nxt else None
        tp_txt = (f'TP{len(hits)+1}/{len(ladder)} {de_px(tp_px)} <i>(+{nxt[0]*100:.0f}\u00a0% · {nxt[1]*100:.0f}\u00a0% der Startmenge)</i>' if nxt
                  else ('alle TPs erreicht · Rest läuft mit Trailing' if ladder else '—'))
        left = ts_min - held
        ts_txt = (("Zeit-Stop fällig" if left <= 0 else f"Zeit-Stop in {de_dur(left)}") + (" (nur wenn nicht im Plus)" if ts_only_loss else "")) if ts_min else ""
        value = o["qty"] * last; cost = o["cost_usd"]; upl = value - cost; upl_pct = upl / cost if cost else 0.0
        lead = o.get("lead") or _lead_id(o.get("token"))
        nm = (o.get("name") or "?").split(" / ")[0]
        dex = f'https://dexscreener.com/solana/{o.get("pool")}' if o.get("pool") else (o.get("url") or "#")
        pf = f'https://pump.fun/coin/{o.get("token")}' if o.get("token") else None
        part = _partials.get((o.get("token"), o.get("entry_time")))
        venue = "Bonding Curve" if o.get("venue") == "bonding_curve" else "PumpSwap"
        tier = f' · {esc((o.get("tier") or "").upper())}' if sl_ == "newpairs" and o.get("tier") else ""
        try: age_px = (NOW - dt.datetime.fromisoformat(o["last_check"])).total_seconds()
        except Exception: age_px = None
        open_rows.append({"sleeve": sl_, "name": nm, "lead": lead, "entry_time": o["entry_time"], "entry_price": entry, "price": last, "value_usd": round(value, 4),
                          "cost_usd": cost, "upl_usd": round(upl, 4), "upl_pct": round(upl_pct * 100, 2), "peak_pct": round(peak_g * 100, 2), "stop_price": stop_px,
                          "next_tp_price": tp_px, "held_min": round(held, 1)})
        open_cards[sl_].append(
            f'<div class="tc tc-{pn(upl)}"><div class="tc-h"><div class="tc-n"><a class="tn" href="{esc(dex)}" target="_blank" rel="noopener">{esc(nm[:24])}</a>'
            f' <span class="lead">{esc(lead or "")}</span><div class="tsl">{_SLEEVE_LBL[sl_]}{tier} · {venue}'
            + (f' · <a href="{esc(pf)}" target="_blank" rel="noopener">pump.fun</a>' if pf else "") + f' · <a href="{esc(dex)}" target="_blank" rel="noopener">DexScreener</a></div></div>'
            f'<div class="tc-p {pn(upl)}"><div class="pb">{de_usd(upl, 2, True)}</div><div class="pp">{de_pct(upl_pct)}</div></div></div>'
            '<div class="tc-g">'
            + _kv("Einstieg", f'{de_time(o["entry_time"])} · {de_px(entry)}')
            + _kv("Aktuell", de_px(last) + (f' <i>({age_px:.0f}\u00a0s alt)</i>' if age_px is not None and age_px < 3600 else ""), pn(chg))
            + _kv("Wert / Einsatz", f'{de_usd(value)} / {de_usd(cost)}')
            + _kv("Peak", de_pct(peak_g, 0), pn(peak_g))
            + _kv("Offen seit", de_dur(held) + (f' <i>· {ts_txt}</i>' if ts_txt else ""))
            + (_kv("Teilgewinn realisiert", de_usd(part, 2, True), pn(part)) if part else "")
            + '</div>'
            + f'<div class="tc-x"><div><span>Stop aktiv</span>{stop_txt}</div><div><span>Nächstes TP</span>{tp_txt}</div></div></div>')
        _ck = "m_" + str(o.get("pool"))
        _cd = open_cards[sl_][-1]
        hold_items.append({"ck": _ck, "sleeve": sl_, "name": nm, "value": value, "cost": cost, "upl": upl, "upl_pct": upl_pct * 100, "desk": _SLEEVE_LBL[sl_],
                           "status": ("TP taken · runner" if part else ("trailing" if armed else "in a trade")), "det": _cd[_cd.index('<div class="tc-g">'):-6]})
        open_cards[sl_][-1] = _with_chart(open_cards[sl_][-1], _ck)
        _lv = [{"p": stop_px, "c": "#ff453a", "t": "Trailing" if (trail_px and trail_px > hard_px) else "Stop"}]
        if tp_px: _lv.append({"p": tp_px, "c": "#30d158", "t": f"TP{len(hits)+1}"})
        _sells = [{"t": dt.datetime.fromisoformat(c["exit_time"]).timestamp(), "p": c.get("exit_price"), "txt": "Teilverkauf " + de_usd(c["pnl"], 2, True)}
                  for c in (meme or {}).get("closed", []) if c.get("partial") and c.get("token") == o.get("token") and c.get("entry_time") == o.get("entry_time")]
        chart_meme_req.append({"key": _ck, "o": o, "lead": lead, "levels": _lv, "sells": _sells})
    except Exception as e:
        errors.append(f"open-card {o.get('name')}: {type(e).__name__}: {e}")
# --- Alpaca paper positions (read-only) ---
_alp_entry = {}
if positions:
    try:
        from alpaca.trading.enums import OrderSide as _OS
        _ords = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500, after=NOW - dt.timedelta(days=120)))
        _fl = sorted([x for x in _ords if x.filled_at and float(x.filled_qty or 0) > 0], key=lambda x: x.filled_at)
        for sym in {p_["symbol"] for p_ in positions}:
            run, startt = 0.0, None
            for x in _fl:
                if x.symbol.replace("/", "") != sym: continue
                q = float(x.filled_qty)
                if x.side == _OS.BUY:
                    if run <= 1e-9: startt = x.filled_at
                    run += q
                else:
                    run -= q
                    if run <= 1e-9: run, startt = 0.0, None
            _alp_entry[sym] = startt
    except Exception as e: errors.append(f"alpaca entry times: {type(e).__name__}: {e}")
_ALP_EXIT = {"trend": ("kein Kurs-Stop · Signalwechsel TQQQ↔SHY (200-Tage-Linie) um 15:45 NY", "kein TP (Trendfolge)"),
             "stocks": ("kein Kurs-Stop · Verkauf wenn von beiden Listen gefallen oder Dial < 0,50 (15:45 NY)", "kein TP (Rebalance)"),
             "crypto": ("kein Kurs-Stop · Verkauf wenn nicht mehr Top-2-Momentum oder Dial < 0,50 (20:05 NY)", "kein TP (Rebalance)")}
for p_ in positions or []:
    try:
        s_ = _sleeve(p_["symbol"]); entry = p_.get("entry") or 0.0; last = p_.get("price") or 0.0
        cost = p_.get("cost") or (entry * p_["qty"]); upl = p_["upl"]; upl_pct = upl / cost if cost else 0.0
        et = _alp_entry.get(p_["symbol"]) or (dt.datetime.fromisoformat(p_["entry_time"]) if p_.get("entry_time") else None); held = (NOW - et).total_seconds() / 60 if et else None
        url = (f'https://www.tradingview.com/symbols/{p_["symbol"].replace("USD", "")}USD/' if s_ == "crypto" else f'https://finance.yahoo.com/quote/{p_["symbol"]}')
        open_rows.append({"sleeve": s_, "name": p_["symbol"], "entry_time": et.isoformat() if et else None, "entry_price": entry, "price": last,
                          "value_usd": p_["mv"], "cost_usd": cost, "upl_usd": upl, "upl_pct": round(upl_pct * 100, 2), "peak_pct": None, "held_min": round(held, 1) if held else None})
        stop_txt, tp_txt = _ALP_EXIT[s_]
        open_cards[s_].append(
            f'<div class="tc tc-{pn(upl)}"><div class="tc-h"><div class="tc-n"><a class="tn" href="{esc(url)}" target="_blank" rel="noopener">{esc(p_["symbol"])}</a>'
            f'<div class="tsl">{_SLEEVE_LBL[s_]} · Alpaca Paper · {de_num(p_["qty"], 4 if p_["qty"] < 10 else 2)} Stk</div></div>'
            f'<div class="tc-p {pn(upl)}"><div class="pb">{de_usd(upl, 2, True)}</div><div class="pp">{de_pct(upl_pct)}</div></div></div>'
            '<div class="tc-g">'
            + _kv("Einstieg", f'{de_time(et) if et else "—"} · {de_px(entry)}')
            + _kv("Aktuell", de_px(last), pn(last - entry))
            + _kv("Wert / Einsatz", f'{de_usd(p_["mv"])} / {de_usd(cost)}')
            + _kv("Peak", "— <i>(nicht erfasst)</i>")
            + _kv("Offen seit", de_dur(held) if held is not None else "—")
            + '</div>'
            + f'<div class="tc-x"><div><span>Stop aktiv</span>{stop_txt}<br><i>Konto-Kill-Switch −4\u00a0% vs. Vortag (alle 30 Min)</i></div><div><span>Nächstes TP</span>{tp_txt}</div></div></div>')
        _ck = "a_" + p_["symbol"]
        _cd = open_cards[s_][-1]
        hold_items.append({"ck": _ck, "sleeve": s_, "name": p_["symbol"], "value": p_["mv"], "cost": cost, "upl": upl, "upl_pct": upl_pct * 100, "desk": _SLEEVE_LBL[s_],
                           "status": "in a trade", "det": _cd[_cd.index('<div class="tc-g">'):-6]})
        open_cards[s_][-1] = _with_chart(open_cards[s_][-1], _ck)
        chart_alp_req.append((_ck, p_["symbol"], s_, et.timestamp() if et else None, entry))
    except Exception as e:
        errors.append(f"open-card {p_.get('symbol')}: {type(e).__name__}: {e}")
charts = {}
try:
    import dash_charts as _dc
    if chart_meme_req:
        _dc.meme_requests(chart_meme_req)
        _facts = _dc.ds_facts([q["o"].get("pool") for q in chart_meme_req]); _mlog = tail(f"{DESK}/logs/meme.log", 3000)
        for q in chart_meme_req:
            try: charts[q["key"]] = _dc.meme_chart(q, _mlog, _facts)
            except Exception as e: errors.append(f"chart {q['key'][:12]}: {type(e).__name__}: {e}")
    if chart_alp_req: _dc.alp_prefetch(chart_alp_req, os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET"))
    for _ck, _sym, _sl, _ets, _epx in chart_alp_req:
        try: charts[_ck] = _dc.alpaca_chart(_ck, _sym, _sl, _ets, _epx, [], os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET"))
        except Exception as e: errors.append(f"chart {_sym}: {type(e).__name__}: {e}")
    chart_notes = _dc.notes()
except Exception as e:
    errors.append(f"charts: {type(e).__name__}: {e}"); chart_notes = {}
equity_data = {}
try:
    import dash_charts as _dc
    _nowl = _dc.loc(NOW.timestamp()); _mid = dt.datetime.combine(TODAY_BER, dt.time(0), BER).timestamp()
    _mp = [[_dc.loc(t.timestamp()), round(v, 4)] for t, v in hist if _dc.loc(t.timestamp()) < _nowl] + [[_nowl, round(equity, 4)]]   # desk equity as recorded in history.csv
    _mm = []
    for c in (meme or {}).get("closed", []):
        if abs(c.get("pnl") or 0) >= 0.40:
            _mm.append({"t": _dc.loc(dt.datetime.fromisoformat(c["exit_time"]).timestamp()), "txt": "", "abs": abs(c["pnl"]),
                        "c": "#30d158" if c["pnl"] > 0 else "#ff453a", "up": c["pnl"] > 0})
    _mm = sorted(_mm, key=lambda m: -m["abs"])[:8]   # only the 8 biggest trades (arrows, no text) -> no clutter on mobile
    for m in _mm[:3]: m["txt"] = de_usd(m["abs"] if m["up"] else -m["abs"], 2, True)
    try:
        for l in open(f"{DESK}/logs/risk_state.jsonl"):
            r = json.loads(l)
            if r.get("halted") and (r.get("halted_at") or r.get("at")):
                _mm.append({"t": _dc.loc(dt.datetime.fromisoformat(r.get("halted_at") or r.get("at")).timestamp()), "txt": "HALT", "c": "#ff9f0a", "up": False, "shape": "square"})
    except Exception: pass
    _ap = (_dc.alp_history(tc) if acct else []) + ([[_nowl, round(acct["equity"], 2)]] if acct else [])
    _am = []
    if alp["kill_flag"] and alp["kill_flag"].get("fired_at"):
        _am.append({"t": _dc.loc(dt.datetime.fromisoformat(alp["kill_flag"]["fired_at"]).timestamp()), "txt": "KILL", "c": "#ff9f0a", "up": False, "shape": "square"})
    equity_data = {"meme": {"start": start, "pts": _mp, "markers": _mm}, "alp": {"start": 100000.0, "pts": _ap, "markers": _am}, "today0": _dc.loc(_mid), "now": _nowl}
except Exception as e:
    errors.append(f"equity chart: {type(e).__name__}: {e}")
n_open_by = {k: len(v) for k, v in open_cards.items()}
_open_html = ""
for k in ("meme", "newpairs", "trend", "stocks", "crypto"):
    unreachable = k in ("trend", "stocks", "crypto") and positions is None
    head = (f'<div class="slh"><b>{_SLEEVE_LBL[k]}</b><span>{_SLEEVE_SUB[k]}</span>'
            f'<em class="{"cnt1" if n_open_by[k] else ""}">{n_open_by[k]} offen</em></div>')
    if unreachable:
        _open_html += f'<div class="sl">{head}<div class="none neg">Alpaca nicht erreichbar – Positionen unbekannt</div></div>'
    elif open_cards[k]:
        _open_html += f'<div class="sl">{head}<div class="tcs">{"".join(open_cards[k])}</div></div>'
    else:
        _open_html += f'<div class="sl">{head}<div class="none">Keine offenen Trades in {_SLEEVE_LBL[k]}.</div></div>'
_n_open = sum(n_open_by.values())
_upl_tot = sum(r["upl_usd"] for r in open_rows if r["sleeve"] in ("meme", "newpairs"))
_upl_alp = sum(r["upl_usd"] for r in open_rows if r["sleeve"] not in ("meme", "newpairs"))
open_section = (f'<div class="sech"><h2>Offene Trades <span class="badge-n">{_n_open}</span></h2>'
                f'<div class="secs">Meme offen <b class="{pn(_upl_tot)}">{de_usd(_upl_tot, 2, True)}</b> · Alpaca offen <b class="{pn(_upl_alp)}">{de_usd(_upl_alp, 2, True)}</b></div></div>'
                + _open_html)
# --- Heute geschlossen ---
_ct = []
for c in (meme or {}).get("closed", []):
    try:
        xt = dt.datetime.fromisoformat(c["exit_time"])
        if xt.astimezone(BER).date() != TODAY_BER: continue
        sl_ = "newpairs" if c.get("sleeve") == "newpairs" else "meme"
        nm = (c.get("name") or "?").split(" / ")[0]; lead = c.get("lead") or _lead_id(c.get("token"))
        held = (xt - dt.datetime.fromisoformat(c["entry_time"])).total_seconds() / 60
        cost = c.get("cost_usd") or 0.0; pct = c["pnl"] / cost if cost else 0.0
        dex = f'https://dexscreener.com/solana/{c.get("pool")}' if c.get("pool") else (c.get("url") or "#")
        _ct.append((xt, sl_, c["pnl"], (
            f'<div class="cr cr-{pn(c["pnl"])}"><div class="cr1"><a class="tn" href="{esc(dex)}" target="_blank" rel="noopener">{esc(nm[:22])}</a>'
            f' <span class="lead">{esc(lead or "")}</span> <span class="tag2">{_SLEEVE_LBL[sl_]}</span>'
            + (' <span class="tag2">Teilverkauf</span>' if c.get("partial") else "") +
            f'<b class="crp {pn(c["pnl"])}">{de_usd(c["pnl"], 2, True)} <i>{de_pct(pct, 0)}</i></b></div>'
            f'<div class="cr2">{de_time(c["entry_time"])} → {de_time(xt)} · {de_dur(held)} · {de_px(c["entry_price"])} → {de_px(c.get("exit_price"))} · Einsatz {de_usd(cost)}'
            f' · <span title="{esc(c.get("exit_reason") or "")}">{esc(reason_de(c.get("exit_reason")))}</span></div></div>')))
    except Exception as e: errors.append(f"closed-today {c.get('name')}: {type(e).__name__}: {e}")
for o in orders or []:   # Alpaca paper sleeves: today's filled SELL orders (P&L per fill not tracked by Alpaca orders)
    try:
        if not o.filled_at or str(o.side.value) != "sell" or o.filled_at.astimezone(BER).date() != TODAY_BER: continue
        s_ = _sleeve(o.symbol.replace("/", ""))
        _ct.append((o.filled_at, s_, 0.0, f'<div class="cr cr-zero"><div class="cr1"><b class="tn">{esc(o.symbol)}</b> <span class="tag2">{_SLEEVE_LBL[s_]}</span>'
                    f'<b class="crp">verkauft</b></div><div class="cr2">{de_time(o.filled_at)} · {esc(str(o.filled_qty))} Stk @ {de_px(float(o.filled_avg_price or 0))} · Alpaca Paper</div></div>'))
    except Exception: pass
_ct.sort(key=lambda x: x[0], reverse=True)
_ct_pnl = sum(x[2] for x in _ct); _ct_w = sum(1 for x in _ct if x[2] > 0); _ct_l = sum(1 for x in _ct if x[2] < 0)
_ct_full = sum(1 for c in (meme or {}).get("closed", []) if not c.get("partial") and dt.datetime.fromisoformat(c["exit_time"]).astimezone(BER).date() == TODAY_BER)
closed_section = (f'<div class="sech"><h2>Heute geschlossen <span class="badge-n">{len(_ct)}</span></h2>'
                  f'<div class="secs">Ergebnis <b class="{pn(_ct_pnl)}">{de_usd(_ct_pnl, 2, True)}</b> · {_ct_w} Gewinner / {_ct_l} Verlierer · {_ct_full} komplett, {len(_ct) - _ct_full} Teilverkäufe/Alpaca</div></div>'
                  + ("".join(x[3] for x in _ct[:12]) or '<div class="none">Heute noch keine Trades geschlossen.</div>')
                  + (f'<details class="more"><summary>{len(_ct) - 12} weitere heute geschlossen</summary>{"".join(x[3] for x in _ct[12:])}</details>' if len(_ct) > 12 else ""))
# --- Kopf: Equity / heute / seit Start / Status ---
try: _rs = meme_mod.risk_state(); meme_halt = meme_mod.daily_halt_active()
except Exception as e: _rs, meme_halt = {}, None; errors.append(f"risk_state: {e}")
if meme:
    if _rs.get("date") == TODAY_BER.isoformat() and _rs.get("day_open_equity") is not None:
        meme_today = meme["equity"] + alp_pnl - float(_rs["day_open_equity"]); meme_today_src = "vs. Tagesstart (Risk-Engine)"
    else:
        meme_today = sum(c["pnl"] for c in meme["closed"] if dt.datetime.fromisoformat(c["exit_time"]).astimezone(BER).date() == TODAY_BER); meme_today_src = "realisiert heute"
    meme_since = meme["equity"] - meme["start"]
ALP_START = 100000.0
alp_today = (acct["equity"] - acct["last_equity"]) if acct and acct["last_equity"] else None
alp_since = (acct["equity"] - ALP_START) if acct else None
def _tile(title, sub, eq, today, since, base_today, base_since, extra=""):
    if eq is None: return f'<div class="tile"><div class="tt">{title}</div><div class="te neg">nicht erreichbar</div></div>'
    return (f'<div class="tile"><div class="tt">{title}<i>{sub}</i></div><div class="te">{de_usd(eq)}</div>'
            f'<div class="tr"><div><span>Heute</span><b class="{pn(today)}">{de_usd(today, 2, True)}</b><i>{de_pct(today/base_today) if base_today else ""}</i></div>'
            f'<div><span>Seit Start</span><b class="{pn(since)}">{de_usd(since, 2, True)}</b><i>{de_pct(since/base_since) if base_since else ""}</i></div></div>{extra}</div>')
_tiles = (_tile("MEME-BANK", f"virtuell · Start {de_usd(meme['start'], 0)} am {esc(bank['started'])}", meme["equity"], meme_today, meme_since,
                (meme["equity"] - meme_today) or None, meme["start"], f'<div class="tf">Bar {de_usd(meme["cash"])} · offen {de_usd(meme["unrealized"], 2, True)} · {meme_today_src}</div>')
          if meme else '<div class="tile"><div class="tt">MEME-BANK</div><div class="te neg">nicht lesbar</div></div>')
_tiles += _tile("ALPACA PAPER", f"TREND · STOCKS · CRYPTO · Start {de_usd(ALP_START, 0)}", acct["equity"] if acct else None, alp_today or 0.0, alp_since or 0.0,
                acct["last_equity"] if acct else None, ALP_START, f'<div class="tf">Bar {de_usd(acct["cash"])} · Konto {esc(acct["status"])}</div>' if acct else "")
_tot = (meme["equity"] if meme else 0.0) + (acct["equity"] if acct else 0.0)
_tot_today = (meme_today if meme else 0.0) + (alp_today or 0.0); _tot_since = (meme_since if meme else 0.0) + (alp_since or 0.0)
def _badge(ok, txt):
    return f'<span class="bdg {"ok" if ok is True else "bad" if ok is False else "warn"}"><i></i>{txt}</span>'
_kchg = (alp["kill"] or {}).get("change")
_badges = (_badge(None if meme_halt is None else not meme_halt, "MEME: HALT – Tagesverlust-Limit erreicht" if meme_halt else ("MEME: Handel aktiv" if meme_halt is False else "MEME: Status unbekannt"))
           + _badge(not kill_today if kill_sched else None, "ALPACA: KILL-SWITCH AUSGELÖST" if kill_today else
                    (f'ALPACA: Kill-Switch bereit ({de_pct(_kchg, 2) if _kchg is not None else "ok"})' if kill_sched else "ALPACA: Kill-Switch AUS"))
           + _badge(cron_ok, "Cron läuft" if cron_ok else "CRON STEHT"))
header_section = (f'<div class="hdr-top"><div><div class="logo2">Trading Desk <span class="paper">PAPER</span></div>'
                  f'<div class="upd">Stand {NOW.astimezone(BER).strftime("%d.%m.%Y %H:%M:%S")} Berlin</div></div>'
                  f'<div class="tot"><span>Gesamt</span><b>{de_usd(_tot)}</b><i>heute <b class="{pn(_tot_today)}">{de_usd(_tot_today, 2, True)}</b> · seit Start <b class="{pn(_tot_since)}">{de_usd(_tot_since, 2, True)}</b></i></div></div>'
                  f'<div class="badges">{_badges}</div><div class="tiles">{_tiles}</div>')
# --- details sections (new bodies) ---
def _wr(r): return "—" if r.get("win_rate") is None else f"{r['win_rate']*100:.0f}%"
_ctrl = [r for r in ((shadow_sum or {}).get("rows") or []) if str(r.get("cat", "")).startswith("control:")]
control_html = ('<div class="sub">Kontroll-Bot = Baseline ohne Judge-/RugCheck-/Dip-Filter (Top bzw. Zufalls-Scan-Passer), gleiche Fills und Exits, nur virtuell. Die Filter müssen diese Baseline schlagen.</div>'
                + ('<div class="tscroll"><table class="rt2"><tr><th>BOT</th><th>OFFEN</th><th>ZU</th><th>WIN</th><th>P&amp;L $</th><th>OFFEN $</th></tr>'
                   + "".join(f'<tr><td>{esc(r["cat"].split(":", 1)[1])}</td><td>{r["open"]}</td><td>{r["closed"]}</td><td>{_wr(r)}</td>'
                             f'<td class="{pn(r["pnl"])}">{r["pnl"]:+.2f}</td><td class="{pn(r["open_pnl"])}">{r["open_pnl"]:+.2f}</td></tr>' for r in _ctrl) + '</table></div>'
                   if _ctrl else '<div class="empty">Noch keine Kontroll-Trades.</div>'))
try:
    _rt = json.load(open(f"{DESK}/reject_tracker.json")); _rc = _rt.get("coins") or {}
    _gc = {}
    for v in _rc.values():
        for g in (v.get("gates") or ["?"])[:1]: _gc[g] = _gc.get(g, 0) + 1
    _hz = {h: sum(1 for v in _rc.values() if h in (v.get("samples") or {})) for h in ("t0", "1h", "6h", "24h")}
    try: _ro = sum(1 for _ in open(f"{DESK}/logs/reject_outcomes.jsonl"))
    except FileNotFoundError: _ro = 0
    rejtrack_html = (f'<div class="sub"><b>{len(_rc)}</b> Coins verfolgt · Preisproben t0 {_hz["t0"]} · +1h {_hz["1h"]} · +6h {_hz["6h"]} · +24h {_hz["24h"]} · {_ro} abgeschlossen (alle 5 Min, DexScreener)</div>'
                     '<div class="rchips mt">' + "".join(f'<span class="rchip">{esc(k)} <b>{v}</b></span>' for k, v in sorted(_gc.items(), key=lambda kv: -kv[1])[:20]) + '</div>')
except Exception as e:
    rejtrack_html = f'<div class="empty">Reject-Tracker nicht lesbar ({esc(type(e).__name__)}).</div>'
try:
    _cl = [l[3:].strip() for l in open(f"{DESK}/CHANGELOG_research.md") if l.startswith("## ")][-8:][::-1]
    _rdirs = sorted(os.listdir(f"{DESK}/research")) if os.path.isdir(f"{DESK}/research") else []
    research_html = (f'<div class="sub">Research-Ordner: {esc(", ".join(_rdirs) or "leer")} · letzte Einträge aus CHANGELOG_research.md:</div>'
                     + "".join(f'<div class="ln">{esc(x[:160])}</div>' for x in _cl))
except Exception as e:
    research_html = f'<div class="empty">Kein Research-Changelog ({esc(type(e).__name__)}).</div>'

# ---------- pieces ----------
pc = "up" if pnl > 0 else "down" if pnl < 0 else "flat"
wins, losses = (bank_state["wins"], bank_state["losses"]) if bank_state else (0, 0)
def cnt(v, fmt, txt): return f'<span class="cnt" data-v="{v:.4f}" data-f="{fmt}">{txt}</span>'

chips = '<div class="empty">No dial output yet.</div>'; bars = ""
if dial:
    lab = {"liquidity": "LIQ", "volatility": "VIX", "credit": "CREDIT", "btc": "BTC", "sol": "SOL", "nasdaq": "QQQ"}
    srcmap = {"liquidity": ["WALCL", "WTREGEN", "RRPONTSYD"], "volatility": ["VIXCLS"], "credit": ["BAMLH0A0HYM2"], "btc": ["BTC/USD"], "sol": ["SOL/USD"], "nasdaq": ["QQQ"]}
    def val(k, i):
        if not i: return "n/a"
        if k == "liquidity": return f"{i['change_4w_bn']:+.0f}bn/4w"
        if k == "volatility": return f"{i['vix_last']:.2f}"
        if k == "credit": return f"{i['change_4w']:+.2f}/4w"
        if k in ("btc", "sol"): s = [x for x in i if x.startswith("sma")][0]; return f"{i['close']/i[s]*100-100:+.1f}% vs {s[3:]}d"
        if k == "nasdaq": return f"{i['qqq_close']/i['sma200']*100-100:+.1f}% vs 200d"
    chips = ""
    for k, g in dial["greens"].items():
        d = any(s in deg for s in srcmap[k] + [k]); age = max(dial["data_age_hours"].get(s, 0) for s in srcmap[k])
        chips += (f'<span class="chip {"on" if g else "off"}" title="age {age}h">{lab[k]} {esc(val(k, dial["inputs"].get(k)))}'
                  f'<i>{age:.0f}h{" · DEGRADED" if d else ""}</i></span>')
    bars = "".join(f'<div class="dl"><span>{k.upper()}</span><div class="bar"><b style="width:{dial["dial"][k]*100:.0f}%"></b></div>'
                   f'<span class="dv">{dial["dial"][k]:.2f}</span><span class="di">{esc(dial["dial_interpretation"][k])}</span></div>' for k in ("meme", "stocks", "crypto"))
    ct = dial["crypto_targets"]
    tg = ", ".join(f"{k} {v*100:.0f}%" for k, v in ct["weights"].items()) or "cash (no positive 12m→1m momentum)"
    bars += f'<div class="sub">crypto targets: {esc(tg)} · degraded: {esc(", ".join(deg) or "none")} · dial {dial["date"]}</div>'

act_html = "".join(f'<div class="ln"><span class="t">{esc(t[5:16])}</span> <span class="tag">{esc(m.split("]")[0])}]</span>{esc(m.split("]",1)[1])}</div>' for t, m in activity[:60]) \
    or '<div class="empty">No activity logged yet.</div>'
bot_html = "".join(f'<div class="bot" style="--i:{n}">{blob(v, s)}<div class="bn">{nm}</div><div class="st s-{s.replace(" ", "")}">{s}</div><div class="bd">{esc(d)}</div></div>'
                   for n, (nm, v, s, d) in enumerate(bots))
pos_rows = "".join(f'<tr><td>{esc(s.replace(" (SIMULATED)", ""))}</td><td>{"meme SIM" if "SIMULATED" in s else "desk paper"}</td><td>{h["qty"]:.6f}</td><td>{money(h["market_value"])}</td><td class="{"up" if h["unrealized"]>=0 else "down"}">{h["unrealized"]:+.2f}</td></tr>' for s, h in holdings.items())
pos_rows += "".join(f'<tr class="acct"><td>{esc(p["symbol"])}</td><td>{_sleeve(p["symbol"])} (acct)</td><td>{p["qty"]:.6f}</td><td>{money(p["mv"])}</td><td>{p["upl"]:+.2f}</td></tr>' for p in (positions or []) if p["symbol"] not in holdings)
ord_rows = "".join(f'<tr><td>{o.submitted_at.astimezone(BER).strftime("%d %b %H:%M")}</td><td>{esc(str(o.side.value).upper())} {esc(o.symbol)}</td>'
                   f'<td>{("$"+str(o.notional)) if o.notional else (o.qty or "")}</td><td>{esc(str(o.status.value))}{" @ "+str(o.filled_avg_price) if o.filled_avg_price else ""}</td></tr>' for o in (orders or []))
foot = (f'POSITION LIVE · {", ".join(holdings)} · live P&amp;L {bank_state["unrealized"]:+.2f}' if holdings else "FLAT · AGENTS SCANNING")
acct_line = (f'Alpaca paper acct {esc(acct["status"])} · equity {money(acct["equity"])} · cash {money(acct["cash"])} · day '
             + (f'{(acct["equity"]/acct["last_equity"]-1)*100:+.2f}%' if acct["last_equity"] else "n/a") + ' · sizes TREND 35% / STOCKS 50%×dial / CRYPTO 15%×dial' + (' · KILL SWITCH FIRED today' if kill_today else '')) if acct else "Alpaca paper account unreachable"
gen = NOW.astimezone(BER).strftime("%Y-%m-%d %H:%M") + " Berlin"
err_html = "".join(f'<div class="err">{esc(e)}</div>' for e in errors)
trades = bank_state["closed_trades"] if bank_state else []

CSS = """
:root{--a:#5b4bdb;--a2:#4c3fb5;--glow:rgba(91,75,219,.45);--card:#1c1c1e;--line:#3a3a3c;--tx:#f2f2f7;--mut:#8e8e93;--down:#b98a8a}
*{box-sizing:border-box}html,body{margin:0}
body{font-family:"JetBrains Mono","Space Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;color:var(--tx);
background:linear-gradient(165deg,#3a3a3c 0%,#2c2c2e 100%);background-attachment:fixed;min-height:100vh;font-size:13px;
padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
.wrap{max-width:1240px;margin:0 auto;padding:20px 16px 40px}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px;flex-wrap:wrap}
.logo{font-size:20px;font-weight:800;letter-spacing:3px}.subt{font-size:10.5px;letter-spacing:3px;color:var(--mut)}
.rt{display:flex;align-items:center;gap:12px}.gen{color:var(--mut);font-size:11px}
.pill{display:inline-flex;align-items:center;gap:8px;background:var(--a);color:#fff;font-weight:800;font-size:11px;letter-spacing:2px;padding:6px 13px;border-radius:999px;box-shadow:0 0 18px var(--glow)}
.pill i{width:7px;height:7px;border-radius:50%;background:#fff;animation:pd 1.6s infinite}
@keyframes pd{0%{box-shadow:0 0 0 0 rgba(255,255,255,.8)}70%{box-shadow:0 0 0 7px rgba(255,255,255,0)}100%{box-shadow:0 0 0 0 rgba(255,255,255,0)}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.lbl{font-size:10.5px;letter-spacing:2px;color:var(--mut);margin-bottom:8px;font-weight:700}
.hero{display:flex;align-items:baseline;gap:18px;flex-wrap:wrap;margin:2px 2px 16px}
.hero .h{font-size:44px;font-weight:800;letter-spacing:-1px}.hero .h em{font-style:normal;color:var(--a);text-shadow:0 0 22px var(--glow)}
.hero .p{font-size:15px}.up{color:#8f84ff}.down{color:var(--down)}.flat{color:var(--mut)}
.grid{display:grid;gap:14px}.stats{grid-template-columns:1fr 1fr 1fr 1.6fr}.main{grid-template-columns:1.9fr 1fr;margin-top:14px}.bot3{grid-template-columns:1fr 1.4fr 1fr;margin-top:14px}
.big{font-size:26px;font-weight:800}.sub{font-size:11px;color:var(--mut);margin-top:6px}
.wr{display:flex;align-items:center;gap:12px}.ringt{font:800 15px ui-monospace,Menlo,monospace;fill:#fff}
.ringarc{filter:drop-shadow(0 0 4px rgba(91,75,219,.8))}
.dl{display:grid;grid-template-columns:62px 1fr 38px auto;align-items:center;gap:8px;margin:5px 0;font-size:11.5px}
.bar{height:7px;background:#2c2c2e;border-radius:9px;overflow:hidden}.bar b{display:block;height:100%;background:linear-gradient(90deg,var(--a2),var(--a));border-radius:9px;box-shadow:0 0 10px var(--glow)}
.dv{font-weight:800}.di{color:var(--mut);font-size:10.5px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{font-size:10.5px;padding:4px 9px;border-radius:999px;white-space:nowrap}.chip i{font-style:normal;opacity:.7;margin-left:6px}
.chip.on{background:rgba(91,75,219,.22);border:1px solid var(--a);color:#cfc9ff}.chip.off{border:1px solid #5a4646;color:var(--down);background:rgba(185,138,138,.07)}
.chart{width:100%;height:auto;display:block}.ax{font:10px ui-monospace,Menlo,monospace;fill:var(--mut);letter-spacing:1px}
.tip{font:800 12px ui-monospace,Menlo,monospace;fill:#fff}.bt{font:700 10px ui-monospace,Menlo,monospace;fill:#fff}
.draw{stroke-dasharray:1;stroke-dashoffset:1;animation:dr 1.8s ease-out forwards}@keyframes dr{to{stroke-dashoffset:0}}
.area{opacity:0;animation:fi 1.2s .9s forwards}@keyframes fi{to{opacity:1}}
.pulse{transform-box:fill-box;transform-origin:center;animation:pu 1.8s infinite}@keyframes pu{0%{transform:scale(.6);opacity:.7}100%{transform:scale(2.2);opacity:0}}
.cfoot{margin-top:10px;padding-top:10px;border-top:1px solid var(--line);font-size:11.5px;letter-spacing:1.5px;color:#cfc9ff}
.log{max-height:330px;overflow:auto;font-size:11px;line-height:1.6}.ln{padding:3px 0;border-bottom:1px dashed #2c2c2e;word-break:break-word}
.t{color:#636366}.tag{color:#a59cff;font-weight:700}
.pipe{margin-top:18px}.ph{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:6px;margin:0 2px 10px}
.ph b{letter-spacing:2px;font-size:12px}.ph span{color:var(--mut);font-size:11px}
.bots{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px}
.bot{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 8px;text-align:center;position:relative;
animation:hl 8s infinite;animation-delay:calc(var(--i) * 1s)}
.bot .blob{animation:bo 8s infinite;animation-delay:calc(var(--i) * 1s)}.blob.dim{opacity:.45}
@keyframes hl{0%,12.4%{border-color:#fff;box-shadow:0 0 16px var(--glow)}12.5%,100%{border-color:var(--line);box-shadow:none}}
@keyframes bo{0%{transform:translateY(0)}3%{transform:translateY(-7px)}6%{transform:translateY(0)}9%{transform:translateY(-3px)}12%,100%{transform:translateY(0)}}
.bn{font-weight:800;letter-spacing:2px;margin-top:4px}.bd{font-size:10px;color:var(--mut);margin-top:5px}
.st{display:inline-block;font-size:9.5px;letter-spacing:1px;padding:2px 8px;border-radius:999px;margin-top:5px;text-transform:uppercase}
.s-active{background:var(--a);color:#fff}.s-idle{border:1px solid var(--a);color:#cfc9ff}.s-notsetup{border:1px solid var(--line);color:#636366}.s-paused{border:1px dashed var(--a);color:#8e8e93}.s-degraded{border:1px solid #8a5a5a;color:var(--down)}.s-halted{background:#5a3a3a;color:#fff}
table{width:100%;border-collapse:collapse;font-size:11.5px}td,th{padding:6px 4px;border-bottom:1px solid #2c2c2e;text-align:left}th{color:var(--mut);font-size:10px;letter-spacing:1.5px;font-weight:600}
tr.acct td{color:var(--mut)}.kv{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-bottom:1px solid #2c2c2e;font-size:11.5px}.kv span{color:var(--mut)}
.honest{border-color:var(--a2)}.honest p{margin:0;line-height:1.6;color:#d1d1d6;font-size:12px}
.empty{color:#636366;font-size:11.5px;padding:14px 0;text-align:center}.err{border:1px solid #8a5a5a;color:var(--down);border-radius:10px;padding:8px 12px;font-size:11px;margin-bottom:10px}
.foot{color:#636366;font-size:10.5px;text-align:center;margin-top:20px}.mt{margin-top:14px}
.rchips{display:flex;flex-wrap:wrap;gap:6px}.rchip{font-size:10.5px;border:1px solid var(--line);border-radius:999px;padding:3px 9px;color:#d1d1d6}.rchip b{color:#a59cff;margin-left:4px}
details summary{cursor:pointer;color:#cfc9ff;font-size:11.5px;letter-spacing:1px;padding:6px 0}details summary::marker{color:var(--a)}
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch;max-height:520px;overflow-y:auto}.rt{min-width:760px}.rt td{vertical-align:top;font-size:11px}
.rt a{color:#a59cff;text-decoration:none;font-weight:700}.vn{color:#636366;font-size:9.5px;margin-top:2px}.why{color:#d1d1d6;min-width:190px}
.vd{display:inline-block;font-size:9px;padding:1px 6px;border-radius:999px;margin-right:4px;letter-spacing:1px}.vd-scan{border:1px solid #5a4646;color:var(--down)}
.vd-judge{border:1px solid var(--a);color:#cfc9ff}.vd-watch{border:1px solid #c9a227;color:#e8cf6a}.vd-pick{background:var(--a);color:#fff}
@media(max-width:1000px){.stats{grid-template-columns:1fr 1fr}.main,.bot3{grid-template-columns:1fr}}
@media(max-width:600px){.wrap{padding:14px 12px 30px}.stats{grid-template-columns:1fr}.hero .h{font-size:34px}
.bots{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:6px}.bot{flex:0 0 132px;scroll-snap-align:start}}
@media(prefers-reduced-motion:reduce){*{animation:none!important}.draw{stroke-dashoffset:0}.area{opacity:1}}
"""
JS = """(function(){var els=[].slice.call(document.querySelectorAll('.cnt'));if(!els.length)return;var t0=Date.now(),D=1100;
function fm(e,x){var f=e.dataset.f,s=Math.abs(x).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
if(f=='money')return'$'+s;if(f=='smoney')return(x<0?'-':'+')+'$'+s;if(f=='spct')return(x<0?'-':'+')+s+'%';return s}
var id=setInterval(function(){var p=Math.min(1,(Date.now()-t0)/D),k=1-Math.pow(1-p,3);
els.forEach(function(e){e.textContent=fm(e,parseFloat(e.dataset.v)*k)});if(p>=1)clearInterval(id)},30)})();"""

CSS2 = """:root{--g:#30d158;--r:#ff453a;--gbg:rgba(48,209,88,.10);--rbg:rgba(255,69,58,.10)}
body.v2{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-size:15px;background:#161618;-webkit-text-size-adjust:100%}
.v2 .rt,.v2 .rt2,.v2 .log,.v2 .tscroll{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
.wrap2{max-width:1180px;margin:0 auto;padding:12px 12px 40px}
.pos{color:var(--g)!important}.neg{color:var(--r)!important}.zero{color:var(--mut)}
.hdr-top{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;flex-wrap:wrap}
.logo2{font-size:20px;font-weight:800}.paper{font-size:11px;background:var(--a);color:#fff;border-radius:999px;padding:2px 8px;vertical-align:middle;letter-spacing:1px}
.upd{color:var(--mut);font-size:13px;margin-top:2px}
.tot{text-align:right}.tot span{display:block;color:var(--mut);font-size:12px}.tot>b{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums}.tot i{display:block;font-style:normal;font-size:13px;color:var(--mut)}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.bdg{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:700;padding:6px 11px;border-radius:999px}
.bdg i{width:9px;height:9px;border-radius:50%}
.bdg.ok{background:var(--gbg);color:var(--g);border:1px solid rgba(48,209,88,.5)}.bdg.ok i{background:var(--g)}
.bdg.bad{background:var(--r);color:#fff}.bdg.bad i{background:#fff}
.bdg.warn{background:rgba(255,214,10,.1);color:#ffd60a;border:1px solid rgba(255,214,10,.5)}.bdg.warn i{background:#ffd60a}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px}
.tt{font-size:12px;font-weight:800;letter-spacing:1px;color:#cfc9ff}.tt i{display:block;font-style:normal;font-weight:400;letter-spacing:0;color:var(--mut);font-size:11.5px}
.te{font-size:28px;font-weight:800;margin:4px 0 6px;font-variant-numeric:tabular-nums}
.tr{display:grid;grid-template-columns:1fr 1fr;gap:8px}.tr span{display:block;color:var(--mut);font-size:12px}.tr b{font-size:17px;font-variant-numeric:tabular-nums}.tr i{display:block;font-style:normal;font-size:12.5px;color:var(--mut)}
.tf{font-size:12px;color:var(--mut);margin-top:8px}
.livebar{color:var(--mut);font-size:12.5px;margin:10px 2px}.livebar .live{font-size:12.5px}
.card2{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin-top:12px}
.sech{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:4px 12px;margin-bottom:6px}
.sech h2{margin:0;font-size:22px;font-weight:800}.secs{font-size:13.5px;color:var(--mut)}
.badge-n{font-size:14px;background:var(--a);color:#fff;border-radius:999px;padding:1px 9px;vertical-align:middle}
.sl{margin-top:12px}.slh{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:5px;margin-bottom:8px}
.slh b{font-size:15px;letter-spacing:1px}.slh span{color:var(--mut);font-size:12px;flex:1}.slh em{font-style:normal;font-size:12.5px;color:var(--mut)}.slh em.cnt1{color:#fff;font-weight:700}
.none{color:var(--mut);font-size:14px;padding:2px 2px 4px}
.tcs{display:grid;grid-template-columns:1fr;gap:10px}
.tc{border-radius:14px;padding:12px;border:1px solid var(--line);border-left:5px solid var(--mut);background:#232326}
.tc.tc-pos{border-left-color:var(--g);background:linear-gradient(90deg,rgba(48,209,88,.08),#232326 60%)}.tc.tc-neg{border-left-color:var(--r);background:linear-gradient(90deg,rgba(255,69,58,.08),#232326 60%)}
.tc-h{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.tn{font-size:19px;font-weight:800;color:#fff;text-decoration:none;word-break:break-word}a.tn{border-bottom:1px dotted #8e8e93}
.lead{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#a59cff;border:1px solid #4c3fb5;border-radius:6px;padding:1px 5px;white-space:nowrap}
.tsl{color:var(--mut);font-size:12.5px;margin-top:3px}.tsl a{color:#a59cff;text-decoration:none}
.tc-p{text-align:right;white-space:nowrap}.pb{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}.pp{font-size:16px;font-weight:700}
.tc-g{display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-top:10px}
.kv2 span{display:block;color:var(--mut);font-size:11.5px}.kv2 b{font-size:14.5px;font-weight:600;font-variant-numeric:tabular-nums;word-break:break-word}.kv2 i,.tc-x i{font-style:normal;color:var(--mut);font-weight:400;font-size:12px}
.tc-x{margin-top:10px;padding-top:8px;border-top:1px dashed var(--line);display:grid;gap:6px;font-size:14px}.tc-x span{display:block;color:var(--mut);font-size:11.5px}
.cr{padding:9px 2px 9px 10px;border-bottom:1px solid #2c2c2e;border-left:4px solid var(--mut)}.cr.cr-pos{border-left-color:var(--g)}.cr.cr-neg{border-left-color:var(--r)}
.cr1{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}.cr1 .tn{font-size:16px}.crp{margin-left:auto;font-size:17px;font-variant-numeric:tabular-nums;white-space:nowrap}.crp i{font-style:normal;font-size:13px}
.cr2{color:var(--mut);font-size:12.5px;margin-top:3px;font-variant-numeric:tabular-nums}
.tag2{font-size:10.5px;letter-spacing:1px;border:1px solid var(--line);border-radius:999px;padding:1px 7px;color:#d1d1d6}
details.more summary{font-size:14px;padding:10px 2px}
.more2{margin-top:18px}.more2>h3{font-size:13px;letter-spacing:2px;color:var(--mut);margin:0 2px 6px;font-weight:700}
details.sec{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:8px}
details.sec>summary{letter-spacing:0;font-size:15px;font-weight:700;color:#e5e5ea;padding:13px 14px;list-style:none;display:flex;justify-content:space-between;gap:8px}
details.sec>summary::-webkit-details-marker{display:none}details.sec>summary:after{content:"▸";color:var(--a)}details.sec[open]>summary:after{content:"▾"}
details.sec>summary .sm{font-weight:400;color:var(--mut);font-size:12.5px;margin-left:auto;text-align:right}
details.sec>.body{padding:0 14px 14px}
.rt2{width:100%;font-size:12px}.v2 .bots{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr))}
@media(min-width:760px){.tcs{grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}.te{font-size:32px}}
@media(max-width:560px){.tiles{gap:8px}.tile{padding:10px}.te{font-size:21px;margin:2px 0 4px}.tt i{display:none}.tr{grid-template-columns:1fr;gap:3px}.tr div{display:flex;align-items:baseline;gap:5px}.tr span{flex:1;font-size:12px}.tr b{font-size:15px}.tr i{font-size:11.5px}.tf{font-size:11px;margin-top:5px}.hdr-top{display:block}.tot{text-align:left;margin-top:6px}.tot span{display:inline;margin-right:6px}.tot>b{font-size:18px}.tot i{font-size:12.5px}.logo2{font-size:18px}.badges{margin:8px 0;gap:5px}.bdg{font-size:12px;padding:5px 9px}.sech h2{font-size:20px}.card2{padding:12px}.wrap2{padding:10px 10px 30px}.v2 .bots{display:flex;overflow-x:auto}.v2 .bot{flex:0 0 132px}}
@media(max-width:360px){.tc-g{grid-template-columns:1fr}.pb{font-size:21px}}
"""
CSS3 = """.tc[data-ck]{cursor:pointer;-webkit-tap-highlight-color:rgba(91,75,219,.15)}.tc.open{grid-column:1/-1}
.chint{margin-top:9px;font-size:13px;color:#a59cff;font-weight:600}.chint .b{display:none}.tc.open .chint .a{display:none}.tc.open .chint .b{display:inline}
.tc-chart:empty{display:none}.tc-chart{cursor:default;margin:8px -4px 0}
.chbox{border-top:1px dashed var(--line);padding-top:8px}
.tfr{display:flex;gap:6px;margin-bottom:8px}.tfb{flex:1;font:600 14px -apple-system,system-ui,sans-serif;color:#d1d1d6;background:#2c2c2e;border:1px solid var(--line);border-radius:9px;padding:8px 0}
.tfb.on{background:var(--a);border-color:var(--a);color:#fff}
.chc{width:100%;border-radius:10px;overflow:hidden}
.cf{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;margin-top:10px}.cf span{display:block;color:var(--mut);font-size:11.5px}.cf b{font-size:15px;font-variant-numeric:tabular-nums}.cf i{display:block;font-style:normal;color:var(--mut);font-size:11.5px}
.cl{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.cl a,.lvb{font:600 14px -apple-system,system-ui,sans-serif;color:#cfc9ff;background:#2c2c2e;border:1px solid var(--line);border-radius:9px;padding:9px 12px;text-decoration:none}
.lvb{color:#fff;background:#3a2f9e;border-color:var(--a)}
.lvf iframe{width:100%;height:440px;border:0;border-radius:10px;margin-top:10px;background:#000}
.csrc{color:#636366;font-size:11px;margin-top:8px}
.clh{font-size:12px;letter-spacing:1px;color:var(--mut);font-weight:700;margin:6px 0}.lvf iframe{width:100%;height:400px;border:0;border-radius:10px;background:#000;display:block}
@media(min-width:760px){.lvf iframe{height:480px}}
.eqs{margin-top:12px;padding:12px}.eqh{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap}
.eqv{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums}.eqd{font-size:14px;font-weight:700}.eqtt{font-size:12px;color:var(--mut);min-height:16px}
.seg{display:flex;gap:4px;background:#2c2c2e;border-radius:9px;padding:3px}.seg button{font:600 13px -apple-system,system-ui,sans-serif;color:#d1d1d6;background:none;border:0;border-radius:7px;padding:6px 10px}
.seg button.on{background:var(--a);color:#fff}.eqr{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;justify-content:space-between}
#eqc{width:100%;height:190px;margin-top:8px}.eqn{font-size:11.5px;color:var(--mut);margin-top:6px}
.tcs{grid-template-columns:minmax(0,1fr)}.tc{min-width:0}.tc-chart,.chbox,.chc,.lvf{min-width:0;max-width:100%;overflow:hidden}
@media(min-width:760px){.tcs{grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}}
"""
CHART_JS = r"""(function(){
var K='desk_chart_v1',st={};try{st=JSON.parse(sessionStorage.getItem(K)||'{}')}catch(e){}
function save(){try{sessionStorage.setItem(K,JSON.stringify(st))}catch(e){}}
var D=null,CH={};try{D=JSON.parse(document.getElementById('embedded').textContent)}catch(e){}
try{CH=(JSON.parse((document.getElementById('charts-embedded')||{}).textContent||'{}').charts)||{}}catch(e){}
var busy=false;function pull(cb){if(location.protocol==='file:'&&Object.keys(CH).length){cb&&cb();return}if(busy)return;busy=true;
 fetch('charts.json'+(location.search?location.search+'&':'?')+'_='+Date.now(),{cache:'no-store',credentials:'same-origin'}).then(function(r){if(!r.ok)throw 0;return r.json()})
 .then(function(d){CH=d.charts||{};busy=false;cb&&cb()}).catch(function(){busy=false;cb&&cb()})}
var live={},TFN={'1m':'1 Min','5m':'5 Min','1h':'1 Std','1T':'1 Tag'},TFS={'1m':60,'5m':300,'1h':3600,'1T':86400};
function de(x,d){return (x==null||isNaN(x))?'—':Number(x).toLocaleString('de-DE',{minimumFractionDigits:d,maximumFractionDigits:d})}
function usdK(x){if(x==null)return'—';x=+x;return x>=1e6?de(x/1e6,2)+' Mio $':x>=1e3?de(x/1e3,1)+' Tsd $':de(x,0)+' $'}
function age(h){if(h==null)return'—';return h<1?Math.round(h*60)+' Min':h<48?de(h,1)+' Std':de(h/24,1)+' Tage'}
function pc(x){return x==null?'—':'<b class="'+(x>0?'pos':x<0?'neg':'')+'">'+(x>0?'+':'')+de(x,1)+' %</b>'}
function cfg(ck){return CH[ck]}
function facts(c){var f=c.facts||{},h=f.holders,l=c.links||{},s='';
 if(c.kind==='meme'){s+='<div class="cf"><div><span>Market Cap</span><b>'+usdK(f.mcap)+'</b></div><div><span>Liquidität</span><b>'+usdK(f.liq)+'</b></div>'+
  '<div><span>Volumen 24h</span><b>'+usdK(f.vol24)+'</b></div><div><span>Alter</span><b>'+age(f.age_h)+'</b></div>'+
  '<div><span>Holder (Top 10 ohne Pool)</span><b>'+(h?de(h.top10_pct,1)+' %':'—')+'</b><i>'+(h&&h.largest_pct!=null?'größter '+de(h.largest_pct,1)+' %':'RugCheck-Cache')+'</i></div>'+
  '<div><span>Kurs 1h / 24h</span>'+pc(f.chg_h1)+' / '+pc(f.chg_h24)+'</div></div>';
  s+='<div class="cl"><a href="'+l.dex+'" target="_blank" rel="noopener">DexScreener ↗</a>'+(l.pump?'<a href="'+l.pump+'" target="_blank" rel="noopener">pump.fun ↗</a>':'')+
   '</div>';}
 else s+='<div class="cl"><a href="'+l.ext+'" target="_blank" rel="noopener">Externer Chart ↗</a></div>';
 return s+'<div class="csrc">Quelle: '+(c.src||'')+' · Zeiten Berlin</div>';}
function snap(t,tf,bars){var s=TFS[tf],k=Math.floor(t/s)*s;if(!bars.length)return null;if(k<bars[0][0])return null;
 for(var i=bars.length-1;i>=0;i--){if(bars[i][0]<=k)return bars[i][0]}return null}
function paint(L){var c=cfg(L.ck);if(!c)return;var tf=L.tf,bars=(c.tf||{})[tf]||[];
 L.series.setData(bars.map(function(b){return{time:b[0],open:b[1],high:b[2],low:b[3],close:b[4]}}));
 (L.pl||[]).forEach(function(p){L.series.removePriceLine(p)});L.pl=[];
 function line(p,col,ttl,sty){if(p==null||!isFinite(p))return;L.pl.push(L.series.createPriceLine({price:p,color:col,lineWidth:sty===0?2:1,lineStyle:sty,axisLabelVisible:true,title:ttl}))}
 if(c.entry&&c.entry.p)line(c.entry.p,'#0a84ff','Einstieg',0);
 (c.lines||[]).forEach(function(x){line(x.p,x.c,x.t,2)});
 var mk=[];if(c.entry&&c.entry.t){var t=snap(c.entry.t,tf,bars);if(t!=null)mk.push({time:t,position:'belowBar',color:'#0a84ff',shape:'arrowUp',text:'Kauf'})}
 (c.sells||[]).forEach(function(s){var t=snap(s.t,tf,bars);if(t!=null)mk.push({time:t,position:'aboveBar',color:'#ffd60a',shape:'arrowDown',text:s.txt})});
 mk.sort(function(a,b){return a.time-b.time});L.series.setMarkers(mk);
 L.box.querySelectorAll('.tfb').forEach(function(b){b.classList.toggle('on',b.dataset.tf===tf)});
 L.box.querySelector('.cfx').innerHTML=facts(c);if(!bars.length)L.box.querySelector('.cnone').style.display='block';else L.box.querySelector('.cnone').style.display='none'}
function build(ck,holder){var c=cfg(ck);holder.innerHTML='';
 if(!c||!window.LightweightCharts){holder.innerHTML='<div class="none">Keine Chartdaten verfügbar.</div>';return}
 var tf=st[ck]&&c.tf[st[ck]]?st[ck]:(c.tf[c.default]?c.default:(c.order.filter(function(x){return c.tf[x]})[0]||c.default));
 var box=document.createElement('div');box.className='chbox';
 box.innerHTML='<div class="tfr">'+c.order.filter(function(x){return c.tf[x]}).map(function(x){return'<button type="button" class="tfb" data-tf="'+x+'">'+TFN[x]+'</button>'}).join('')+
  '</div><div class="chc"></div><div class="cnone none" style="display:none">Für diesen Zeitraum noch keine Kerzen.</div><div class="cfx"></div>';
 if(c.links&&c.links.embed)box.insertAdjacentHTML('afterbegin','<div class="clh">Live-Chart · '+c.links.embed_name+'</div><div class="lvf"><iframe src="'+c.links.embed+'" referrerpolicy="no-referrer" allowfullscreen title="Live-Chart"></iframe></div><div class="clh">Mein Einstieg · Einstieg / Stop / TP</div>');
 holder.appendChild(box);var el=box.querySelector('.chc');
 var pr=c.prec||4,ch=LightweightCharts.createChart(el,{width:el.clientWidth||340,height:Math.min(320,Math.max(240,Math.round(window.innerHeight*0.36))),
  layout:{background:{type:'solid',color:'#17171a'},textColor:'#c7c7cc',fontSize:11},grid:{vertLines:{color:'#26262a'},horzLines:{color:'#26262a'}},
  rightPriceScale:{borderColor:'#3a3a3c',scaleMargins:{top:0.12,bottom:0.08}},timeScale:{borderColor:'#3a3a3c',timeVisible:true,secondsVisible:false,rightOffset:3},
  crosshair:{mode:0},handleScroll:{vertTouchDrag:false},localization:{locale:'de-DE',priceFormatter:function(p){return de(p,pr)}}});
 var s=ch.addCandlestickSeries({upColor:'#30d158',downColor:'#ff453a',borderVisible:false,wickUpColor:'#30d158',wickDownColor:'#ff453a',
  priceFormat:{type:'price',precision:pr,minMove:Math.pow(10,-pr)}});
 var L={ck:ck,tf:tf,chart:ch,series:s,box:box,pl:[]};live[ck]=L;paint(L);ch.timeScale().fitContent();
 if(window.ResizeObserver){L.ro=new ResizeObserver(function(){if(el.clientWidth)ch.applyOptions({width:el.clientWidth})});L.ro.observe(el)}
 box.addEventListener('click',function(e){var b=e.target.closest('.tfb');if(b){L.tf=b.dataset.tf;st[ck]=L.tf;save();paint(L);ch.timeScale().fitContent();return}
  });
 ['touchstart','mousedown','wheel'].forEach(function(ev){el.addEventListener(ev,function(){window.__deskTouch=Date.now()},{passive:true})})}
function destroy(ck){var L=live[ck];if(!L)return;try{L.ro&&L.ro.disconnect();L.chart.remove()}catch(e){}delete live[ck]}
function card(ck){return document.querySelector('.tc[data-ck="'+ck.replace(/"/g,'')+'"]')}
function openCard(c,ck){c.classList.add('open');var h=c.querySelector('.tc-chart');if(!h)return;
 if(live[ck]){if(live[ck].box.parentNode!==h){h.innerHTML='';h.appendChild(live[ck].box)}paint(live[ck])}
 else if(cfg(ck))build(ck,h);else{h.innerHTML='<div class="none">Chart lädt …</div>';pull(function(){if(c.classList.contains('open')&&!live[ck])build(ck,h)})}}
document.addEventListener('click',function(e){var c=e.target.closest('.tc[data-ck]');if(!c||e.target.closest('a,button,.tc-chart'))return;
 var ck=c.dataset.ck;if(c.classList.contains('open')){c.classList.remove('open');destroy(ck);c.querySelector('.tc-chart').innerHTML='';delete st[ck];save()}
 else{st[ck]=st[ck]||'';save();openCard(c,ck)}});
window.deskChartOpen=function(){return Object.keys(live).length>0};
window.deskSwap=function(el,html){if(!Object.keys(live).length)return false;var t=document.createElement('div');t.innerHTML=html;
 function cks(r){return [].map.call(r.querySelectorAll('.tc[data-ck]'),function(x){return x.dataset.ck}).join('|')}
 if(cks(t)!==cks(el))return false;
 [].forEach.call(el.querySelectorAll('.tc[data-ck]'),function(oc){var nc=t.querySelector('.tc[data-ck="'+oc.dataset.ck+'"]'),ch=oc.querySelector('.tc-chart');
  [].slice.call(oc.childNodes).forEach(function(n){if(n!==ch)oc.removeChild(n)});
  [].slice.call(nc.childNodes).forEach(function(n){if(!(n.classList&&n.classList.contains('tc-chart')))oc.insertBefore(n,ch)});
  oc.className=nc.className+(oc.classList.contains('open')?' open':'')});
 ['.sech','.slh','.none'].forEach(function(sel){var a=el.querySelectorAll(sel),b=t.querySelectorAll(sel);if(a.length===b.length)for(var i=0;i<a.length;i++)if(a[i].innerHTML!==b[i].innerHTML)a[i].innerHTML=b[i].innerHTML});
 return true};
window.deskPre=function(){};   // nothing to detach: deskSwap patches open cards in place; after a full swap deskPost re-attaches the kept chart box
window.deskPost=function(el,d){if(d)D=d;Object.keys(st).forEach(function(ck){var c=card(ck);if(c)openCard(c,ck);else{destroy(ck);delete st[ck]}});save();
 if(Object.keys(live).length)pull(function(){Object.keys(live).forEach(function(ck){paint(live[ck])})})};
Object.keys(st).forEach(function(ck){var c=card(ck);if(c)openCard(c,ck);else delete st[ck]});save();
if(Object.keys(st).length)pull(function(){Object.keys(st).forEach(function(ck){var c=card(ck);if(c)openCard(c,ck)})});
})();
"""
EQ_JS = r"""(function(){
var K='desk_eq_v1',st={s:'meme',r:'today',u:'usd'};try{var o=JSON.parse(sessionStorage.getItem(K)||'{}');for(var k in o)st[k]=o[k]}catch(e){}
function save(){try{sessionStorage.setItem(K,JSON.stringify(st))}catch(e){}}
var D=null;try{D=JSON.parse(document.getElementById('embedded').textContent)}catch(e){}
var el=document.getElementById('eqc');if(!el||!window.LightweightCharts)return;
function de(x,d){return Number(x).toLocaleString('de-DE',{minimumFractionDigits:d,maximumFractionDigits:d})}
function sg(x,d,u){return (x>0?'+':x<0?'−':'±')+de(Math.abs(x),d)+u}
var ch=LightweightCharts.createChart(el,{width:el.clientWidth||340,height:el.clientHeight||190,layout:{background:{type:'solid',color:'transparent'},textColor:'#aeaeb2',fontSize:12},
 grid:{vertLines:{visible:false},horzLines:{color:'#2a2a2e'}},rightPriceScale:{borderVisible:false,scaleMargins:{top:0.15,bottom:0.1}},
 timeScale:{borderVisible:false,timeVisible:true,secondsVisible:false,fixLeftEdge:true,fixRightEdge:true},crosshair:{mode:0,vertLine:{labelVisible:false},horzLine:{labelVisible:false}},
 handleScroll:false,handleScale:false,localization:{locale:'de-DE'}});
var ser=null,pl=null;
function sleeve(){var e=(D&&D.equity)||{};return e[st.s]||{pts:[],start:0}}
function draw(){var e=(D&&D.equity)||{},s=sleeve(),start=s.start||0,pts=s.pts||[],t0=st.r==='today'?e.today0:st.r==='7d'?e.now-7*86400:0;
 var p=pts.filter(function(x){return x[0]>=t0});if(!p.length)p=pts.slice(-1);var pct=st.u==='pct';
 var conv=function(v){return pct?(v/start-1)*100:v},base=pct?0:start,dec=pct?2:(start>=10000?0:2);
 if(ser)ch.removeSeries(ser);
 ser=ch.addBaselineSeries({baseValue:{type:'price',price:base},lineWidth:2,topLineColor:'#30d158',topFillColor1:'rgba(48,209,88,.28)',topFillColor2:'rgba(48,209,88,.02)',
  bottomLineColor:'#ff453a',bottomFillColor1:'rgba(255,69,58,.02)',bottomFillColor2:'rgba(255,69,58,.28)',priceLineVisible:false,lastValueVisible:true,
  priceFormat:{type:'custom',formatter:function(v){return pct?de(v,2)+' %':de(v,dec)+' $'},minMove:pct?0.01:(dec?0.01:1)}});
 var m={};p.forEach(function(x){m[x[0]]=conv(x[1])});var data=Object.keys(m).map(Number).sort(function(a,b){return a-b}).map(function(t){return{time:t,value:m[t]}});ser.setData(data);
 ser.createPriceLine({price:base,color:'#8e8e93',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'Start'});
 var mk=[];(s.markers||[]).forEach(function(m){if(m.t<(data[0]||{}).time)return;var tt=null;for(var i=data.length-1;i>=0;i--)if(data[i].time<=m.t){tt=data[i].time;break}
  if(tt!=null)mk.push({time:tt,position:m.up?'belowBar':'aboveBar',color:m.c,shape:m.shape||(m.up?'arrowUp':'arrowDown'),text:m.txt})});
 mk.sort(function(a,b){return a.time-b.time});ser.setMarkers(st.r==='today'||mk.length<=12?mk:[]);ch.timeScale().fitContent();
 var cur=pts.length?pts[pts.length-1][1]:start,first=p.length?p[0][1]:cur,dS=cur-start,dR=cur-first;
 document.getElementById('eqv').textContent=de(cur,start>=10000?2:2)+' $';
 var a=document.getElementById('eqd');a.className='eqd '+(dS>0?'pos':dS<0?'neg':'zero');a.textContent='seit Start '+sg(dS,2,' $')+' ('+sg(start?dS/start*100:0,2,' %')+')';
 var b=document.getElementById('eqz');b.className=(dR>0?'pos':dR<0?'neg':'zero');b.textContent=({today:'heute',"7d":'7 Tage',all:'gesamt'})[st.r]+' '+sg(dR,2,' $')+' ('+sg(first?dR/first*100:0,2,' %')+')';
 document.getElementById('eqtt').textContent='Antippen für Wert · Start '+de(start,start>=10000?0:2)+' $';
 document.querySelectorAll('#eqbox .seg button').forEach(function(x){x.classList.toggle('on',st[x.dataset.k]===x.dataset.v)})}
ch.subscribeCrosshairMove(function(pr){var tt=document.getElementById('eqtt');if(!pr||!pr.time||!ser){return}var v=pr.seriesData.get(ser);if(!v)return;
 var d=new Date(pr.time*1000),s=('0'+d.getUTCDate()).slice(-2)+'.'+('0'+(d.getUTCMonth()+1)).slice(-2)+'. '+('0'+d.getUTCHours()).slice(-2)+':'+('0'+d.getUTCMinutes()).slice(-2);
 tt.textContent=s+' · '+(st.u==='pct'?de(v.value,2)+' %':de(v.value,2)+' $')});
document.getElementById('eqbox').addEventListener('click',function(e){var b=e.target.closest('.seg button');if(!b)return;st[b.dataset.k]=b.dataset.v;save();draw()});
if(window.ResizeObserver)new ResizeObserver(function(){ch.applyOptions({width:el.clientWidth})}).observe(el);
['touchstart','mousedown'].forEach(function(ev){el.addEventListener(ev,function(){window.__deskTouch=Date.now()},{passive:true})});
var prev=window.deskPost;window.deskPost=function(x,d){if(prev)prev(x,d);if(d&&d.equity){D=d;draw()}};
draw();})();
"""
RELOAD_JS = r"""(function(){var t0=Date.now();setInterval(function(){if(document.hidden)return;if(window.deskChartOpen&&window.deskChartOpen())return;if(Date.now()-t0>=60000&&Date.now()-(window.__deskTouch||0)>30000)location.reload()},5000)})();"""
try: LW_JS = open(f"{DESK}/vendor/lightweight-charts-4.2.3.standalone.production.js").read().replace("</", "<\\/")
except Exception: LW_JS = ""
KEEP_JS = r"""(function(){try{var K='desk_open_v2',o=JSON.parse(sessionStorage.getItem(K)||'{}');
document.querySelectorAll('details.sec[id]').forEach(function(d){if(o[d.id])d.open=true;d.addEventListener('toggle',function(){o[d.id]=d.open;sessionStorage.setItem(K,JSON.stringify(o))})});
var y=sessionStorage.getItem(K+'_y');if(y)window.scrollTo(0,parseInt(y,10));
window.addEventListener('beforeunload',function(){sessionStorage.setItem(K+'_y',String(window.scrollY))});}catch(e){}})();"""
def smoney(x): return ("-" if x < 0 else "+") + f"${abs(x):,.2f}"
# ---------- fragments (re-rendered server side, swapped in place by the live page) ----------
cad = gate_next.split()[0].split("=")[1].replace("min", "") if gate_next.startswith("cadence=") else "—"
nxt_scan = fmt_ber(dt.datetime.fromisoformat(gate_next.split("next=")[1])) if "next=" in gate_next and "ended" not in gate_next else "schedule ended"
frag = {}
frag["errors"] = err_html
frag["hero"] = (f'<div class="h">{money(start)} → <em>{cnt(equity, "money", money(equity))}</em></div>'
                f'<div class="p {pc}">{cnt(pnl, "smoney", smoney(pnl))} ({cnt(pnl_pct, "spct", f"{pnl_pct:+.2f}%")})</div><div class="sub">since {esc(bank["started"])}</div>')
frag["stats"] = f"""
 <div class="card"><div class="lbl">BALANCE</div><div class="big">{cnt(equity, "money", money(equity))}</div><div class="sub">started at {money(start)} · cash {money(bank_state['cash'])}</div></div>
 <div class="card"><div class="lbl">TOTAL P&amp;L</div><div class="big {pc}">{cnt(pnl, "smoney", smoney(pnl))}</div>
  <div class="sub">{pnl_pct:+.2f}% · realized {bank_state['realized']:+.2f} · open {bank_state['unrealized']:+.2f}</div>
  <div class="kv"><span>MEME (pump.fun, simulated)</span><b>{meme_pnl:+.2f}</b></div><div class="kv"><span>ALPACA PAPER ACCT (trend/stocks/crypto, own book)</span><b>{(money(acct["equity"]) + " · " + f'{(acct["equity"]/acct["last_equity"]-1)*100:+.2f}% day') if acct and acct["last_equity"] else "n/a"}</b></div></div>
 <div class="card"><div class="lbl">WIN RATE</div><div class="wr">{ring(wins, losses)}<div class="sub">{wins} wins<br>{losses} losses{'' if wins+losses else '<br>no closed trades yet'}</div></div></div>
 <div class="card"><div class="lbl">QUANT DIAL</div>{bars}<div class="chips">{chips}</div></div>"""
frag["chart"] = f'<div class="lbl">BALANCE HISTORY</div>{chart(hist[-400:], trades)}<div class="cfoot">{foot}</div>'
frag["activity"] = f'<div class="lbl">ACTIVITY LOG</div><div class="log">{act_html}</div>'
frag["bots"] = bot_html
frag["rejects"] = f'<div class="lbl">SCAN REJECTS</div>{rej_html}'
frag["shadow"] = f'<div class="lbl">SHADOW TRADES · what the blocked candidates would have done (paper, virtual)</div>{shadow_html}'
try: _rv = open(f"{DESK}/reviews/weekly_latest.html").read(); _rvt = dt.datetime.fromtimestamp(os.path.getmtime(f"{DESK}/reviews/weekly_latest.html"), BER).strftime("%a %d %b %H:%M")
except Exception: _rv, _rvt = '<div class="empty">No weekly review yet (Sundays 20:00 Berlin).</div>', "—"
frag["review"] = f'<details><summary class="lbl">WEEKLY REVIEW · {_rvt} Berlin · win rate / avg R by hour, phase, narrative age · gate costs · add/cut</summary><div class="tscroll">{_rv}</div></details>'
frag["newpairs"] = f'<div class="lbl">NEW PAIRS · fresh pump.fun launches (paper)</div>{np_html}'
frag["schedule"] = f"""<div class="lbl">SCHEDULE</div>
  <div class="kv"><span>MEME CADENCE</span><b>{'ended' if cad in ('—','None') else 'every ' + esc(cad) + ' min'}</b></div>
  <div class="kv"><span>NEXT SCAN</span><b>{esc(nxt_scan)}</b></div>
  <div class="kv"><span>RISK POLL</span><b>{"5× per min (~12 s)" if risk_sched else "off"}</b></div>
  <div class="kv"><span>TREND + STOCKS 15:45 NY</span><b>{fmt_ber(nxt_run) if runner_sched or stocks_sched else 'not scheduled'}</b></div>
  <div class="kv"><span>CRYPTO 20:05 NY</span><b>{fmt_ber(nxt_cry) if crypto_sched else 'not scheduled'}</b></div>
  <div class="kv"><span>LISTS 07:30 NY</span><b>{fmt_ber(nxt_lists) if lists_sched else 'not scheduled'}</b></div>
  <div class="kv"><span>ACCT KILL SWITCH</span><b>{("FIRED today" if kill_today else "every 30 min") if kill_sched else "off"}{(" · last " + esc(str((alp["kill"] or {}).get("result", ""))[:24])) if alp["kill"] else ""}</b></div>
  <div class="kv"><span>JEV (Judge)</span><b>{"ON" if jev_on else "off — no key"}</b></div>
  <div class="kv"><span>QUANT 06:00 NY daily</span><b>{fmt_ber(nxt_dial) if dial_sched else 'not scheduled'}</b></div>
  <div class="kv"><span>DATA</span><b>rebuilt every 1 min · page polls 15 s</b></div>
  <div class="kv"><span>CRON</span><b>{'running' if cron_ok else 'NOT running'}</b></div>
  <div class="kv"><span>LAST TARGET</span><b>{esc(last_dry[1]) if last_dry else '—'}</b></div><div class="sub">{esc(last_dry[0]) if last_dry else ''}</div>"""
frag["positions"] = (f'<div class="lbl">POSITIONS</div>' + (('<table><tr><th>SYM</th><th>BOOK</th><th>QTY</th><th>VALUE</th><th>UPL</th></tr>' + pos_rows + '</table>') if pos_rows else '<div class="empty">No positions — desk is flat.</div>')
                     + '<div class="lbl mt">RECENT ORDERS</div>' + (('<table><tr><th>TIME</th><th>ORDER</th><th>SIZE</th><th>STATUS</th></tr>' + ord_rows + '</table>') if ord_rows else '<div class="empty">No orders yet.</div>')
                     + f'<div class="sub">{acct_line}</div>')
frag["gen"] = gen
frag["header"] = header_section; frag["open"] = open_section; frag["closed"] = closed_section
frag["control"] = control_html; frag["rejtrack"] = f'<div class="lbl">REJECT-TRACKER · Kursverlauf abgelehnter Coins (+1h/+6h/+24h)</div>{rejtrack_html}'
frag["research"] = research_html; frag["review_body"] = f'<div class="tscroll">{_rv}</div>'
frag["dial"] = f'<div class="wr">{ring(wins, losses)}<div class="sub">Gewinnquote gesamt: {wins} Gewinner · {losses} Verlierer</div></div><div class="lbl mt">QUANT DIAL</div>{bars}<div class="chips">{chips}</div>'
frag["s_chart"] = f"{len(hist)} Punkte"
frag["s_shadow"] = (f'{shadow_sum["open"]} offen · {shadow_sum["closed"]} zu · {shadow_sum["pnl"]:+.2f} $' if shadow_sum else "—")
frag["s_control"] = (f'{sum(r["open"] for r in _ctrl)} offen · {sum(r["closed"] for r in _ctrl)} zu' if _ctrl else "—")
frag["s_rejtrack"] = (f'{len(_rc)} Coins' if "_rc" in globals() else "—")
frag["s_review"] = (dt.datetime.fromtimestamp(os.path.getmtime(f"{DESK}/reviews/weekly_latest.html"), BER).strftime("%d.%m. %H:%M") + " Berlin") if os.path.exists(f"{DESK}/reviews/weekly_latest.html") else "—"

# ---------- 2026-10-22 SELF-LEARN (USER ORDER 17:58): "Lernt dazu" panel = last 5 learner changes + trades analysed ----------
def _learn_html():
    def _j(p):
        try: return json.load(open(p))
        except Exception: return None
    ov = _j(f"{DESK}/learner_overrides.json") or {}; rp = _j(f"{DESK}/learner/report.json") or {}
    try:
        import learner as _lm; _on = _lm.enabled()
    except Exception: _on = None
    ch = [c for c in ov.get("changes", []) if c.get("kind") in ("tighten", "loosen", "revert")][-5:][::-1]
    n_an = rp.get("trades_main_with_features"); n_sh = rp.get("shadow_trades")
    try: _at = dt.datetime.fromisoformat(rp["at"]).astimezone(BER).strftime("%d.%m. %H:%M") + " Berlin"
    except Exception: _at = "noch nie"
    _kind = {"tighten": "verschärft", "loosen": "gelockert", "revert": "zurückgenommen"}
    rows = ""
    for c in ch:
        try: t = dt.datetime.fromisoformat(c["at"]).astimezone(BER).strftime("%d.%m. %H:%M")
        except Exception: t = "?"
        cls = "cr-neg" if c.get("kind") == "revert" else "cr-pos" if c.get("kind") == "loosen" else "cr-zero"
        rows += (f'<div class="cr {cls}"><div class="cr1"><b class="tn">{esc(str(c.get("label") or c.get("param")))}</b> '
                 f'<span class="tag2">{_kind.get(c.get("kind"), esc(str(c.get("kind"))))}</span> <b class="crp">{esc(str(c.get("old")))} → {esc(str(c.get("new")))}</b></div>'
                 f'<div class="cr2">{t} Berlin · {esc(str(c.get("reason_de") or ""))}</div></div>')
    head = (f'<div class="sech"><h2>Lernt dazu <span class="badge-n">{len(ov.get("params", {}))}</span></h2>'
            f'<div class="secs">{"aktiv" if _on else "AUS (Kill-Switch)" if _on is False else "—"} · {n_an if n_an is not None else "—"} echte Trades + {n_sh if n_sh is not None else "—"} Shadow-Trades analysiert · letzter Lauf {_at} · '
            f'{len(rp.get("proposals") or [])} Änderung(en) im letzten Lauf</div></div>')
    return head + (rows or '<div class="none">Noch keine Regel geändert – das Gate (≥15 Trades, klar negativ, Holdout auf den neuesten 30 %) hat bisher nichts freigegeben.</div>'), (f'{len(ov.get("params", {}))} aktiv · {n_an if n_an is not None else "—"} Trades')
try: frag["learn"], frag["s_learn"] = _learn_html()
except Exception as e: frag["learn"], frag["s_learn"] = f'<div class="none">Lernt dazu: {esc(str(e))}</div>', "—"

# ---------- 2026-10-21 SAVIP redesign (dash_savip.py): desk floor / balance / holdings / analysis / activity, black theme ----------
SV = None
try:
    import dash_savip as _sv, dash_charts as _dc
    SV = _sv.assemble(globals())
    frag.update(SV["frag"])   # "open" = holdings rows (same .tc[data-ck] tap-to-expand cards), + hold_head/hold_n/analysis/an_head/activity2
except Exception as e:
    import traceback; traceback.print_exc(); errors.append(f"savip: {type(e).__name__}: {e}"); frag["errors"] = "".join(f'<div class="err">{esc(x)}</div>' for x in errors)
data = {
    "generated_at": NOW.astimezone(BER).isoformat(timespec="seconds"), "generated_ts": int(NOW.timestamp()),
    "mode": "PAPER", "bank": {"start": start, "started": bank["started"], "equity": round(equity, 4), "pnl": round(pnl, 4), "pnl_pct": round(pnl_pct, 4),
             "cash": round(bank_state["cash"], 4), "realized": round(bank_state["realized"], 4), "unrealized": round(bank_state["unrealized"], 4),
             "meme_pnl": round(meme_pnl, 4), "trend_pnl": round(alp_pnl, 4), "wins": wins, "losses": losses,
             "start_eur": bank.get("start_eur"), "epoch": bank.get("epoch", 1), "started_at": bank.get("started_at"),
             "started_label": dt.datetime.fromisoformat(bank["started_at"]).astimezone(BER).strftime("%d.%m. %H:%M"),
             "previous": bank.get("epochs", [])},
    "dial": dial, "history": [[t.isoformat(), v] for t, v in hist[-400:]],
    "activity": [{"t": t, "line": m} for t, m in activity[:60]],
    "holdings": bank_state["holdings"], "meme_open": (meme or {}).get("open", []), "meme_closed": (meme or {}).get("closed", [])[-50:],
    "account": acct, "orders": [{"time": o.submitted_at.isoformat(), "side": str(o.side.value), "symbol": o.symbol, "notional": str(o.notional or ""),
                                 "qty": str(o.qty or ""), "status": str(o.status.value), "filled_avg_price": str(o.filled_avg_price or "")} for o in (orders or [])],
    "bots": [{"name": n, "status": st, "note": d} for n, v, st, d in bots],
    "schedule": {"meme_cadence_min": cad, "next_scan": nxt_scan, "risk_poll": risk_sched, "quant_next": fmt_ber(nxt_dial) if dial_sched else None, "cron_running": cron_ok},
    "scan": {"latest": rej_rec, "judge": judge_rec},
    "newpairs": {k: v for k, v in (_np or {}).items() if k not in ("candidates", "near_misses")},
    "shadow": shadow_sum,
    "alpaca_sleeves": {"lists": alp_lists, "stocks": alp["stocks"], "crypto": alp["crypto"], "kill": alp["kill"], "kill_today": kill_today,
                       "market_value": alp_mv, "jev_active": jev_on},
    "open_trades": open_rows, "open_counts": n_open_by, "chart_notes": chart_notes, "equity": equity_data, "errors": errors, "fragments": frag,
}
if SV: data["savip"] = SV["data"]
data_js = json.dumps(data, default=str, separators=(",", ":"))

LIVE_CSS = """.live{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:#cfc9ff}.live i{width:8px;height:8px;border-radius:50%;background:var(--a);box-shadow:0 0 8px var(--glow);animation:pd2 1.6s infinite}
.live.stale{color:#8e8e93}.live.stale i{background:#636366;box-shadow:none;animation:none}
@keyframes pd2{0%{box-shadow:0 0 0 0 rgba(91,75,219,.8)}70%{box-shadow:0 0 0 8px rgba(91,75,219,0)}100%{box-shadow:0 0 0 0 rgba(91,75,219,0)}}
.noanim .draw{animation:none;stroke-dashoffset:0}.noanim .area{animation:none;opacity:1}"""
LIVE_JS = r"""(function(){
var D=JSON.parse(document.getElementById('embedded').textContent),last=D.generated_ts,ok=false,lastOk=0;
var ind=document.getElementById('live'),txt=document.getElementById('live-t');
function ago(){var s=Math.max(0,Math.round(Date.now()/1000-last)),stale=s>180||(!ok&&location.protocol!=='file:'&&lastOk&&Date.now()-lastOk>60000);
 var a=s<90?s+'s':s<5400?Math.round(s/60)+'m':Math.round(s/3600)+'h';
 txt.textContent=(location.protocol==='file:'&&!ok?'statisch · ':'')+'aktualisiert vor '+a;ind.className='live'+(stale||(!ok&&location.protocol==='file:')?' stale':'')}
function apply(d){var f=d.fragments||{};if(window.deskPre)try{window.deskPre()}catch(e){}
 Object.keys(f).forEach(function(k){var el=document.getElementById('f-'+k);if(!el||el.innerHTML===f[k])return;if(k==='open'&&window.deskSwap)try{if(window.deskSwap(el,f[k]))return}catch(e){}
  var open={},sc={};el.querySelectorAll('details').forEach(function(x,i){open[i]=x.open});
  el.querySelectorAll('.log,.tscroll').forEach(function(x,i){sc[i]=[x.scrollTop,x.scrollLeft]});
  el.innerHTML=f[k];
  el.querySelectorAll('details').forEach(function(x,i){if(i in open)x.open=open[i]});
  el.querySelectorAll('.log,.tscroll').forEach(function(x,i){if(sc[i]){x.scrollTop=sc[i][0];x.scrollLeft=sc[i][1]}});});
 if(window.deskPost)try{window.deskPost(null,d)}catch(e){}
 last=d.generated_ts;ago()}
function poll(){fetch('data.json'+(location.search?location.search+'&':'?')+'_='+Date.now(),{cache:'no-store',credentials:'same-origin'}).then(function(r){if(!r.ok)throw 0;return r.json()})
 .then(function(d){ok=true;lastOk=Date.now();document.body.classList.add('noanim');if(d.generated_ts!==last||true)apply(d)})
 .catch(function(){ok=false;ago()})}
setTimeout(function(){document.body.classList.add('noanim')},2500);
ago();setInterval(ago,1000);poll();setInterval(poll,15000);
document.addEventListener('visibilitychange',function(){if(!document.hidden)poll()});
})();"""

page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<noscript><meta http-equiv="refresh" content="60"></noscript>
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Grok Desk">
<meta name="theme-color" content="#161618"><meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png"><link rel="icon" type="image/png" href="apple-touch-icon.png">
<title>Trading Desk (Paper) · {_n_open} offen</title><style>{CSS}{LIVE_CSS}{CSS2}{CSS3}</style></head><body class="v2"><div class="wrap2">
<div id="f-errors">{frag["errors"]}</div>
<header id="f-header">{frag["header"]}</header>
<section class="card2 eqs" id="eqbox"><div class="eqh"><div class="seg"><button type="button" data-k="s" data-v="meme">Meme-Bank</button><button type="button" data-k="s" data-v="alp">Alpaca</button></div>
<div class="seg"><button type="button" data-k="u" data-v="usd">$</button><button type="button" data-k="u" data-v="pct">%</button></div></div>
<div style="margin-top:8px"><span class="eqv" id="eqv"></span> <span id="eqd" class="eqd"></span><div id="eqz" style="font-size:13.5px;font-weight:600"></div></div>
<div id="eqc"></div><div class="eqr"><div class="seg"><button type="button" data-k="r" data-v="today">Heute</button><button type="button" data-k="r" data-v="7d">7 Tage</button><button type="button" data-k="r" data-v="all">Alles</button></div><div class="eqtt" id="eqtt"></div></div>
<div class="eqn" id="eqnote">Meme-Bank = Desk-Equity aus history.csv (alle 5 Min) · Alpaca = Paper-Konto (Portfolio-History) · Pfeile = größte Trades</div><noscript><div class="eqn">Chart braucht JavaScript (Drive-Vorschau zeigt ihn nicht).</div></noscript></section>
<div class="livebar"><span id="live" class="live"><i></i><span id="live-t">gerade aktualisiert</span></span> · gebaut <span id="f-gen">{gen}</span> · Zahlen alle 15 s, Seite alle 60 s neu</div>
<section class="card2" id="f-open">{frag["open"]}</section>
<section class="card2" id="f-closed">{frag["closed"]}</section>
<details class="sec" id="d-learn"><summary>Lernt dazu (Self-Learner)<span class="sm" id="f-s_learn">{frag["s_learn"]}</span></summary><div class="body" id="f-learn">{frag["learn"]}</div></details>
<div class="more2"><h3>MEHR (ZUM AUFKLAPPEN)</h3>
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
<details class="sec" id="d-honest"><summary>Hinweis</summary><div class="body honest"><p>Nur Paper-Trading. Meme: virtuelle Bank (Start {money(start)}), simulierte pump.fun-Fills. TREND/STOCKS/CRYPTO: Alpaca-PAPER-Konto (eigenes Buch, Start $100.000). Vergangene Ergebnisse garantieren nichts.</p></div></details>
</div>
<div class="foot">Alpaca Paper + pump.fun SIMULIERT · keine Wallets · Live-Zahlen aus data.json alle 15 s</div>
</div><script id="embedded" type="application/json">{data_js.replace("</", "<\\/")}</script><script id="charts-embedded" type="application/json">{{}}</script><script>{JS}</script><script>{LIVE_JS}</script><script>{KEEP_JS}</script><script>{LW_JS}</script><script>{CHART_JS}</script><script>{EQ_JS}</script><script>{RELOAD_JS}</script></body></html>"""
if SV:
    try: page = _sv.page(globals(), SV)
    except Exception as e:
        import traceback; traceback.print_exc(); print(f"WARNING: savip page failed, old layout kept: {type(e).__name__}: {e}")
# ---------- widget.json (tiny, numbers only; published to a separate public here.now Site at a random path) ----------
last_trade = None
evts = []
for c in (meme or {}).get("closed", []): evts.append((c["exit_time"], f'SELL {c["name"].split(" / ")[0]} {c["pnl"]:+.2f} (sim)'))
for o in (meme or {}).get("open", []): evts.append((o["entry_time"], f'BUY {o["name"].split(" / ")[0]}{" NEW PAIR" if o.get("sleeve") == "newpairs" else ""} ${o["cost_usd"]:.2f} (sim)'))
for f_ in fills: evts.append((str(f_["time"]), f'{f_["side"]} {f_["symbol"]} {f_["qty"]:.4g} @ {f_["price"]:.2f}'))
if evts: last_trade = sorted(evts)[-1][1]
widget = {"title": "GROK BOT TEST", "mode": "PAPER", "balance": round(equity, 2), "start": start, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
          "open_positions": len(bank_state["holdings"]), "last_trade": last_trade or "no trades yet",
          "meme_dial": dial["dial"]["meme"] if dial else None,
          "alpaca_equity": round(acct["equity"], 2) if acct else None, "alpaca_day_pct": round((acct["equity"]/acct["last_equity"]-1)*100, 2) if acct and acct["last_equity"] else None,
          "updated_at": NOW.astimezone(BER).isoformat(timespec="seconds")}
_wout = os.environ.get("DESK_DASH_OUT") or f"{DESK}/dashboard"; os.makedirs(_wout, exist_ok=True)
_wtmp = f"{_wout}/.widget.json.tmp"; open(_wtmp, "w").write(json.dumps(widget)); os.replace(_wtmp, f"{_wout}/widget.json")
try: os.environ.setdefault("JEV_API_KEY", (_jev._conf().get("key") or ""))
except Exception: pass
for k in ("ALPACA_KEY", "ALPACA_SECRET", "JEV_API_KEY", "TYPESAFE_API_KEY"):
    v = os.environ.get(k)
    assert not v or (v not in page and v not in data_js), "secret leak guard"
tok = open(f"{DESK}/dash_token").read().strip() if os.path.exists(f"{DESK}/dash_token") else (os.environ.get("DASH_TOKEN") or "").strip() or None
assert not tok or (tok not in page and tok not in data_js), "token leak guard"
_OUT = os.environ.get("DESK_DASH_OUT") or f"{DESK}/dashboard"   # test builds write elsewhere; cron uses the default
_priv = []   # privacy guard: widget feed link / site password / SEC contact e-mail must never be on the dashboard
try:
    _hs = json.load(open(f"{DESK}/herenow_site.json"))
    _priv += [str(_hs[k]) for k in ("widget_path", "widget_slug", "widget_url", "widget_site_url", "password") if _hs.get(k) and len(str(_hs[k])) >= 8]
except Exception: pass
try: _priv += re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", open(f"{DESK}/sec.env").read())
except Exception: pass
# 2026-10-22 github: same guard for values that come from env (Actions secrets) instead of local files
_priv += [os.environ[k].strip() for k in ("HERENOW_SITE_PASSWORD", "HERENOW_WIDGET_PATH", "HERENOW_WIDGET_SLUG") if len((os.environ.get(k) or "").strip()) >= 8]
_priv += re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", os.environ.get("SEC_USER_AGENT", ""))
for _v in _priv: assert _v not in page and _v not in data_js, "privacy leak guard (widget link / SEC e-mail)"
os.makedirs(_OUT, exist_ok=True)
charts_js = json.dumps({"generated_ts": int(NOW.timestamp()), "charts": charts}, default=str, separators=(",", ":"))
for _v in _priv: assert _v not in charts_js, "privacy leak guard (charts)"
for name, body in (("charts.json", charts_js), ("data.json", data_js), ("index.html", page)):
    tmp = f"{_OUT}/.{name}.tmp"
    open(tmp, "w").write(body); os.replace(tmp, f"{_OUT}/{name}")
if not os.environ.get("DESK_DASH_OUT"):
    try:   # Drive mirror (2026-10-20 22:5x): LIGHT single file. The Drive tool caps one update at 1,000,000 characters and the Drive
        # preview runs no JS, so the copy keeps all server-rendered HTML but drops the chart library, the embedded data.json and all
        # chart data (charts stay on the here.now site, which loads charts.json separately). Target < 600k characters.
        DRIVE_SOFT, DRIVE_HARD = 600_000, 900_000
        _emb = '<script id="embedded" type="application/json">' + data_js.replace("</", "<\\/") + '</script>'
        _mini = json.dumps({"generated_ts": data["generated_ts"], "generated_at": data["generated_at"], "mode": "PAPER", "fragments": {}, "drive_copy": True})
        drive = page.replace(_emb, '<script id="embedded" type="application/json">' + _mini + '</script>')
        if LW_JS: drive = drive.replace("<script>" + LW_JS + "</script>", "")
        drive = re.sub(r'<img class="lgi"[^>]*>', "", drive)   # SAVIP v2: logos are served files on here.now only; Drive copy keeps the initials
        drive = drive.replace('<section class="card2 eqs" id="eqbox">', '<section class="card2 eqs" id="eqbox"><div class="none">Charts nur auf der Webseite (here.now) · Drive-Kopie ohne Chartdaten</div>', 1)
        drive = drive.replace("</style>", "#eqc,#eqbox .seg,#eqbox .eqtt,#eqnote,.chint,.tc-chart{display:none!important}</style>", 1)
        if len(drive) > DRIVE_HARD:   # hard guard: strip every remaining script block + embedded JSON and warn
            drive = re.sub(r"<script\b[^>]*>.*?</script>", "", drive, flags=re.S)
            print(f"WARNING: Drive mirror still {len(drive)} chars after stripping scripts (hard cap {DRIVE_HARD})")
            if len(drive) > DRIVE_HARD:
                drive = drive[:0] + ('<!doctype html><meta charset="utf-8"><title>Trading Desk (Paper)</title><body style="font-family:sans-serif;background:#161618;color:#eee">'
                                     + header_section + open_section + '<p>Drive-Kopie gekürzt (zu groß). Vollständig auf der Webseite.</p></body>')
                print(f"WARNING: Drive mirror reduced to header + open trades ({len(drive)} chars)")
        elif len(drive) > DRIVE_SOFT:
            print(f"WARNING: Drive mirror {len(drive)} chars > soft target {DRIVE_SOFT}")
        for _v in _priv: assert _v not in drive, "privacy leak guard (drive copy)"
        open("/workspace/.desk-dashboard.html.tmp", "w").write(drive)
        os.replace("/workspace/.desk-dashboard.html.tmp", "/workspace/desk-dashboard.html")
    except AssertionError: raise
    except Exception as e: print(f"WARNING: Drive mirror not written: {type(e).__name__}: {e}")
print(f"{_OUT}/index.html + data.json", "errors:", errors or "none")
