# TQQQ/SHY 200-day trend runner (author's logic) on the Alpaca PAPER account.
# 2026-10-20 07:xx (user request, closer to the article):
#   * budget = Alpaca PAPER account equity * TREND_SHARE (0.35), not the $100 desk bank
#   * holdings = the account's TQQQ/SHY positions (the runner owns these symbols; STOCKS/CRYPTO never touch them)
#   * exits sell exactly the held qty; min trade = author's $25 (TREND_MIN_TRADE)
#   * skips while the account kill switch (alp_kill.json) is set for today; orders tagged alp-trend-*
#   * --dry-run prints everything and submits nothing; logs carry [RISK]/[SIZE]/[FILLS] tags
import os, sys, math, datetime as dt
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed
import desk_bank, alp_common as ac

if os.environ.get("ALPACA_PAPER", "1") != "1":
    sys.exit("refusing to run: ALPACA_PAPER must be 1 (paper only)")
KEY, SECRET = os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"]
trade = TradingClient(KEY, SECRET, paper=True)          # hard-wired paper endpoint
data  = StockHistoricalDataClient(KEY, SECRET)
SHARE    = float(os.environ.get("TREND_SHARE", "0.35"))
IN_BAND  = 1.01
OUT_BAND = 0.97
DRY = "--dry-run" in sys.argv

def qqq_closes(days=420):
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    bars = data.get_stock_bars(StockBarsRequest(symbol_or_symbols="QQQ", timeframe=TimeFrame.Day, start=start, feed=DataFeed.IEX)).df
    return bars.loc["QQQ"]["close"]

def want(have):
    c = qqq_closes()
    sma, last = c.rolling(200).mean().iloc[-1], c.iloc[-1]
    if math.isnan(sma):
        raise RuntimeError(f"SMA200 is NaN ({len(c)} bars)")
    inside = have.get("TQQQ", 0) > 0
    thr = sma * (OUT_BAND if inside else IN_BAND)
    target = "TQQQ" if last > thr else "SHY"
    print(f"[RISK] QQQ last={last:.2f} SMA200={sma:.2f} ({len(c)} bars, last bar {c.index[-1][1].date() if isinstance(c.index[-1], tuple) else c.index[-1].date()}) "
          f"ratio={last/sma:.4f} band={'OUT 0.97' if inside else 'IN 1.01'} threshold={thr:.2f} -> target {target}")
    return target

def run():
    """2026-10-20 07:xx (user request): sized on the ALPACA PAPER ACCOUNT equity x TREND_SHARE (article: 35%), the runner
    owns the account's TQQQ/SHY positions. Orders tagged alp-trend-* (not desk-*, so the $100 meme bank stays separate)."""
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    clock = trade.get_clock()
    print(f"[RISK] mode={'DRY-RUN' if DRY else 'LIVE-PAPER'} market_open={clock.is_open} next_open={clock.next_open}")
    if ac.kill_active():
        print("[RISK] account kill switch fired today -> flat, no orders"); return
    if not clock.is_open and not DRY:
        print("[RISK] market closed -> nothing to do"); return
    eq = float(trade.get_account().equity)
    pos = {p.symbol: p for p in trade.get_all_positions() if p.symbol in ("TQQQ", "SHY")}
    have = {s: float(p.market_value) for s, p in pos.items()}
    st = {"holdings": {s: {"qty": float(p.qty), "market_value": float(p.market_value)} for s, p in pos.items()}}
    budget = eq * SHARE
    min_trade = max(desk_bank.ALPACA_MIN_NOTIONAL, float(os.environ.get("TREND_MIN_TRADE", "25")))
    print(f"[SIZE] alpaca_paper_equity=${eq:,.2f} share={SHARE} budget=${budget:,.2f} min_trade=${min_trade:,.2f}")
    print(f"[SIZE] runner holdings: " + (", ".join(f"{s} {h['qty']:.6f} sh ${h['market_value']:.2f}" for s, h in st["holdings"].items()) or "none"))
    oo = [o for o in trade.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500)) if o.symbol in ("TQQQ", "SHY")]
    if oo:
        print(f"[RISK] {len(oo)} TQQQ/SHY order(s) still open -> skip to avoid double orders"); return
    target = want(have)
    for s in sorted(("TQQQ", "SHY"), key=lambda s: s == target):
        goal = budget if s == target else 0.0
        diff = goal - have.get(s, 0.0)
        if goal == 0 and have.get(s, 0) > 0:
            q = st["holdings"][s]["qty"]
            req = MarketOrderRequest(symbol=s, qty=round(q, 9), side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
                                     client_order_id=ac.coid("trend"))
            desc = f"SELL {s} qty={q:.6f} (exit, ~${have[s]:.2f})"
        elif abs(diff) >= min_trade:
            n = round(abs(diff), 2)
            if n < desk_bank.ALPACA_MIN_NOTIONAL:
                print(f"[SIZE] skip {s}: ${n:.2f} below Alpaca $1 minimum"); continue
            side = OrderSide.BUY if diff > 0 else OrderSide.SELL
            req = MarketOrderRequest(symbol=s, notional=n, side=side, time_in_force=TimeInForce.DAY,
                                     client_order_id=ac.coid("trend"))
            desc = f"{side.value.upper()} {s} notional=${n:.2f}"
        else:
            print(f"[SIZE] {s}: goal ${goal:.2f} have ${have.get(s,0):.2f} diff ${diff:+.2f} < min ${min_trade:.2f} -> no order"); continue
        why = ac.submit_block_reason(req.side)   # 2026-10-20 risk audit: kill switch / STOP_ALL re-checked right before every order
        if why:
            print(f"[RISK] BLOCKED {desc}: {why}"); continue
        if DRY:
            print(f"[FILLS] WOULD SUBMIT {desc} (dry-run, not sent)")
        else:
            o = trade.submit_order(req)
            print(f"[FILLS] {desc} submitted id={o.id} client_id={o.client_order_id} status={o.status.value}")

if __name__ == "__main__":
    run()
