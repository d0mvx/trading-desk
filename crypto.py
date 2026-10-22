#!/usr/bin/env python3
"""CRYPTO sleeve (Alpaca PAPER). Fills at 20:05 America/New_York, every day (cron via tz_gate.sh).
Budget = Alpaca paper account equity x 0.15 x crypto_dial. Targets = Quant crypto_targets (top-2 POSITIVE 12-1 month
momentum of BTC/ETH/SOL, equal weight; none positive -> cash). RISK: crypto_dial < 0.50 or a coin out of the targets
-> sell it at 20:05. Dial missing/stale -> hold, no orders. Kill switch fired today -> no orders. Usage: crypto.py [--dry-run]"""
import os, sys, json, datetime as dt
sys.path.insert(0, os.path.expanduser("~/.desk")); import alp_common as ac
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
SHARE, REBAL_TOL = 0.15, 0.25
DRY = "--dry-run" in sys.argv; STATE = f"{ac.DESK}/crypto_state.json"
L = lambda s: ac.log("CRYPTO", s)

def main():
    tc = ac.trading(); run = {"at": dt.datetime.now(ac.BER).isoformat(timespec="seconds"), "dry": DRY, "orders": []}
    def done(msg):
        L(msg); run["result"] = msg; ac.write_json(STATE, run); return 0
    if ac.kill_active(): return done("kill switch fired today -> no orders")
    eq = float(tc.get_account().equity); run["equity"] = eq
    dial, age = ac.latest_dial()
    pos = {p.symbol.replace("USD", "/USD") if "/" not in p.symbol else p.symbol: p for p in tc.get_all_positions() if str(p.asset_class.value) == "crypto"}
    run["held"] = {s: round(float(p.market_value), 2) for s, p in pos.items()}
    if dial is None or age > ac.DIAL_MAX_AGE_H: return done(f"crypto dial missing/stale -> HOLD, no orders")
    cd = dial["dial"]["crypto"]; w = dial["crypto_targets"].get("weights") or {}
    if dial["crypto_targets"].get("scores") == {} : return done("crypto momentum scores missing -> HOLD")
    tgt = {f"{k}/USD": v for k, v in w.items()} if cd >= 0.5 else {}
    budget = eq * SHARE * cd if cd >= 0.5 else 0.0
    run.update({"dial": cd, "targets": tgt, "scores": dial["crypto_targets"].get("scores"), "budget": round(budget, 2)})
    L(f"equity ${eq:,.2f} | crypto dial {cd} | 12-1m momentum {dial['crypto_targets'].get('scores')} -> targets {tgt or 'cash'} | budget ${budget:,.2f} | held {run['held'] or 'none'}")
    open_o = [o for o in tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500)) if (o.client_order_id or "").startswith("alp-crypto-")]
    if open_o and not DRY: return done(f"{len(open_o)} crypto order(s) still open -> skip")
    def submit(req, desc):
        why = ac.submit_block_reason(req.side)      # 2026-10-20 risk audit: kill switch / STOP_ALL re-checked right before every order
        if why: L(f"[RISK] BLOCKED {desc}: {why}"); return
        run["orders"].append(desc)
        if DRY: L(f"[FILLS] WOULD SUBMIT {desc} (dry-run)"); return
        try: o = tc.submit_order(req); L(f"[FILLS] {desc} -> id {o.id} {o.status.value}")
        except Exception as e: L(f"[FILLS] {desc} FAILED {str(e)[:160]}")
    for s, p in pos.items():
        if s not in tgt:
            why = "crypto dial < 0.50" if cd < 0.5 else "out of momentum targets"
            submit(MarketOrderRequest(symbol=s, qty=float(p.qty_available or p.qty), side=OrderSide.SELL, time_in_force=TimeInForce.GTC, client_order_id=ac.coid("crypto")), f"SELL {s} qty {p.qty} ({why})")
    for s, wt in tgt.items():
        goal = budget * wt; have = float(pos[s].market_value) if s in pos else 0.0; diff = goal - have
        if s in pos and abs(diff) < REBAL_TOL * goal: continue
        if diff >= 1:
            submit(MarketOrderRequest(symbol=s, notional=round(diff, 2), side=OrderSide.BUY, time_in_force=TimeInForce.GTC, client_order_id=ac.coid("crypto")), f"BUY {s} ${diff:,.2f}")
        elif diff <= -1 and s in pos:
            q = round(min(float(pos[s].qty), -diff / float(pos[s].current_price)), 8)
            submit(MarketOrderRequest(symbol=s, qty=q, side=OrderSide.SELL, time_in_force=TimeInForce.GTC, client_order_id=ac.coid("crypto")), f"SELL {s} qty {q} (trim)")
    return done(f"{'DRY-RUN ' if DRY else ''}{len(run['orders'])} order(s)")

if __name__ == "__main__":
    sys.exit(main())
