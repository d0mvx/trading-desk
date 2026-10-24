"""Test harness: import the REAL desk modules but redirect every file they write to a temp dir.
Never touches live state (meme_positions.json, risk_state.json, logs, Alpaca). No network: callers mock it."""
import os, sys, tempfile, importlib, json, datetime as dt
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)

def iso_meme():
    import meme; importlib.reload(meme)
    tmp = tempfile.mkdtemp(prefix="desk_test_"); os.makedirs(f"{tmp}/logs")
    meme.DESK = tmp
    meme.POS = f"{tmp}/meme_positions.json"; meme.POS_LOCK = f"{tmp}/.pos.lock"
    meme.TRADES = f"{tmp}/logs/meme_trades.jsonl"; meme.RISKST = f"{tmp}/risk_state.json"
    meme.RISK_JOURNAL = f"{tmp}/logs/risk_state.jsonl"
    meme.LOGLINES = []
    meme.log = lambda l: meme.LOGLINES.append(l)
    import scan; scan.COOLDOWN_FILE = f"{tmp}/meme_cooldown.json"   # never write the live cooldown file from tests
    import entry_rules; importlib.reload(entry_rules)   # USER ORDER 2026-10-24 13:34: loss streak + drop log never touch the live files
    entry_rules.STREAK_FILE = f"{tmp}/loss_streak.json"; entry_rules.STREAK_LOCK = f"{tmp}/.loss_streak.lock"; entry_rules.DROP_LOG = f"{tmp}/logs/entry_rules_drops.jsonl"
    json.dump({"open": [], "closed": []}, open(meme.POS, "w"))
    return meme, tmp

def pos(token, sleeve="main", cost=1.0, venue="pumpswap", price=1.0, **kw):
    o = {"pool": "P" + token, "token": token, "name": token + " / SOL", "venue": venue, "entry_time": dt.datetime.now(dt.timezone.utc).isoformat(),
         "entry_mid": price, "entry_price": price, "qty": cost / price, "qty_initial": cost / price, "cost_usd": cost, "sol_usd": 150.0,
         "rent_sol": 0.00203928, "rent_usd": 0.3, "peak_price": price, "last_price": price, "tp_done": False, "tp_hits": [],
         "stop_loss": {"pumpswap": 0.20, "bonding_curve": 0.30}[venue], "entry_fee": 0.05, "simulated": True}
    if sleeve != "main": o["sleeve"] = sleeve
    o.update(kw); return o
