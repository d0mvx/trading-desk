#!/usr/bin/env python3
"""SHADOW book (upgrade 3, 2026-10-20 19:5x, user-approved). PAPER, virtual only — never touches bank.json / meme_positions.json.
Records virtual trades for candidates the real desk did NOT buy because of
  * capacity:   'max open' (main max 3 / overall 4; new pairs max 2), 'one buy per run'
  * policy:     main sleeve bonding-curve coins (upgrade 4: no real curve buys)
  * exactly ONE failing gate (main: SCAN filter / JUDGE metric / RugCheck / dip; new pairs: narrative passer with one safety gate)
Same fill model (meme.sim_buy / sim_sell incl. priority fee + rent deposit) and the SAME exit rules (meme.exit_decision),
checked in the fast-exit loop (meme.py risk, 5x/min) with DexScreener + on-chain curve prices (0 GeckoTerminal calls).
Files: shadow_positions.json (open + compact closed), logs/shadow_trades.jsonl, logs/shadow.log. Lock: .shadow.lock.
Usage: shadow.py summary | shadow.py state"""
import os, sys, json, time, datetime as dt
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
import meme
from leads import lead_id, ltag   # 2026-10-20 research upgrade: lead IDs
SPOS = f"{DESK}/shadow_positions.json"; STRADES = f"{DESK}/logs/shadow_trades.jsonl"; SLOG = f"{DESK}/logs/shadow.log"
LOCK = f"{DESK}/.shadow.lock"
MAX_OPEN_TOTAL = 150      # bounds the DexScreener load: <= 5 batch calls per check (30 mints/call)
MAX_OPEN_PER_CAT = 10
REOPEN_MIN = 120          # same (mint, category) is not re-opened within 120 min of its last shadow entry
CLOSED_KEEP = 5000
SAFETY_EVERY_S = 60       # new-pair safety exits (dev sold / volume collapse / RugCheck danger) for shadow positions: <= 1x/min each
SAFETY_MAX_PER_CHECK = 8

def log(line):
    with open(SLOG, "a") as f: f.write(f"{meme.now().astimezone(meme.BER):%Y-%m-%d %H:%M:%S %Z} {line}\n")
def load():
    try: return json.load(open(SPOS))
    except (FileNotFoundError, ValueError): return {"open": [], "closed": [], "recent": {}}
def save(d):
    tmp = SPOS + ".tmp"; json.dump(d, open(tmp, "w"), default=str, separators=(",", ":")); os.replace(tmp, SPOS)
def tlog(rec):
    with open(STRADES, "a") as f: f.write(json.dumps(rec, default=str, separators=(",", ":")) + "\n")

def _refresh(ents):
    """fresh entry prices: DexScreener for everything it indexes, chain curve for fresh curve coins; else the candidate price."""
    try: return meme.fast_prices([{"pool": e["pool"], "token": e["token"], "venue": e["venue"], "sol_usd": e.get("sol")} for e in ents])
    except Exception: return {}

def open_entries(ents):
    """ents: [{cat, note, pool, token, name, venue, price, sol, liq, mcap, ticket, exit, sleeve, url, (tier, creator, ...)}]"""
    ents = [e for e in ents if e.get("token") and e.get("pool")]
    if not ents: return 0
    t = time.time(); fresh = _refresh(ents); n = 0
    with meme.poslock(path=LOCK):
        d = load(); rec = {k: v for k, v in d.get("recent", {}).items() if t - v < REOPEN_MIN * 60}
        percat = {}
        for o in d["open"]: percat[o["cat"]] = percat.get(o["cat"], 0) + 1
        for e in ents:
            key = f"{e['token']}|{e['cat']}"
            if key in rec or len(d["open"]) >= MAX_OPEN_TOTAL or percat.get(e["cat"], 0) >= MAX_OPEN_PER_CAT: continue
            a = fresh.get(e["pool"]) or {}
            if a.get("_migrated_to") and e["venue"] == "bonding_curve": continue   # graduating right now -> skip
            price = float(a.get("base_token_price_usd") or e.get("price") or 0); sol = float(a.get("quote_token_price_usd") or e.get("sol") or 0)
            liq = float(a.get("reserve_in_usd") or e.get("liq") or 0)
            if e["venue"] == "bonding_curve" and price and sol:
                import scan; cs = scan.curve_state(price, sol); liq = cs["real_sol"] * sol if cs else liq
            ticket = round(e.get("ticket") or 0, 2)
            if not price or not sol or ticket < meme.MIN_TICKET: continue
            b = meme.sim_buy(ticket, e["venue"], price, sol, liq, float(a.get("market_cap_usd") or e.get("mcap") or 0))
            o = {"id": f"S{int(t*1000)%10**10}{n}", "lead": lead_id(e["token"]), "cat": e["cat"], "note": (e.get("note") or "")[:160], "sleeve": e.get("sleeve", "main"),
                 "pool": e["pool"], "token": e["token"], "name": e["name"], "venue": e["venue"], "url": e.get("url"),
                 "entry_time": meme.now().isoformat(), **b, "tp_done": False, "tp_hits": [], "stop_loss": meme.STOP_LOSS.get(e["venue"], 0.20) if e.get("sleeve") != "newpairs" else 0.30,
                 "exit": e.get("exit") or meme.MAIN_EXIT, "realized": 0.0, "cost_initial": ticket, "shadow": True, "price_src": a.get("_src", "candidate")}
            for k in ("tier", "creator", "narrative_score", "feat"):   # feat: 2026-10-22 SELF-LEARN entry features
                if e.get(k) is not None: o[k] = e[k]
            d["open"].append(o); rec[key] = t; percat[e["cat"]] = percat.get(e["cat"], 0) + 1; n += 1
            tlog({"type": "SHADOW_BUY", **o})
            log(f"[SHADOW] BUY {ltag(o['token'])}{o['name']} [{o['cat']}] ${ticket:.2f} @ {o['entry_price']:.10g} ({o['venue']}, {o['price_src']}) | {o['note'][:90]}")
        d["recent"] = rec; save(d)
    return n

def check(i, deadline=None):
    """one fast-exit pass over the shadow book (called from meme.risk after the real book)."""
    d0 = load()
    if not d0["open"]: return 0
    if deadline and time.time() > deadline - 3: return 0
    errs = []; data = meme.fast_prices(d0["open"], errs=errs); saf, rcat = {}, {}
    if i == 0:   # new-pair safety exits, at most once a minute per position, bounded per check
        import newpairs
        for o in [o for o in d0["open"] if o.get("sleeve") == "newpairs" and o["pool"] in data][:SAFETY_MAX_PER_CHECK]:
            if deadline and time.time() > deadline - 6: break
            if time.time() - (o.get("_saf_at") or 0) < SAFETY_EVERY_S: continue
            try: saf[o["id"]] = newpairs.position_safety(o); rcat[o["id"]] = o.get("np_rc_at")
            except Exception: pass
    n = 0
    with meme.poslock(path=LOCK):
        d = load(); keep = []
        for o in d["open"]:
            a = data.get(o["pool"])
            if o["id"] in rcat: o["np_rc_at"] = rcat[o["id"]]; o["_saf_at"] = time.time()
            if not a: keep.append(o); continue
            if a.get("_migrated_to") and o["venue"] == "bonding_curve":
                o["pool_original"] = o["pool"]; o["pool"] = a["_migrated_to"]; o["venue"] = "pumpswap"
            mark = float(a["base_token_price_usd"]); ratio, vmode = meme.vol_decay(a.get("volume_usd") or {}, a.get("pool_created_at"))
            o["last_price"] = mark; o["last_check"] = meme.now().isoformat()
            frac, why = meme.exit_decision(o, mark, ratio, vmode, saf.get(o["id"]))
            n += 1
            if not frac: keep.append(o); continue
            f = meme.sim_sell(o, a, frac); o["realized"] = round(o.get("realized", 0) + f["pnl"], 6)
            tlog({"type": "SHADOW_SELL", "id": o["id"], "cat": o["cat"], "name": o["name"], "frac": frac, "reason": why, **f})
            if frac < 1.0:
                o["qty"] -= f["qty"]; o["cost_usd"] = round(o["cost_usd"] - f["cost_usd"], 6); keep.append(o)
                log(f"[SHADOW] SELL PART {ltag(o.get('token'))}{o['name']} [{o['cat']}] {frac:.0%} -> {f['pnl']:+.4f} | {why}")
            else:
                c = {"id": o["id"], "cat": o["cat"], "sleeve": o["sleeve"], "name": o["name"], "venue": o["venue"], "entry_time": o["entry_time"],
                     "exit_time": f["exit_time"], "cost_usd": o["cost_initial"],
                     "pnl": o["realized"], "peak_gain": round(o["peak_price"] / o["entry_price"] - 1, 4), "tp_hits": o.get("tp_hits"), "reason": why[:140]}
                c["pnl_pct"] = round(c["pnl"] / c["cost_usd"], 4) if c["cost_usd"] else None
                d["closed"].append(c)
                log(f"[SHADOW] CLOSE {ltag(o.get('token'))}{o['name']} [{o['cat']}] total {o['realized']:+.4f} ({(c['pnl_pct'] or 0):+.1%}) | {why}")
        d["open"] = keep; d["closed"] = d["closed"][-CLOSED_KEEP:]; save(d)
    return n

def summary():
    """per category: opened / open / closed, win rate, realized P&L, open unrealized, avg % (compact, for the dashboard)."""
    d = load(); cats = {}
    for c in d["closed"]:
        s = cats.setdefault(c["cat"], {"cat": c["cat"], "open": 0, "closed": 0, "wins": 0, "pnl": 0.0, "upnl": 0.0, "pct_sum": 0.0})
        s["closed"] += 1; s["wins"] += c["pnl"] > 0; s["pnl"] += c["pnl"]; s["pct_sum"] += c.get("pnl_pct") or 0
    for o in d["open"]:
        s = cats.setdefault(o["cat"], {"cat": o["cat"], "open": 0, "closed": 0, "wins": 0, "pnl": 0.0, "upnl": 0.0, "pct_sum": 0.0})
        s["open"] += 1; s["upnl"] += o.get("realized", 0) + o["qty"] * (o.get("last_price") or o["entry_mid"]) - o["cost_usd"]
    rows = []
    for s in cats.values():
        rows.append({"cat": s["cat"], "open": s["open"], "closed": s["closed"], "win_rate": round(s["wins"] / s["closed"], 3) if s["closed"] else None,
                     "pnl": round(s["pnl"], 4), "open_pnl": round(s["upnl"], 4), "avg_pct": round(s["pct_sum"] / s["closed"], 4) if s["closed"] else None})
    rows.sort(key=lambda r: (-(r["closed"] + r["open"]), r["cat"]))
    tot_c = sum(r["closed"] for r in rows); tot_w = sum(1 for c in d["closed"] if c["pnl"] > 0)
    return {"rows": rows, "open": len(d["open"]), "closed": tot_c, "win_rate": round(tot_w / tot_c, 3) if tot_c else None,
            "pnl": round(sum(r["pnl"] for r in rows), 4), "open_pnl": round(sum(r["open_pnl"] for r in rows), 4)}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if cmd == "summary": print(json.dumps(summary(), indent=1))
    else: print(json.dumps(load(), indent=1, default=str)[:20000])
