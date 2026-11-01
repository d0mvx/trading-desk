"""STEP 9 commands (Account tab command box + Grok Bot reading the db via cli.py). No Telegram: replies go back to the
caller; 'buy X' resends the push through the notifier (Web Push). Every coin mentioned carries its coin_url.
No order is ever placed."""
from __future__ import annotations
import asyncio, datetime as dt, re
from . import db, util, config, account, links

AGENTS = ["scanner", "auditor", "analyst", "executor", "risk"]
HELP = ("Commands: buy X · sell X · why X · pause/resume <agent> · set stop to -8% · stack 1240 · skip X · "
        "status · paper | live · invite · report   (X = name, symbol or mint)")

def coins_matching(q: str) -> list[dict]:
    q = q.strip().lstrip("$")
    c = db.coin(q)
    if c: return [c]
    return db.q("SELECT * FROM coins WHERE lower(symbol)=lower(?) OR lower(name)=lower(?) ORDER BY migrated_at DESC", (q, q))

def find_coin(q: str) -> dict | None:
    r = coins_matching(q)
    return r[0] if r else None

def _nm(c):
    return c.get("symbol") or c.get("name") or util.short(c["mint"])

def _pick(q):
    """(coin, error_reply). Unknown -> ask for the mint; 2+ -> ask which, each with its coin_url."""
    r = coins_matching(q)
    if not r:
        if links._B58.match(q.strip()):
            return {"mint": q.strip(), "symbol": None, "name": None, "_new": True}, None
        return None, f"I don't know '{q}'. Send me its mint."
    if len(r) > 1:
        return None, f"'{q}' matches {len(r)} coins, which one?\n" + "\n".join(f"- {_nm(c)} · {c['mint']} · {links.coin_url(c['mint'])}" for c in r[:10])
    return r[0], None

def why(q: str) -> str:
    c, err = _pick(q)
    if err: return err
    m = c["mint"]
    lines = [f"{_nm(c)} · {links.coin_url(m)}"]
    sc = db.one("SELECT * FROM scans WHERE mint=? AND verdict IN ('kill','pass','drop') ORDER BY id DESC LIMIT 1", (m,))
    if sc: lines.append(f"Scanner: {sc['verdict']} · {sc['reason']} · {util.local_hm(sc['ts'])}")
    au = db.q("SELECT layer,name,value_text,pass,ts FROM audits WHERE mint=? ORDER BY id DESC LIMIT 8", (m,))
    red = next((a for a in au if a["pass"] == 0), None)
    if red: lines.append(f"Auditor: layer {red['layer']} {red['name']} · {red['value_text']} · {util.local_hm(red['ts'])}")
    for a in sorted(au, key=lambda r: r["layer"]):
        lines.append(f"  {a['layer']} {a['name']}: {a['value_text']} {'✓' if a['pass'] == 1 else ('✗' if a['pass'] == 0 else '·')}")
    v = db.one("SELECT * FROM verdicts WHERE mint=? ORDER BY id DESC LIMIT 1", (m,))
    if v: lines.append(f"Analyst: score {v['score']} · {'pass' if v['pass'] else v['reason']} · {util.local_hm(v['ts'])} "
                       f"(alive {v['alive_6h']}, organic {v['organic']}, flush {v['flush']}, chase {v['chase']})")
    d = db.one("SELECT * FROM decisions WHERE mint=? AND agent='executor' ORDER BY id DESC LIMIT 1", (m,))
    if d: lines.append(f"Executor: {d['text']} · {util.local_hm(d['ts'])}")
    p = db.one("SELECT * FROM positions WHERE mint=? ORDER BY id DESC LIMIT 1", (m,))
    if p: lines.append(f"Position: ${p['size_usd']:.2f} at {p['entry_price']:.8g} · {p['exit_reason'] or 'open'} · pnl {p['pnl_usd']}")
    if len(lines) == 1: lines.append("Seen, nothing decided yet.")
    return "\n".join(lines)

async def buy(q: str) -> dict:
    from . import webpush
    from .agents import auditor
    c, err = _pick(q)
    if err: return {"ok": False, "text": err}
    m = c["mint"]; url = links.coin_url(m)
    pu = db.one("SELECT * FROM pushes WHERE mint=? AND kind='buy' AND ts>=? ORDER BY id DESC LIMIT 1",
                (m, util.iso(util.night_start(config.get("desk.report_time")))))
    if pu:
        r = await webpush.push(pu["title"].removeprefix("PAPER · "), pu["body"], m, "buy")
        return {"ok": True, "text": f"Resent the push: {pu['title']}\n[Buy on {links.VENUE}] {url}", "link": url, "delivered": r["ok"]}
    if c.get("_new"):
        db.upsert_coin(m, migrated_at=util.iso())
    ok = await auditor.audit({"mint": m, "pool": (db.coin(m) or {}).get("pool")}, record=False)
    rows = db.q("SELECT layer,name,value_text,pass FROM audits WHERE mint=? ORDER BY id DESC LIMIT 8", (m,))
    lay = "\n".join(f"  {a['layer']} {a['name']}: {a['value_text']} {'✓' if a['pass'] == 1 else ('✗' if a['pass'] == 0 else '·')}" for a in sorted(rows, key=lambda r: r["layer"]))
    return {"ok": True, "text": f"{_nm(db.coin(m) or c)} · {'Cleared 8/8' if ok else 'Rejected'}\n{lay}\n[Buy on {links.VENUE}] {url}\nnot sized, not on the desk",
            "link": url}

def sell(q: str) -> dict:
    c, err = _pick(q)
    if err: return {"ok": False, "text": err}
    p = db.one("SELECT * FROM positions WHERE mint=? AND closed_at IS NULL", (c["mint"],))
    if not p: return {"ok": False, "text": f"No open {_nm(c)} position · {links.coin_url(c['mint'])}"}
    return {"ok": True, "text": f"[Sell on {links.VENUE}] {links.coin_url(c['mint'])} · {config.get('desk.mode')} position ${p['size_usd']:.2f}",
            "link": links.coin_url(c["mint"])}

def run(text: str, who: str = "app") -> dict:
    """Sync commands. 'buy X' needs the network -> use arun()."""
    t = text.strip().lstrip("/")
    tl = t.lower()
    try:
        if tl.startswith("why "):
            return {"ok": True, "text": why(t[4:])}
        if tl.startswith("sell "):
            return sell(t[5:])
        m = re.match(r"^(pause|resume)\s+(\w+)$", tl)
        if m:
            ag = m.group(2)
            if ag not in AGENTS: return {"ok": False, "text": f"unknown agent {ag}"}
            if m.group(1) == "pause" and ag == "risk" and account.open_positions():
                return {"ok": False, "text": "Risk can't be paused while a position is open"}
            db.set_paused(ag, m.group(1) == "pause")
            extra = " · no new coins, Risk keeps guarding" if (ag == "scanner" and m.group(1) == "pause") else ""
            return {"ok": True, "text": f"{ag.capitalize()} {m.group(1)}d{extra}"}
        m = re.match(r"^set\s+(.+?)\s+(?:to\s+)?(-?[\w.:$%,]+)$", tl)
        if m:
            key, val = m.group(1), m.group(2)
            k = config.resolve_key(key)
            if k in ("risk.stop_pct", "risk.trail_pct"):
                val = val.lstrip("-")
            k, old, new = config.set(k, val, who)
            short = k.split(".")[-1].replace("_pct", "")
            if k == "risk.stop_pct":
                txt = f"stop -{old:g}% -> -{new:g}% (open stops only tighten)"
            else:
                txt = f"{short} {old} -> {new}"
            return {"ok": True, "text": txt, "warning": config.ticket_check()}
        m = re.match(r"^stack\s+\$?([\d.,]+)$", tl)
        if m:
            k, old, new = config.set("desk.live_stack", m.group(1), who)
            return {"ok": True, "text": f"LIVE stack {old} -> {new} (the desk runs PAPER; LIVE is locked)"}
        m = re.match(r"^skip\s+(.+)$", tl)
        if m:
            c, err = _pick(m.group(1))
            if err: return {"ok": False, "text": err}
            skip(c["mint"]); return {"ok": True, "text": f"{_nm(c)} skipped until the morning report · {links.coin_url(c['mint'])}"}
        if tl == "live":
            return {"ok": False, "text": "LIVE is locked. The desk runs PAPER only."}
        if tl == "paper":
            return {"ok": True, "text": "PAPER (already)."}
        if tl == "status":
            return {"ok": True, "text": status()}
        if tl == "invite":
            return {"ok": True, "text": links.SIGNUP_URL, "link": links.SIGNUP_URL}
        if tl == "report":
            import glob, os
            fs = sorted(glob.glob(os.path.join(util.ROOT, "reports", "*.html")))
            return {"ok": True, "text": fs[-1] if fs else "No morning report yet. /api/report shows tonight so far."}
    except config.SettingError as e:
        return {"ok": False, "text": str(e)}
    return {"ok": False, "text": HELP}

async def arun(text: str, who: str = "app") -> dict:
    t = text.strip().lstrip("/")
    if t.lower().startswith("buy "):
        try:
            return await buy(t[4:])
        except Exception as e:
            return {"ok": False, "text": f"buy failed: {e}"}
    return run(t, who)

def skip(mint):
    nxt = util.night_start(config.get("desk.report_time")) + dt.timedelta(days=1)
    db.insert("skips", mint=mint, until=util.iso(nxt))

def status() -> str:
    hb = {r["agent"]: r["ts"] for r in db.q("SELECT * FROM heartbeats")}
    ps = account.open_positions()
    lines = [f"{config.get('desk.mode')} · balance ${account.equity():,.2f} · free ${account.free():,.2f} · {len(ps)} open"]
    for p in ps:
        c = db.coin(p["mint"]) or {"mint": p["mint"]}
        lines.append(f"- {_nm(c)} ${p['size_usd']:.2f} at {p['entry_price']:.8g} · [Sell on {links.VENUE}] {links.coin_url(p['mint'])}")
    lines.append("heartbeats " + ", ".join(f"{a} {util.local_hm(t)}" for a, t in hb.items()))
    return "\n".join(lines)
