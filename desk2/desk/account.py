"""PAPER account: equity = start stack + realized PnL + unrealized PnL of open positions (last price)."""
from __future__ import annotations
from . import db, config

def last_price(mint):
    r = db.one("SELECT price FROM prices WHERE mint=? AND price IS NOT NULL ORDER BY ts DESC LIMIT 1", (mint,))
    return r["price"] if r else None

def open_positions(mode=None):
    mode = mode or config.get("desk.mode")
    return db.q("SELECT * FROM positions WHERE closed_at IS NULL AND mode=?", (mode,))

def realized(mode="PAPER") -> float:
    r = db.one("SELECT COALESCE(SUM(pnl_usd),0) s FROM positions WHERE closed_at IS NOT NULL AND mode=?", (mode,))
    return r["s"]

def unrealized(mode="PAPER") -> float:
    s = 0.0
    for p in open_positions(mode):
        entry = p["entry_price"]
        if not entry:
            continue
        lp = last_price(p["mint"]) or entry
        s += p["size_usd"] * (lp / entry - 1) - (p["fees_usd"] or 0)
    return s

def equity() -> float:
    mode = config.get("desk.mode")
    if mode == "LIVE":
        return config.get("desk.live_stack")
    return config.get("desk.paper_start_stack") + realized("PAPER") + unrealized("PAPER")

def in_positions() -> float:
    return sum(p["size_usd"] for p in open_positions())

def free() -> float:
    mode = config.get("desk.mode")
    base = config.get("desk.paper_start_stack") + realized("PAPER") if mode == "PAPER" else config.get("desk.live_stack")
    return base - in_positions()
