"""Experiment tags: every pass that only happened because of a loosened/new rule carries a tag, so each change can be
measured on its own (GET /api/experiments, decisions [tags], positions.tags, shadow.tags).

  waiting_room_liq  scanner pass after the pool was first seen under scanner.min_liquidity_usd
  top10_30          scanner pass with top-10 between the old 25% and the current max
  pullback          h1 rocket that passed after a pullback from its room peak (scanner.rocket_pullback_*)
  established       coin from the established scanner (not a fresh graduate)
  bundled_6         auditor pass with 5-6 bundled wallets (old limit: 5 = red)
  jev_loose         analyst pass that the old Jev gate (0.70 / 0.65 / 0.30 / 70) would have rejected
  jev_plus          analyst verdict built with the extra Jev data (analyst.extra_data_on)
  half_size         executor used executor.borderline_stack_pct for a borderline pass
"""
from __future__ import annotations
from . import db, util

TAGS = ["waiting_room_liq", "established", "top10_30", "jev_loose", "bundled_6", "pullback", "jev_plus", "half_size"]
# the rules as they were before the loosening (2026-11-04); used only to label passes
OLD = {"scanner.max_top10_pct": 25, "auditor.max_bundled": 5, "analyst.min_alive_6h": 0.70, "analyst.min_organic": 0.65,
       "analyst.max_chase": 0.30, "analyst.min_score": 70}

def add(item: dict, tag: str, stage: str):
    """add a tag to a pipeline item (and record the tagged pass once per item/stage)."""
    t = item.setdefault("tags", [])
    if tag not in t:
        t.append(tag)
    db.insert("tag_events", mint=item["mint"], ts=util.iso(), tag=tag, stage=stage)
    c = db.coin(item["mint"]) or {}
    have = set(filter(None, (c.get("tags") or "").split(",")))
    if tag not in have:
        db.upsert_coin(item["mint"], tags=",".join(sorted(have | {tag})))

def of(item: dict) -> list[str]:
    return list(item.get("tags") or [])

def s(tags) -> str | None:
    return ",".join(sorted(set(tags))) if tags else None

def experiments() -> dict:
    from . import account
    out = {}
    for tag in TAGS:
        ev = db.q("SELECT stage, COUNT(DISTINCT mint) n FROM tag_events WHERE tag=? GROUP BY stage", (tag,))
        pos = db.q("SELECT * FROM positions WHERE ','||IFNULL(tags,'')||',' LIKE ?", (f"%,{tag},%",))
        closed = [p for p in pos if p["closed_at"]]
        opn = [p for p in pos if not p["closed_at"]]
        unreal = 0.0
        for p in opn:
            last = account.last_price(p["mint"]) or p["entry_price"]
            unreal += p["size_usd"] * (last / p["entry_price"] - 1) - (p["fees_usd"] or 0)
        realized = sum(p["pnl_usd"] or 0 for p in closed)
        out[tag] = {"passed": {e["stage"]: e["n"] for e in ev},
                    "coins": db.one("SELECT COUNT(DISTINCT mint) n FROM tag_events WHERE tag=?", (tag,))["n"],
                    "trades": len(pos), "open": len(opn), "closed": len(closed),
                    "wins": sum(1 for p in closed if (p["pnl_usd"] or 0) > 0),
                    "pnl_realized_usd": round(realized, 2), "pnl_unrealized_usd": round(unreal, 2),
                    "pnl_usd": round(realized + unreal, 2)}
    first = db.one("SELECT MIN(ts) t FROM tag_events")
    return {"mode": "PAPER", "since": first["t"] if first else None, "tags": out}
