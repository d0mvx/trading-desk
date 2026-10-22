#!/usr/bin/env python3
"""STOCKS sleeve (Alpaca PAPER). Fills at 15:45 America/New_York, Mon-Fri (cron via tz_gate.sh).
Budget = Alpaca paper account equity x 0.50 x stocks_dial (Quant; floored to 0.25 grid, never rounded up).
Names: DRIFT + INSIDERS lists (lists/drift.json, lists/insiders.json), max 16, equal weight.
  priority: held names still on a list -> names on BOTH lists -> alternate DRIFT (by surprise) / INSIDERS (by $).
  A list with status null (could not be built honestly from free data) = HOLD: its held names are kept, no new buys from it.
RISK: stocks_dial < 0.50 -> whole sleeve to cash; a held name that dropped off BOTH lists -> sell (at this 15:45 run);
  dial missing/stale (>26h) -> hold everything, no orders; kill switch fired today -> no orders.
Never touches TQQQ/SHY (TREND runner) or crypto positions. Usage: stocks.py [--dry-run]
2026-10-20 risk audit: a held name above 10% of equity is trimmed even inside the 25% tolerance; no top-up buys of a held name
below its average entry (no averaging down); kill switch / STOP_ALL re-checked right before every submit."""
import os, sys, json, math, datetime as dt
sys.path.insert(0, os.path.expanduser("~/.desk")); import alp_common as ac
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
SHARE, MAX_NAMES, MAX_NAME_PCT, REBAL_TOL, LIST_MAX_AGE_H = 0.50, 16, 0.10, 0.25, 30
DRY = "--dry-run" in sys.argv
STATE = f"{ac.DESK}/stocks_state.json"; BOOK = f"{ac.DESK}/stocks_book.json"
L = lambda s: ac.log("STOCKS", s)

def load_list(name):
    p = f"{ac.DESK}/lists/{name}.json"
    try: d = json.load(open(p))
    except (FileNotFoundError, ValueError): return None, f"{name}.json missing"
    age = (dt.datetime.now(ac.UTC) - dt.datetime.fromisoformat(d["generated_at"])).total_seconds() / 3600
    if d.get("status") != "ok" or d.get("names") is None: return None, d.get("reason") or "status null"
    if age > LIST_MAX_AGE_H: return None, f"list is {age:.0f}h old"
    return d["names"], None

def main():
    tc = ac.trading(); run = {"at": dt.datetime.now(ac.BER).isoformat(timespec="seconds"), "dry": DRY, "orders": [], "notes": []}
    def done(msg):
        L(msg); run["result"] = msg; ac.write_json(STATE, run); return 0
    clock = tc.get_clock()
    if ac.kill_active(): return done("kill switch fired today -> no orders")
    if not clock.is_open and not DRY: return done("market closed -> nothing to do")
    acct = tc.get_account(); eq = float(acct.equity); run["equity"] = eq
    dial, age = ac.latest_dial()
    sd = None if not dial else dial["dial"].get("stocks")
    pos = {p.symbol: p for p in tc.get_all_positions() if str(p.asset_class.value) == "us_equity" and p.symbol not in ac.RUNNER_SYMBOLS}
    try: book = json.load(open(BOOK))
    except (FileNotFoundError, ValueError): book = {}
    run["held"] = {s: round(float(p.market_value), 2) for s, p in pos.items()}
    if dial is None or age > ac.DIAL_MAX_AGE_H: return done(f"stocks dial missing/stale ({age and round(age,1)}h) -> HOLD, no orders")
    run["dial"] = sd
    open_o = [o for o in tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500)) if (o.client_order_id or "").startswith("alp-stocks-")]
    if open_o and not DRY: return done(f"{len(open_o)} stocks order(s) still open -> skip")
    drift, dr = load_list("drift"); ins, ir = load_list("insiders")
    run["lists"] = {"DRIFT": [n["symbol"] for n in drift] if drift is not None else None, "DRIFT_reason": dr,
                    "INSIDERS": [n["symbol"] for n in ins] if ins is not None else None, "INSIDERS_reason": ir}
    L(f"equity ${eq:,.2f} | stocks dial {sd} (age {age:.1f}h) | DRIFT {'null: ' + dr if drift is None else len(drift)} | INSIDERS {'null: ' + ir if ins is None else len(ins)} | held {sorted(pos)}")
    sells, target = [], []
    if sd < 0.50:
        sells = [(s, "stocks dial < 0.50 -> sleeve to cash") for s in pos]
    else:
        dset = {n["symbol"] for n in drift or []}; iset = {n["symbol"] for n in ins or []}
        for s in pos:
            src = book.get(s, {}).get("lists", [])
            on = (s in dset) or (s in iset)
            held_by_null = (drift is None and ("DRIFT" in src or not src)) or (ins is None and ("INSIDERS" in src or not src))
            if on or held_by_null: target.append(s)
            else: sells.append((s, "dropped off both lists"))
        both = [n["symbol"] for n in (ins or []) if n["symbol"] in dset]
        dl = [n["symbol"] for n in drift or []]; il = [n["symbol"] for n in ins or []]
        order = both + [x for pair in zip(dl, il) for x in pair] + dl[len(il):] + il[len(dl):]
        for s in order:
            if len(target) >= MAX_NAMES: break
            if s not in target and s not in ac.RUNNER_SYMBOLS: target.append(s)
    budget = eq * SHARE * (sd if sd >= 0.5 else 0)
    per = min(budget / len(target), MAX_NAME_PCT * eq) if target else 0.0
    run.update({"budget": round(budget, 2), "per_name": round(per, 2), "target": target})
    for s in target: book.setdefault(s, {"lists": []}); book[s]["lists"] = sorted({*book[s]["lists"], *(["DRIFT"] if drift and s in {n['symbol'] for n in drift} else []), *(["INSIDERS"] if ins and s in {n['symbol'] for n in ins} else [])})
    L(f"budget ${budget:,.2f} = equity x {SHARE} x dial {sd} | {len(target)} names x ${per:,.2f} | sells {[s for s, _ in sells]}")
    def submit(req, desc):
        why = ac.submit_block_reason(req.side)      # re-checked right before every order (kill switch / STOP_ALL)
        if why: L(f"[RISK] BLOCKED {desc}: {why}"); run["notes"].append(f"blocked {desc}: {why}"); return
        run["orders"].append(desc)
        if DRY: L(f"[FILLS] WOULD SUBMIT {desc} (dry-run)"); return
        try: o = tc.submit_order(req); L(f"[FILLS] {desc} -> id {o.id} {o.status.value}")
        except Exception as e: L(f"[FILLS] {desc} FAILED {str(e)[:160]}"); run["notes"].append(f"{desc} failed")
    for s, why in sells:
        if s in ac.RUNNER_SYMBOLS: continue
        q = float(pos[s].qty)
        submit(MarketOrderRequest(symbol=s, qty=q, side=OrderSide.SELL, time_in_force=TimeInForce.DAY, client_order_id=ac.coid("stocks")), f"SELL {s} qty {q} ({why})")
        book.pop(s, None)
    from alpaca.data.requests import StockLatestTradeRequest
    from alpaca.data.enums import DataFeed
    px = {}
    if target:
        try: px = {k: float(v.price) for k, v in ac.stock_data().get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=target, feed=DataFeed.IEX)).items()}
        except Exception as e: L(f"latest prices failed {type(e).__name__}")
    for s in target:
        have = float(pos[s].market_value) if s in pos else 0.0
        diff = per - have
        over_cap = s in pos and have > MAX_NAME_PCT * eq          # 10%-of-equity cap is enforced even inside the rebalance tolerance
        if s in pos and abs(diff) < REBAL_TOL * per and not over_cap: continue
        if diff < 0 and s in pos:
            q = round(min(float(pos[s].qty), -diff / max(px.get(s) or float(pos[s].current_price), 1e-9)), 6)
            try: frac = tc.get_asset(s).fractionable
            except Exception: frac = False
            q = q if frac else math.floor(q)
            if q > 0: submit(MarketOrderRequest(symbol=s, qty=q, side=OrderSide.SELL, time_in_force=TimeInForce.DAY, client_order_id=ac.coid("stocks")), f"SELL {s} qty {q} (trim to ${per:,.0f})")
            continue
        if diff < 1: continue
        if s in pos:                                              # no averaging down: never top up a held name trading below its avg entry
            cur = px.get(s) or float(pos[s].current_price or 0); avg = float(pos[s].avg_entry_price or 0)
            if avg and cur and cur < avg:
                L(f"[RISK] skip top-up {s}: price {cur:.2f} < avg entry {avg:.2f} (no averaging down)"); run["notes"].append(f"{s} no averaging down"); continue
        try: a = tc.get_asset(s); frac, ok = a.fractionable, a.tradable
        except Exception: frac, ok = False, False
        if not ok: run["notes"].append(f"{s} not tradable"); continue
        if frac: submit(MarketOrderRequest(symbol=s, notional=round(diff, 2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY, client_order_id=ac.coid("stocks")), f"BUY {s} ${diff:,.2f}")
        else:
            p = px.get(s); q = math.floor(diff / p) if p else 0
            if q >= 1: submit(MarketOrderRequest(symbol=s, qty=q, side=OrderSide.BUY, time_in_force=TimeInForce.DAY, client_order_id=ac.coid("stocks")), f"BUY {s} {q} sh (~${q*p:,.2f}, not fractionable)")
    if not DRY: ac.write_json(BOOK, book)
    return done(f"{'DRY-RUN ' if DRY else ''}{len(run['orders'])} order(s)")

if __name__ == "__main__":
    sys.exit(main())
