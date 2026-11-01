"""Risk (PART 5): every 15s poll open positions (approved: DexScreener by pool address), rules in order, PAPER exits."""
from __future__ import annotations
import asyncio, datetime as dt
from .. import db, util, config, bus, log, sources as S, chain, links, webpush, fees

L = log.get("risk")
NAME = "risk"
_misses: dict[int, int] = {}

def stop_pct_of(p) -> float:
    return round((1 - p["stop_price"] / p["entry_price"]) * 100, 4)

def decide(p: dict, price: float, now: dt.datetime, s: dict) -> tuple[dict, str | None]:
    """pure rules, in order. returns (updates, exit_reason)."""
    upd = {}
    peak = max(p["peak_price"] or price, price)
    upd["peak_price"] = peak
    # a tighter stop setting applies to open positions; never moves a stop down
    tighter = p["entry_price"] * (1 - s["risk.stop_pct"] / 100)
    stop_line = max(p["stop_price"], tighter)
    if stop_line != p["stop_price"]:
        upd["stop_price"] = stop_line
    if price <= stop_line:
        return upd, "stop"
    trail = bool(p["trail_active"])
    if not trail and price >= p["entry_price"] * (1 + s["risk.trail_start_pct"] / 100):
        trail = True; upd["trail_active"] = 1
    if trail and price <= peak * (1 - s["risk.trail_pct"] / 100):
        return upd, "trail"
    opened = util.parse(p["opened_at"])
    if now - opened >= dt.timedelta(hours=s["risk.timeout_h"]) and price < p["entry_price"] * (1 + s["risk.timeout_min_gain_pct"] / 100):
        return upd, "timeout"
    return upd, None

def exit_line(p, s) -> float:
    """the current exit line drawn on the Coin screen ('Risk trailing stop')."""
    line = p["stop_price"]
    if p["trail_active"]:
        line = max(line, p["peak_price"] * (1 - s["risk.trail_pct"] / 100))
    return line

async def close(p: dict, price: float, reason: str, v: dict | None, s: dict):
    name = (db.coin(p["mint"]) or {}).get("symbol") or util.short(p["mint"])
    exit_value = p["size_usd"] * price / p["entry_price"]
    out_cost = fees.side_cost(exit_value, v["liquidity"] if v else None, v["mcap"] if v else None, v["sol_usd"] if v else None,
                              s["fees.gas_sol_per_side"], s["fees.extra_slippage_pct"])["total_usd"] if v else exit_value * 0.0125
    fee_total = (p["fees_usd"] or 0) + out_cost
    pnl = exit_value - p["size_usd"] - fee_total
    pct = pnl / p["size_usd"] * 100
    db.x("UPDATE positions SET closed_at=?, exit_price=?, exit_reason=?, pnl_usd=?, fees_usd=? WHERE id=?",
         (util.iso(), price, reason, round(pnl, 4), round(fee_total, 4), p["id"]))
    sp = stop_pct_of(p)
    link = links.coin_url(p["mint"], "solana")
    if reason == "trail" or (reason in ("timeout", "pulled") and pnl >= 0):
        kind, title = "sold", f"Sold {name}"
        sub = "Risk · trailing stop" if reason == "trail" else ("Risk · dead money" if reason == "timeout" else "Risk · liquidity pulled")
        val = f"{'+' if pnl >= 0 else '-'}${abs(pnl):,.2f} · {pct:+.1f}%"
    else:
        kind, title = ("stopped", f"Stopped {name}") if reason == "stop" else ("sold", f"Sold {name}")
        sub = f"Risk · -{sp:g}% stop" if reason == "stop" else ("Risk · dead money" if reason == "timeout" else "Risk · liquidity pulled")
        val = f"-${abs(pnl):,.2f}" if reason == "stop" else f"{'+' if pnl >= 0 else '-'}${abs(pnl):,.2f} · {pct:+.1f}%"
    db.activity(kind, p["mint"], "Risk", title, sub, val)
    db.decide(NAME, p["mint"], name, f"{reason} at {price:.8g} · {val}", pnl >= 0)
    if reason == "trail":
        t, b = f"Sold {name} · +${pnl:,.2f} ({pct:+.1f}%)", "Risk · trailing stop"
    elif reason == "stop":
        t, b = f"{name} hit the -{sp:g}% stop · -${abs(pnl):,.2f}", "Risk · stop"
    elif reason == "timeout":
        t, b = f"Sell {name}, dead money · {pct:+.1f}% in {s['risk.timeout_h']:g}h", "Risk · timeout"
    else:
        t, b = f"Sell {name} now · liquidity pulled", f"{pct:+.1f}%"
    await webpush.push(t, b, p["mint"], "exit")
    out = {"agent": "risk", "mint": p["mint"], "name": name, "ts": util.iso(), "reason": reason, "entryPrice": p["entry_price"],
           "exitPrice": price, "peakPrice": max(p["peak_price"] or price, price), "pnlUsd": round(pnl, 2), "pct": round(pct, 2),
           "feesUsd": round(fee_total, 2), "stopPct": sp, "mode": p["mode"], "status": "closed", "link": link}
    bus.emit("exit", out)
    L.info("EXIT %s", out)
    return out

async def poll_once():
    s = config.all_settings()
    ps = db.q("SELECT * FROM positions WHERE closed_at IS NULL")
    if not ps:
        return
    pools = {}
    for p in ps:
        c = db.coin(p["mint"]) or {}
        if c.get("pool"): pools[c["pool"]] = p["mint"]
    pairs = await S.dex_pairs(list(pools))
    now = util.now()
    for p in ps:
        c = db.coin(p["mint"]) or {}
        v = chain.pair_view(pairs.get(c.get("pool")))
        name = c.get("symbol") or util.short(p["mint"])
        if v and v["liquidity"] is not None and v["liquidity"] <= 0:
            last = db.one("SELECT price FROM prices WHERE mint=? ORDER BY ts DESC LIMIT 1", (p["mint"],))
            await close(p, (last or {}).get("price") or p["entry_price"], "pulled", v, s); continue
        if not v or v["price"] is None:
            _misses[p["id"]] = _misses.get(p["id"], 0) + 1
            L.info("pos %d %s no price (%d)", p["id"], p["mint"], _misses[p["id"]])
            if _misses[p["id"]] == s["risk.no_price_polls"]:
                await webpush.push(f"{name}: no price for 1 min", "Risk · check pump.fun", p["mint"], "warn")
            continue
        _misses[p["id"]] = 0
        price = v["price"]
        db.price(p["mint"], price, v["vol_m5"])
        upd, reason = decide(p, price, now, s)
        if upd:
            db.x(f"UPDATE positions SET {','.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), p["id"]))
            p.update(upd)
        L.info("pos %d %s price=%.10g peak=%.10g stop=%.10g trail_line=%s action=%s", p["id"], p["mint"], price, p["peak_price"],
               p["stop_price"], f"{p['peak_price'] * (1 - s['risk.trail_pct'] / 100):.10g}" if p["trail_active"] else "-", reason or "hold")
        if reason:
            await close(p, price, reason, v, s)

async def run():
    while True:
        db.heartbeat(NAME)
        try:
            await poll_once()
        except S.RateLimited as e:
            L.warning("429, backing off 30s (missed polls ~2)"); await asyncio.sleep(30); continue
        except Exception as e:
            L.exception("risk poll error: %s", e)
        await asyncio.sleep(config.get("risk.poll_s"))
