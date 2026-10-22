"""Shared helpers for the Alpaca PAPER sleeves (TREND runner, STOCKS, CRYPTO, account kill switch).
PAPER ONLY: TradingClient(paper=True) is hard-wired and ALPACA_PAPER must be 1. Keys are read from
~/.desk/alpaca.env and never printed. Alpaca-sleeve orders use client_order_id prefix 'alp-<sleeve>-' so the
$100 virtual meme bank (desk_bank.py, prefix 'desk-') never mixes with the Alpaca account book."""
import os, sys, json, glob, uuid, datetime as dt
from zoneinfo import ZoneInfo
DESK = os.path.expanduser("~/.desk")
NY, BER, UTC = ZoneInfo("America/New_York"), ZoneInfo("Europe/Berlin"), dt.timezone.utc
KILL = f"{DESK}/alp_kill.json"
RUNNER_SYMBOLS = {"TQQQ", "SHY"}          # owned by the TREND runner only; STOCKS/CRYPTO Fills never touch them
CRYPTO_SYMBOLS = {"BTC/USD", "ETH/USD", "SOL/USD"}
DIAL_MAX_AGE_H = 26

def load_env():
    # 2026-10-22 github: ALPACA_KEY + ALPACA_SECRET from the environment (GitHub Actions secrets) win; otherwise
    # ~/.desk/alpaca.env is loaded exactly as before (box). Paper check below is unchanged.
    for f in (() if os.environ.get("ALPACA_KEY") and os.environ.get("ALPACA_SECRET") else ("alpaca.env",)):
        p = f"{DESK}/{f}"
        if os.path.exists(p):
            for l in open(p):
                l = l.strip()
                if l and not l.startswith("#") and "=" in l:
                    k, v = l.split("=", 1); os.environ[k.strip()] = v.strip().strip('"\'')   # file is the source of truth
    if os.environ.get("ALPACA_PAPER", "1") != "1":
        sys.exit("refusing to run: ALPACA_PAPER must be 1 (paper only)")

def trading():
    load_env()
    from alpaca.trading.client import TradingClient
    return TradingClient(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"], paper=True)   # PAPER endpoint only

def stock_data():
    load_env()
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"])

def coid(sleeve):
    return f"alp-{sleeve}-{dt.datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"

def ny_today(): return dt.datetime.now(NY).date().isoformat()

KILL_JOURNAL = None      # default f"{DESK}/logs/alp_kill.jsonl" (resolved at call time so tests can redirect DESK)
STOP_FILE = None         # default f"{DESK}/STOP_ALL"

def _kj(): return KILL_JOURNAL or f"{DESK}/logs/alp_kill.jsonl"

def _journal_fired_today():
    try:
        for l in open(_kj()):
            try:
                if json.loads(l).get("date") == ny_today(): return True
            except ValueError: continue
    except FileNotFoundError: pass
    return False

def kill_active():
    """True if the account kill switch fired today (New York date): Alpaca sleeves stay flat for the rest of the day.
    2026-10-20 (risk audit): FAIL CLOSED. A corrupt/unreadable alp_kill.json -> True (no trading until a human fixes it);
    a deleted alp_kill.json is recovered from the append-only journal logs/alp_kill.jsonl."""
    try: k = json.load(open(KILL))
    except FileNotFoundError: return _journal_fired_today()
    except (ValueError, OSError): return True
    if not isinstance(k, dict): return True
    return k.get("date") == ny_today() or _journal_fired_today()

def write_kill(rec):
    """Persist a kill: journal line first (append-only), then the state file."""
    os.makedirs(os.path.dirname(_kj()), exist_ok=True)
    with open(_kj(), "a") as f: f.write(json.dumps(rec, default=str) + "\n")
    write_json(KILL, rec)

def stop_all():
    """Manual STOP ALL switch: the file ~/.desk/STOP_ALL blocks every NEW BUY on every sleeve (exits/stops still run)."""
    return os.path.exists(STOP_FILE or f"{DESK}/STOP_ALL")

def submit_block_reason(side):
    """Re-checked right before every Alpaca submit_order. Kill active -> block everything; STOP_ALL -> block buys."""
    if kill_active(): return "kill switch active today"
    if str(getattr(side, "value", side)).lower() == "buy" and stop_all(): return "STOP_ALL file present"
    return None

def latest_dial():
    files = sorted(glob.glob(f"{DESK}/dial/*.json"))
    if not files: return None, None
    d = json.load(open(files[-1]))
    age = (dt.datetime.now(UTC) - dt.datetime.fromisoformat(d["generated_at"])).total_seconds() / 3600
    return d, age

def log(sleeve, line, logfile=None):
    s = f"{dt.datetime.now(BER):%Y-%m-%d %H:%M:%S %Z} [{sleeve}] {line}"
    print(s, flush=True)
    with open(logfile or f"{DESK}/logs/alpaca_sleeves.log", "a") as f: f.write(s + "\n")

def write_json(path, obj):
    tmp = path + ".tmp"; json.dump(obj, open(tmp, "w"), indent=1, default=str); os.replace(tmp, path)
