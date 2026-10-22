#!/usr/bin/env python3
"""Account kill switch (Alpaca PAPER), every 30 min: if equity < last_equity x 0.96 (down 4% vs previous close)
-> DELETE /v2/positions?cancel_orders=true (close_all_positions(cancel_orders=True)) on the PAPER account and stay
flat for the rest of the New York day (alp_kill.json; TREND/STOCKS/CRYPTO skip while it is set).
Meme sleeve is simulated and keeps its own 4% daily drawdown rule. Usage: killswitch.py [--dry-run] [--simulate-drop PCT]
2026-10-20 risk audit: on fire -> journal + alp_kill.json FIRST, then cancel_orders() explicitly and verify no open orders remain
(up to CANCEL_TRIES re-checks), THEN close all positions. kill_active() fails closed on a corrupt state file."""
import os, sys, json, time, datetime as dt
sys.path.insert(0, os.path.expanduser("~/.desk")); import alp_common as ac
LIMIT = 0.04; DRY = "--dry-run" in sys.argv
CANCEL_TRIES, CANCEL_WAIT_S = 5, 1.0

def cancel_then_verify(tc):
    """Cancel every open order, then re-read open orders until none remain. Returns (n_cancel_calls, n_still_open)."""
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    left, calls = None, 0
    for _ in range(CANCEL_TRIES):
        try: tc.cancel_orders(); calls += 1
        except Exception as e: ac.log("KILL", f"cancel_orders failed {type(e).__name__}")
        try: left = len(tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500)))
        except Exception as e: ac.log("KILL", f"get_orders failed {type(e).__name__}"); left = -1
        if left == 0: break
        time.sleep(CANCEL_WAIT_S)
    return calls, left
def main():
    tc = ac.trading(); a = tc.get_account(); eq, last = float(a.equity), float(a.last_equity)
    if "--simulate-drop" in sys.argv: eq = last * (1 - float(sys.argv[sys.argv.index("--simulate-drop") + 1]) / 100); DRY = True
    else: DRY = "--dry-run" in sys.argv
    chg = eq / last - 1 if last else 0.0
    st = {"at": dt.datetime.now(ac.BER).isoformat(timespec="seconds"), "equity": eq, "last_equity": last, "change": round(chg, 5), "limit": -LIMIT,
          "killed_today": ac.kill_active()}
    if ac.kill_active():
        try: json.load(open(ac.KILL)); unreadable = False
        except FileNotFoundError: unreadable = False
        except (ValueError, OSError): unreadable = True
        st["result"] = ("kill state file unreadable -> FAIL CLOSED (no Alpaca orders until alp_kill.json is fixed/removed)" if unreadable
                        else "already fired today -> flat")
    elif last and eq < last * (1 - LIMIT):
        if DRY:
            st["result"] = f"WOULD FIRE (dry-run): equity {chg:+.2%} vs last_equity -> DELETE /v2/positions?cancel_orders=true"
        else:
            ac.write_kill({"date": ac.ny_today(), "fired_at": st["at"], "equity": eq, "last_equity": last, "change": chg})
            calls, left = cancel_then_verify(tc)
            res = tc.close_all_positions(cancel_orders=True)
            st["result"] = (f"FIRED: equity {chg:+.2%} < -{LIMIT:.0%} -> orders cancelled first ({calls} cancel call(s), {left} still open), "
                            f"then closed {len(res)} position(s), flat rest of NY day")
    else:
        st["result"] = f"ok ({chg:+.2%} vs last_equity)"
    ac.log("KILL", f"equity ${eq:,.2f} last_equity ${last:,.2f} -> {st['result']}")
    if "--simulate-drop" not in sys.argv: ac.write_json(f"{ac.DESK}/kill_state.json", st)
if __name__ == "__main__":
    main()
