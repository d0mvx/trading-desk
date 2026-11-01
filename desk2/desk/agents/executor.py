"""Executor (PART 5): arithmetic + 1 push. Never places an order. PAPER fills at the signal price at once."""
from __future__ import annotations
import asyncio
from .. import db, util, config, bus, log, sources as S, chain, links, webpush, account, fees

L = log.get("executor")
NAME = "executor"

def size_for(stack: float, free: float, liquidity: float | None, s: dict) -> tuple[float | None, str | None, str]:
    """returns (size, skip_reason, cap). Pure: tested by test_executor."""
    raw = stack * s["executor.stack_pct"] / 100
    size, cap = raw, "stack_pct"
    if liquidity is not None:
        pool_cap = liquidity * s["executor.max_pool_pct"] / 100
        if pool_cap < size:
            size, cap = pool_cap, "max_pool_pct"
    mt, mode = s["executor.min_ticket_usd"], s["executor.below_min"]
    if mode != "off" and size < mt:
        if mode == "bump":
            if free >= mt:
                size, cap = mt, "bump"
            else:
                return None, "no free stack", cap
        else:
            return None, f"under ${mt:,.2f}", cap
    if size > free:
        return None, "no free stack", cap
    return round(size, 2), None, cap

def buy_text(name, size, pct, audit, score, stop_pct, trail_pct):
    a = "Auditor 8/8" if audit == "8/8" else "Auditor OFF"
    return (f"Buy {name} · ${size:,.2f} · {pct:g}% of stack",
            f"{a} · Analyst {score} · stop -{stop_pct:g}% · trail {trail_pct:g}%")

async def execute(item: dict) -> dict:
    m = item["mint"]
    s = config.all_settings()
    coin = db.coin(m) or {}
    name = coin.get("symbol") or coin.get("name") or util.short(m)
    link = links.coin_url(m, "solana")
    mode = s["desk.mode"]
    night = util.iso(util.night_start(s["desk.report_time"]))
    out = {"agent": "executor", "mint": m, "signalPrice": None, "sizeUsd": None, "stackPct": None, "link": link, "mode": mode,
           "status": "skipped", "reason": None}
    if db.one("SELECT 1 FROM signals WHERE mint=? AND ts>=? AND status IN ('sent','bought')", (m, night)) or \
       db.one("SELECT 1 FROM positions WHERE mint=? AND closed_at IS NULL", (m,)):
        L.info("2nd pass on %s ignored", m); out["reason"] = "already signalled tonight"; return out
    if mode != "PAPER":
        out["reason"] = "LIVE locked"; return out
    v = chain.pair_view((await S.dex_pairs([coin["pool"]])).get(coin["pool"])) if coin.get("pool") else None
    stack, free = account.equity(), account.free()
    size, why, cap = size_for(stack, free, v["liquidity"] if v else None, s)
    reason = why
    if not reason and (not v or v["price"] is None):
        reason = "no price"
    if not reason and item.get("scan_liq") and v["liquidity"] is not None and \
            v["liquidity"] < item["scan_liq"] * (1 - s["executor.recheck_liq_drop_pct"] / 100):
        reason = "liquidity dropping"
    ap = (item.get("analyst") or {}).get("price")
    if not reason and ap and v["price"] > ap * (1 + s["executor.recheck_price_up_pct"] / 100):
        reason = "ran before the push"
    L.info("mint=%s stack=%.2f raw=%.2f cap=%s final=%s mode=%s reason=%s link=%s", m, stack,
           stack * s["executor.stack_pct"] / 100, cap, size, mode, reason, link)
    if reason:
        out["reason"] = reason
        db.x("INSERT INTO signals(mint,ts,price,size_usd,stack_pct,link,mode,status) VALUES(?,?,?,?,?,?,?,?)",
             (m, util.iso(), v["price"] if v else None, size, None, link, mode, "skipped"))
        db.activity("rejected", m, "Executor", f"Rejected {name}", f"Executor · {reason}", "Skipped")
        db.decide(NAME, m, name, f"Skipped · {reason}", False)
        return out
    pct = round(size / stack * 100, 1) if stack else 0
    price = v["price"]
    sid = db.x("INSERT INTO signals(mint,ts,price,size_usd,stack_pct,link,mode,status) VALUES(?,?,?,?,?,?,?,?)",
               (m, util.iso(), price, size, pct, link, mode, "sent"))
    bus.emit("signal", {"mint": m, "name": name, "price": price, "size": size, "pct": pct, "link": link, "mode": mode})
    score = (item.get("analyst") or {}).get("score")
    t, b = buy_text(name, size, pct, item.get("audit", "8/8"), score, s["risk.stop_pct"], s["risk.trail_pct"])
    res = None
    for i in range(3):
        try:
            res = await webpush.push(t, b, m, "buy"); break
        except Exception as e:
            L.warning("push failed try %d: %s", i + 1, e); await asyncio.sleep(2)
    if res is None:
        L.warning("push failed, PAPER fills anyway")
    # PAPER: fill at the signal price at once
    fc = fees.side_cost(size, v["liquidity"], v["mcap"], v["sol_usd"], s["fees.gas_sol_per_side"], s["fees.extra_slippage_pct"])
    stop_price = price * (1 - s["risk.stop_pct"] / 100)
    pid = db.x("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode) VALUES(?,?,?,?,?,?,?,?,?)",
               (m, util.iso(), price, size, price, stop_price, 0, round(fc["total_usd"], 4), mode))
    db.x("UPDATE signals SET status='bought' WHERE id=?", (sid,))
    db.activity("bought", m, "Executor", f"Bought {name}", f"Executor · {util.local_hm(util.iso())}", f"${size:,.2f} · {pct:g}% of stack")
    db.decide(NAME, m, name, f"Filled ${size:,.2f} · {pct:g}% of stack ({cap})", True)
    bus.emit("fill", {"mint": m, "name": name, "price": price, "size": size, "pct": pct, "position": pid, "mode": mode})
    out.update(signalPrice=price, sizeUsd=size, stackPct=pct, status="bought")
    return out

async def run():
    while True:
        item = await bus.to_executor.get()
        db.heartbeat(NAME)
        while db.paused(NAME):
            await asyncio.sleep(5)
        try:
            await execute(item)
        except S.RateLimited:
            await asyncio.sleep(30); await bus.to_executor.put(item)
        except Exception as e:
            L.exception("executor crash %s: %s", item.get("mint"), e)
