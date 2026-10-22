"""Virtual desk bank for the paper desk.

desk_equity = start_capital + realized P&L + unrealized P&L, computed ONLY from our own
orders (client_order_id prefix 'desk-') filled since bank.started_at. Equivalent to
desk_cash + market value of desk holdings. The Alpaca paper account's $100k is ignored for sizing.
"""
import os, json, uuid, datetime as dt
from collections import defaultdict

DESK = os.path.expanduser("~/.desk")
ALPACA_MIN_NOTIONAL = 1.00

def load_bank():
    with open(f"{DESK}/bank.json") as f:
        return json.load(f)

def new_client_order_id(bank, tag):
    return f"{bank.get('order_prefix', 'desk-')}{tag}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"

def desk_orders(trade, bank):
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    after = dt.datetime.fromisoformat(bank["started_at"])
    out, until = [], None
    while True:   # page backwards through all orders since start
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=after, until=until, limit=500, direction="desc", nested=False)
        page = trade.get_orders(req)
        out += page
        if len(page) < 500: break
        until = page[-1].submitted_at
    pref = bank.get("order_prefix", "desk-")
    return [o for o in out if (o.client_order_id or "").startswith(pref)]

def last_prices(symbols):
    if not symbols: return {}
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest
    from alpaca.data.enums import DataFeed
    c = StockHistoricalDataClient(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"])
    r = c.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=list(symbols), feed=DataFeed.IEX))
    return {s: float(t.price) for s, t in r.items()}

def state(trade, bank=None, prices=None):
    """Replay desk fills (average-cost) -> holdings, cash, realized P&L, closed-trade wins/losses."""
    bank = bank or load_bank()
    orders = desk_orders(trade, bank)
    fills = []
    for o in orders:
        q = float(o.filled_qty or 0)
        if q > 0 and o.filled_avg_price:
            fills.append({"time": o.filled_at or o.updated_at, "symbol": o.symbol, "side": str(o.side.value),
                          "qty": q, "price": float(o.filled_avg_price), "id": str(o.id),
                          "client_order_id": o.client_order_id})
    fills.sort(key=lambda f: f["time"])
    qty, cost = defaultdict(float), defaultdict(float)
    cash, realized, wins, losses, closed = float(bank["start_capital"]), 0.0, 0, 0, []
    for f in fills:
        s, q, p = f["symbol"], f["qty"], f["price"]
        if f["side"] == "buy":
            qty[s] += q; cost[s] += q * p; cash -= q * p
        else:
            q = min(q, qty[s]) if qty[s] > 0 else q
            avg = cost[s] / qty[s] if qty[s] > 0 else p
            pnl = (p - avg) * q
            realized += pnl; cash += q * p
            cost[s] -= avg * q; qty[s] -= q
            if qty[s] < 1e-9: qty[s], cost[s] = 0.0, 0.0
            closed.append({**f, "pnl": round(pnl, 4)})
            if pnl > 0: wins += 1
            elif pnl < 0: losses += 1
        f["side"] = f["side"].upper()
    held = {s: q for s, q in qty.items() if q > 0}
    if prices is None:
        prices = last_prices(held.keys())
    holdings, unreal, mv_total = {}, 0.0, 0.0
    for s, q in held.items():
        px = prices.get(s, cost[s] / q)
        mv = q * px; u = mv - cost[s]
        holdings[s] = {"qty": q, "avg_cost": cost[s] / q, "price": px, "market_value": mv, "unrealized": u}
        unreal += u; mv_total += mv
    equity = float(bank["start_capital"]) + realized + unreal
    return {"start_capital": float(bank["start_capital"]), "started": bank["started"],
            "cash": cash, "holdings": holdings, "market_value": mv_total,
            "realized": realized, "unrealized": unreal, "equity": equity,
            "pnl": equity - float(bank["start_capital"]),
            "wins": wins, "losses": losses, "fills": fills, "closed_trades": closed,
            "open_orders": [o for o in orders if str(o.status.value) in ("new", "accepted", "pending_new", "partially_filled")]}
