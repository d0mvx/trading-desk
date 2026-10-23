#!/usr/bin/env python3
"""MEME sleeve (Solana / pump.fun): SCAN -> JUDGE -> SIZE -> FILLS (SIMULATED) and RISK poll.
No wallets, no real funds: fills are simulated at live GeckoTerminal prices with slippage + pump.fun fees.
Usage: meme.py pipeline | meme.py risk | meme.py state | meme.py dry (scan+judge+RugCheck, no fill, nothing persisted)"""
import os, sys, json, glob, math, fcntl, time, re, signal, contextlib, datetime as dt
from zoneinfo import ZoneInfo
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
import gt
from leads import lead_id, ltag   # 2026-10-20 research upgrade: lead IDs
try: import jev                          # optional Jev tie-breaker (inactive without a key)
except Exception: jev = None
BER, UTC = ZoneInfo("Europe/Berlin"), dt.timezone.utc
POS = f"{DESK}/meme_positions.json"; TRADES = f"{DESK}/logs/meme_trades.jsonl"; RISKST = f"{DESK}/risk_state.json"

# ---- pump.fun fees (https://pump.fun/docs/fees, "Last Updated: 17 October 2026") ----
BONDING_CURVE_FEE = 0.0125                 # 0.30% creator + 0.95% protocol + 0% LP
PUMPSWAP_SOL_TIERS = [  # (upper market cap in SOL, total fee) canonical PumpSwap pools, SOL-paired
    (420, .0125), (1470, .0120), (2460, .0115), (3440, .0110), (4420, .0105), (9820, .0100), (14740, .0095),
    (19650, .0090), (24560, .0085), (29470, .0080), (34380, .0075), (39300, .0070), (44210, .0065), (49120, .0060),
    (54030, .0055), (58940, .00525), (63860, .0050), (68770, .00475), (73681, .0045), (78590, .00425), (83500, .0040),
    (88400, .00375), (93330, .0035), (98240, .00325), (float("inf"), .0030)]
APP_PLATFORM_FEE = float(os.environ.get("PUMP_APP_FEE", "0.0045"))   # pump.fun web/mobile app fee, no referral (Terminal/3rd-party: 0)
NETWORK_FEE_USD = 0.002                    # ~Solana base+priority fee per tx (approximation)
BC_K = 30 * 1_073_000_000                  # pump.fun curve invariant: 30 virtual SOL x 1.073B virtual tokens
LATENCY_SLIP = 0.005                       # extra 0.5% for price moving between quote and fill
# 2026-10-20 19:5x (user-approved upgrade 5): realistic Solana costs, both sleeves (newpairs uses these functions too)
PRIORITY_FEE_USD = 0.04                    # priority fee per transaction (every buy and every partial/full sell)
ATA_RENT_SOL = 0.00203928                  # token-account rent, paid on the first buy of a token (1 position per coin -> every buy).
                                           # REFUNDABLE when the account is closed: modelled as a cash deposit locked while the
                                           # position is open and refunded on the full exit (the closing sell closes the account),
                                           # so it reduces free cash/sizing while open but nets to $0 P&L.

TICKET_PCT, LIQ_CAP, MIN_TICKET = 0.03, 0.02, 1.00   # 2026-10-20 01:5x: ticket 6% -> 3% x bank x dial (user-approved)
# 2026-10-21 00:2x USER ORDER: every meme buy (main + new pairs) uses a FIXED 10 EUR ticket (no % of bank, no dial).
# Stops/TPs/caps unchanged; still capped by 2% of pool liquidity and free cash. EURUSD from frankfurter (ECB) 2026-10-20.
FIXED_TICKET_EUR, EURUSD = 10.0, 1.1215
FIXED_TICKET_USD = round(FIXED_TICKET_EUR * EURUSD, 2)
MAX_OPEN = 6                                           # max open MAIN-sleeve positions, 1 per coin (token mint)
TOTAL_MAX_OPEN = 8                                     # 2026-10-20: overall cap incl. the NEW PAIRS sleeve (newpairs.py, max 2 of them)
EXIT_RATIO = 0.20; DAILY_DD = 0.20; DAILY_DD_ENABLED = False  # 2026-10-21 20:17 USER ORDER "hebe daily limit auf": daily drawdown halt OFF (SL/TP/caps unchanged)
   # 2026-10-21 USER ORDER "viel mehr machen": 4% -> 20%
DIAL_MAX_AGE_H = 24
VOL_MIN_AGE_H = 2.0       # volume-decay rule is off for pools younger than 2 h (no history to compare against)
# ---- RISK exits (checked every minute at live price) ----
# 2026-10-20 14:5x (user-approved): bonding-curve stop -20% -> -30% (curve coins swing 20%+ inside a minute; all 4 losers
# were stopped at -20..-25% on curve noise). PumpSwap stays -20%. The stop is frozen per position at entry (o["stop_loss"]),
# so a curve coin that graduates mid-trade keeps its -30%.
STOP_LOSS = {"bonding_curve": 0.30, "pumpswap": 0.20}
TRAIL_STOP = 0.25         # close all if mark <= peak mark x 0.75 ...
TRAIL_ARM = 0.15          # ... but only once peak mark >= entry fill x 1.15: then peak x 0.75 >= entry x 0.8625, i.e. always
# USER ORDER 2026-10-23 17:43 (Dominic, "Beides umsetzen"): PROFIT LOCK. Once the peak gain (peak mark vs entry fill) reached
# +LOCK_TRIGGER, the effective stop is max(trailing stop, entry fill x (1 + LOCK_FLOOR)) -> a +15% winner can no longer close
# at a loss. Main + new pairs (+ shadow, same exit_decision). Not learner-tunable (stops are not in the learner allowlist).
LOCK_TRIGGER = 0.15
LOCK_FLOOR = 0.05
                          # ABOVE the hard stop; before arming only the hard stop applies (no -25% trail undercutting -30%)
TAKE_PROFIT = 0.50        # sell half once when mark >= entry fill price x 1.50
TIME_STOP_MIN = 60        # close all 60 min after entry
# 2026-10-21 research I-18/V-01: SHADOW fields per final main pick (pick_shadow.py -> logs/pick_shadow.jsonl). They do NOT change
# any decision except the I-18 gate: I18_GATE_ENABLED=True (approved by Dominic 2026-10-21 19:24) skips a pick when the twin share
# >= I18_BLOCK_SHARE. Fail-open: timeout/missing data never block (logged). V-01 fresh count is shadow-only.
I18_GATE_ENABLED = True; I18_BLOCK_SHARE = 0.50; I18_MIN_BUYS = 5; PICK_SHADOW_TIMEOUT_S = 6   # min buys = OOS sample rule
# 2026-10-20 19:5x (user-approved upgrade 6): profit protection after a big run-up. Fractions are of the INITIAL qty:
# 50% at +50% (as before) + another 25% at +100%; trailing tightens -25% -> -20% once the peak is >= +100%.
MAIN_EXIT = {"tier": "main", "tp": [[0.50, 0.50], [1.00, 0.25]], "trail_arm": TRAIL_ARM, "trail": TRAIL_STOP, "trail_tight": [1.00, 0.20],
             "time_stop_min": TIME_STOP_MIN, "time_stop_only_if_not_profit": False, "max_hold_min": None}
# 2026-10-20 19:5x (upgrade 1): fast exits. cron starts `meme.py risk` every minute (flock -n .risk.lock, timeout 58); it runs
# RISK_CHECKS checks RISK_STEP_S apart (0/12/24/36/48 s), never starts one after RISK_LAST_START_S, SIGALRM hard stop at RISK_HARD_S.
# Prices: DexScreener /tokens/v1 batch (30 mints/call; limit 300 req/min) + on-chain curve read; 0 GeckoTerminal calls.
RISK_CHECKS, RISK_STEP_S, RISK_LAST_START_S, RISK_HARD_S = 5, 12, 50, 56
STALE_GT_S, STALE_WARN_S = 20, 60   # 2026-10-20 risk audit: no price >= 20 s -> GT fallback; >= 60 s -> log every check
POS_LOCK = f"{DESK}/.pos.lock"            # short lock around every read-modify-write of meme_positions.json (pipeline, newpairs, risk)
# ---- JUDGE gates (replace old score > 0 rule) ----
J_MIN_BUYERS_H1 = 50      # unique buyers last hour
J_MIN_BS_M15 = 1.2        # buys/sells last 15 min
J_MIN_BUYERS_PER_BUY = 0.25   # unique buyers / buys last hour (anti-bot)
J_PC_H1 = (10.0, 300.0)   # price change last hour, % (inclusive)
J_PC_H1_WATCH_MIN = 0.0   # watchlisted coin re-checked during its dip: momentum already proven -> h1 only needs to be >= 0%
try:   # 2026-10-22 SELF-LEARN (USER ORDER): learner_overrides.json may adjust allowlisted thresholds above (bounded, gated, kill switch)
    import learner as _learner; _learner.apply("meme", globals())
except Exception: pass
# ---- DIP entry (2026-10-20 14:5x, user-approved "buy the dip, not the top") ----
DIP_MIN = 0.12            # enter only if price is >= 12% below its 60-min high ...
DIP_MAX = 0.40            # ... but not > 40% below (trend broken; would sit 10% above a -30% stop's worth of further damage)
DIP_M5_MIN = -10.0        # ... and not in free fall: price change m5 >= -10%
DIP_WINDOW_MIN = 60       # high = max(GT 1-min OHLCV highs (<= 1 call/run), prices implied by GT m5/m15/m30/h1 changes,
                          #            prices observed while on the watchlist) over the last 60 min
WATCH_TTL_MIN = 60        # watchlist entry expires 60 min after it was added
WATCH_MAX = 40
OHLCV_PER_RUN = 1         # GT 1-min OHLCV calls per run: 6 lists + 1 multi + 1 OHLCV = 8 of the 9/min GT budget (no limiter waits)
# ---- RugCheck hard gates (api.rugcheck.xyz keyless) ----
RC_URL = "https://api.rugcheck.xyz/v1/tokens/{}/report"; RC_TIMEOUT = 5; RC_TTL = 600
RC_CACHE = f"{DESK}/rugcheck_cache.json"
RC_LP_LOCKED_MIN = 95.0; RC_CREATOR_MAX = 5.0; RC_HOLDER_MAX = 15.0; RC_INSIDERS_MAX = 10
JUDGE_BUDGET_S = 45       # stop judging after 45 s into the run (1-min cadence)

def now(): return dt.datetime.now(UTC)
def log(line):
    os.makedirs(f"{DESK}/logs", exist_ok=True)
    with open(f"{DESK}/logs/meme.log", "a") as f: f.write(f"{now().astimezone(BER):%Y-%m-%d %H:%M:%S %Z} {line}\n")
    print(line)

def venue_fee(venue, mcap_usd, sol_usd):
    if venue == "bonding_curve": return BONDING_CURVE_FEE
    mc_sol = (mcap_usd or 0) / (sol_usd or 1)
    return next(f for cap, f in PUMPSWAP_SOL_TIERS if mc_sol < cap)

def quote_reserve_usd(venue, price_usd, sol_usd, liq_usd):
    """SOL-side reserve (USD) a trade hits. Bonding curve: VIRTUAL SOL reserve from the same curve state as the
    scan's liquidity (vSOL = sqrt(k*price_SOL) = real_SOL + 30). PumpSwap CPMM: ~half of pool liquidity."""
    if venue == "bonding_curve" and price_usd and sol_usd:
        return math.sqrt(BC_K * price_usd / sol_usd) * sol_usd
    return (liq_usd or 0) / 2

def slippage(notional, reserve_usd):
    """constant-product price impact for a trade of `notional` USD against SOL reserve + latency buffer."""
    if reserve_usd <= 0: return 0.05
    return notional / reserve_usd + LATENCY_SLIP

def total_fee(notional, venue, mcap, sol_usd):
    r = venue_fee(venue, mcap, sol_usd) + APP_PLATFORM_FEE
    return notional * r + NETWORK_FEE_USD + PRIORITY_FEE_USD, r

def load_pos():
    try: return json.load(open(POS))
    except FileNotFoundError: return {"open": [], "closed": []}
def save_pos(p):
    tmp = POS + ".tmp"; json.dump(p, open(tmp, "w"), indent=1, default=str); os.replace(tmp, POS)
@contextlib.contextmanager
def poslock(wait=25.0, path=POS_LOCK):
    """Exclusive lock for a read-modify-write of meme_positions.json. Always reload the file INSIDE the lock."""
    f = open(path, "a+"); t = time.time()
    while True:
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except BlockingIOError:
            if time.time() - t > wait: f.close(); raise TimeoutError(f"{os.path.basename(path)} busy > {wait:.0f}s")
            time.sleep(0.05)
    try: yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN); f.close()

def trade_log(rec):
    with open(TRADES, "a") as f: f.write(json.dumps(rec, default=str) + "\n")

def meme_state(p=None):
    p = p or load_pos(); bank = json.load(open(f"{DESK}/bank.json"))
    start = float(bank["start_capital"]) * float(bank.get("sleeves", {}).get("meme", {}).get("weight", 1.0))
    realized = sum(c["pnl"] for c in p["closed"])
    cost = sum(o["cost_usd"] for o in p["open"])
    rent = sum(o.get("rent_usd") or 0 for o in p["open"])     # refundable token-account rent locked in open positions
    mark = sum(o["qty"] * (o.get("last_price") or o["entry_price"]) for o in p["open"])
    return {"start": start, "realized": realized, "unrealized": mark - cost, "cash": start + realized - cost - rent, "rent_locked": rent,
            "equity": start + realized + mark - cost, "open": p["open"], "closed": p["closed"],
            "wins": sum(1 for c in p["closed"] if c["pnl"] > 0), "losses": sum(1 for c in p["closed"] if c["pnl"] < 0)}

def desk_equity():
    """desk equity = $100 + Alpaca desk-order P&L (trend sleeve, paused -> ~0) + meme simulated P&L."""
    ms = meme_state(); alp = 0.0
    try:
        import desk_bank
        from alpaca.trading.client import TradingClient
        env = {k: os.environ[k] for k in ("ALPACA_KEY", "ALPACA_SECRET") if os.environ.get(k)}   # 2026-10-22 github: env first
        if len(env) < 2: env = dict(l.strip().split("=", 1) for l in open(f"{DESK}/alpaca.env") if "=" in l and not l.startswith("#"))
        st = desk_bank.state(TradingClient(env["ALPACA_KEY"].strip('"\''), env["ALPACA_SECRET"].strip('"\''), paper=True))
        alp = st["equity"] - st["start_capital"]
    except Exception as e:
        log(f"[RISK] alpaca desk P&L unavailable ({type(e).__name__}); using meme only")
    return ms["equity"] + alp, ms

RISK_JOURNAL = f"{DESK}/logs/risk_state.jsonl"   # 2026-10-20 risk audit: append-only copy of every day-open / halt record

def _journal_today():
    """Last journaled risk-state record for today's Berlin date (or None)."""
    today = now().astimezone(BER).date().isoformat(); last = None
    try:
        for l in open(RISK_JOURNAL):
            try: r = json.loads(l)
            except ValueError: continue
            # a halt stays sticky for the day; only an explicit bank-epoch reset record (USER ORDER, bank_reset) replaces it
            if r.get("date") == today: last = r if (r.get("epoch_reset") or not (last and last.get("halted") and not r.get("halted"))) else last
    except FileNotFoundError: pass
    return last

def risk_state():
    """risk_state.json; if it is missing or corrupt, recovered from the append-only journal (a halt survives a deleted/broken
    state file). Corrupt file and no journal record for today -> {"halted": True, "_corrupt": True} (fail closed)."""
    try: rs = json.load(open(RISKST))
    except FileNotFoundError: rs = None
    except ValueError: rs = {"halted": True, "_corrupt": True}
    j = _journal_today()
    if j and (rs is None or rs.get("_corrupt") or (rs.get("date") == j["date"] and j.get("halted") and not rs.get("halted"))):
        return dict(j)
    return rs or {}

def daily_halt_active():
    """True if the meme 4% daily drawdown halt is set for TODAY (Berlin), or the state is unreadable (fail closed)."""
    if not DAILY_DD_ENABLED: return False
    rs = risk_state()
    return bool(rs.get("halted")) and (rs.get("_corrupt") or rs.get("date") == now().astimezone(BER).date().isoformat())

def check_daily_dd(eq):
    """4% daily drawdown flat rule on desk equity (Berlin day). Returns True if halted. Persisted in risk_state.json AND the
    append-only journal, so a crash / re-run / deleted state file never resets the day-open equity or an active halt."""
    with poslock(path=f"{DESK}/.riskstate.lock"):
        rs = risk_state(); today = now().astimezone(BER).date().isoformat(); changed = False
        if rs.get("_corrupt"): rs = {}
        if rs.get("date") != today:
            rs = {"date": today, "day_open_equity": eq, "halted": False}; changed = True
        if not DAILY_DD_ENABLED:
            pass
        elif not rs["halted"] and eq < rs["day_open_equity"] * (1 - DAILY_DD):
            rs["halted"] = True; rs["halted_at"] = now().astimezone(BER).isoformat(timespec="seconds"); changed = True
            log(f"[RISK] DAILY DRAWDOWN {eq/rs['day_open_equity']-1:+.2%} breaches -{DAILY_DD:.0%} (open ${rs['day_open_equity']:.2f}, now ${eq:.2f}) -> FLAT + halt new entries today")
        if changed or not _journal_today():
            os.makedirs(os.path.dirname(RISK_JOURNAL), exist_ok=True)
            with open(RISK_JOURNAL, "a") as f: f.write(json.dumps(rs) + "\n")
        tmp = RISKST + ".tmp"; json.dump(rs, open(tmp, "w"), indent=1); os.replace(tmp, RISKST)
        return rs["halted"] and DAILY_DD_ENABLED

def book_add(o, sleeve_max, ticket_pct, total_max=None):
    """2026-10-20 risk audit: the ONLY way a (paper) position enters meme_positions.json, used by the main pipeline and
    newpairs. Under the positions lock it re-checks, against the file as it is NOW (concurrent runs): the daily-drawdown
    halt, the per-sleeve cap, the overall cap, one position per token (no re-buy / averaging into a held coin, also across
    sleeves, matched on mint and pool) and the ticket cap (cost <= ticket_pct x meme equity). Returns None if added, else
    the block reason. Raises TimeoutError if the lock is busy (callers retry next run)."""
    total_max = TOTAL_MAX_OPEN if total_max is None else total_max
    with poslock(path=POS_LOCK):
        if os.path.exists(f"{DESK}/STOP_ALL"): return "STOP_ALL file present (manual stop: no new buys; exits still run)"
        if daily_halt_active(): return "daily drawdown halt active"
        p = load_pos(); sl = o.get("sleeve") or "main"
        mine = [x for x in p["open"] if (x.get("sleeve") or "main") == sl]
        keys = {o.get("token"), o.get("pool")} - {None}
        if len(mine) >= sleeve_max: return f"max {sleeve_max} open {sl} positions reached"
        if len(p["open"]) >= total_max: return f"overall max {total_max} open positions reached"
        if any(keys & {x.get("token"), x.get("pool"), x.get("pool_original")} for x in p["open"]): return "already held (1 position per coin, no averaging)"
        cap = max(ticket_pct * meme_state(p)["equity"], FIXED_TICKET_USD) + 0.01   # fixed 10 EUR ticket allowed
        if float(o.get("cost_usd") or 0) > cap: return f"ticket ${o.get('cost_usd')} > cap ${cap:.2f}"
        p["open"].append(o); save_pos(p); trade_log({"type": "BUY", **o})
    return None

def latest_dial():
    files = sorted(glob.glob(f"{DESK}/dial/*.json"))
    if not files: return None, None
    d = json.load(open(files[-1])); age = (now() - dt.datetime.fromisoformat(d["generated_at"])).total_seconds() / 3600
    return d, age

def pools_multi(addrs, deadline=None):
    """GeckoTerminal multi-pool endpoint (1 call per 30 pools)."""
    out = {}
    for i in range(0, len(addrs), 30):
        d = gt.get("/networks/solana/pools/multi/" + ",".join(addrs[i:i + 30]), deadline=deadline)
        for p in d.get("data") or []: out[p["attributes"]["address"]] = p["attributes"]
    return out

def ds_prices(positions, timeout=10):
    """Risk prices via DexScreener /tokens/v1 (keyless, NOT the GeckoTerminal budget; up to 30 mints per call).
    Returns {pool: GT-like attributes}. Uses the held pool's pair; if a held bonding-curve coin has graduated
    (a PumpSwap pair exists), the most liquid PumpSwap pair is used and returned under the held pool key with
    '_migrated_to' set."""
    import requests
    mints = sorted({o["token"] for o in positions if o.get("token")}); out = {}
    errs = []
    for i in range(0, len(mints), 30):
        try:
            r = requests.get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(mints[i:i + 30]), timeout=timeout)
            r.raise_for_status(); pairs = r.json() or []
        except Exception as e:
            errs.append(e); continue
        for o in positions:
            mine = [x for x in pairs if (x.get("baseToken") or {}).get("address") == o["token"]]
            own = next((x for x in mine if x.get("pairAddress") == o["pool"]), None)
            swaps = sorted((x for x in mine if x.get("dexId") == "pumpswap"), key=lambda x: -((x.get("liquidity") or {}).get("usd") or 0))
            pick, mig = own, None
            if o["venue"] == "bonding_curve" and swaps: pick, mig = swaps[0], swaps[0]["pairAddress"]
            if not pick or not pick.get("priceUsd"): continue
            px, pn = float(pick["priceUsd"]), float(pick.get("priceNative") or 0)
            v = pick.get("volume") or {}
            out[o["pool"]] = {"base_token_price_usd": px, "quote_token_price_usd": (px / pn) if pn else o.get("sol_usd"),
                              "reserve_in_usd": (pick.get("liquidity") or {}).get("usd"), "market_cap_usd": pick.get("marketCap") or pick.get("fdv"),
                              "volume_usd": {"h1": v.get("h1"), "h6": v.get("h6"), "h24": v.get("h24")}, "_src": "dexscreener", "_migrated_to": mig,
                              "pool_created_at": dt.datetime.fromtimestamp(pick["pairCreatedAt"] / 1000, UTC).isoformat() if pick.get("pairCreatedAt") else None}
    if errs and not out: raise errs[0]
    return out

_SOL = [None]
def fast_prices(positions, timeout=6, errs=None):
    """Exit prices with 0 GeckoTerminal calls: DexScreener /tokens/v1 batch (30 mints/call) first; bonding-curve coins
    DexScreener does not index (fresh NEW PAIRS) are read straight from the pump.fun curve account on chain (1 batched
    getMultipleAccounts call) x SOL/USD (median DexScreener SOL quote this check, else last known, else entry SOL price)."""
    errs = [] if errs is None else errs; d = {}
    if not positions: return d
    try: d = ds_prices(positions, timeout=timeout)
    except Exception as e: errs.append(f"dexscreener {type(e).__name__}")
    sols = sorted(float(a["quote_token_price_usd"]) for a in d.values() if (a.get("quote_token_price_usd") or 0) and float(a["quote_token_price_usd"]) > 1)
    if sols: _SOL[0] = sols[len(sols) // 2]
    miss = [o for o in positions if o["pool"] not in d and o.get("venue") == "bonding_curve"]
    if miss:
        try:
            import newpairs
            cs = newpairs.chain_curves(sorted({o["pool"] for o in miss}), errs)
            for o in miss:
                c = cs.get(o["pool"])
                if not c or not c.get("price_sol") or c.get("complete"): continue
                sol = _SOL[0] or o.get("sol_usd"); px = c["price_sol"] * sol
                d[o["pool"]] = {"base_token_price_usd": px, "quote_token_price_usd": sol, "reserve_in_usd": c["real_sol"] * sol,
                                "market_cap_usd": px * 1_000_000_000, "volume_usd": {}, "_src": "chain curve", "_migrated_to": None, "pool_created_at": None}
        except Exception as e: errs.append(f"chain curve {type(e).__name__}")
    return d

def live_prices(positions):
    """kept for callers/tests: same as fast_prices (no GeckoTerminal fallback any more, upgrade 1)."""
    return fast_prices(positions)

def vol_decay(v, created_iso):
    """Article rule: avg_6h = volume.h24/4, ratio = volume.h6/avg_6h, ratio < 0.20 -> close fully.
    h24/4 is only a 6h average if the pool is >= 24h old (a 3h-old pool has h24 == h6 -> ratio 4.0, never fires).
    So the denominator uses the pool's real age (DexScreener pairCreatedAt / GT pool_created_at):
      age >= 24h : ratio = h6 / (h24/4)                         (exactly the article)
      6h..24h    : ratio = h6 / (h24 / (age/6))                (avg per 6h over the pool's life)
      2h..6h     : ratio = h1 / (h6 / age)                     (h1-vs-h6 analog: last hour vs avg hour)
      < 2h / age unknown with h24 == h6 : rule off (other exits still apply)
    Returns (ratio or None, mode text)."""
    h1, h6, h24 = (float(v.get(k) or 0) for k in ("h1", "h6", "h24"))
    age = None
    if created_iso:
        try: age = (now() - dt.datetime.fromisoformat(str(created_iso).replace("Z", "+00:00"))).total_seconds() / 3600
        except ValueError: age = None
    if age is None:
        if h24 > h6 * 1.05 and h24 > 0: return h6 / (h24 / 4), "h6/(h24/4) (age unknown)"
        return None, "volume rule off (pool age unknown, h24==h6)"
    if age >= 24: return (h6 / (h24 / 4) if h24 > 0 else 0.0), "h6/(h24/4)"
    if age >= 6:
        avg6 = h24 / (age / 6)
        return (h6 / avg6 if avg6 > 0 else 0.0), f"h6/(h24 per 6h over {age:.1f}h age)"
    if age >= VOL_MIN_AGE_H:
        avg1 = h6 / age
        return (h1 / avg1 if avg1 > 0 else 0.0), f"h1/(h6 per h over {age:.1f}h age)"
    return None, f"volume rule off (pool {age:.1f}h < {VOL_MIN_AGE_H:.0f}h)"

def sim_buy(ticket, venue, price, sol, liq, mcap):
    """Simulated buy fill (both sleeves + shadow book): venue fee + app fee + network + priority fee (taken from the ticket),
    constant-product slippage + latency buffer, plus the refundable token-account rent (deposit, not in cost_usd)."""
    fee, fr = total_fee(ticket, venue, mcap, sol)
    slip = slippage(ticket - fee, quote_reserve_usd(venue, price, sol, liq))
    fill = price * (1 + slip); qty = (ticket - fee) / fill
    return {"entry_mid": price, "entry_price": fill, "entry_slippage": round(slip, 5), "entry_fee": round(fee, 6), "entry_fee_rate": fr,
            "priority_fee_usd": PRIORITY_FEE_USD, "qty": qty, "qty_initial": qty, "cost_usd": ticket, "sol_usd": sol,
            "rent_sol": ATA_RENT_SOL, "rent_usd": round(ATA_RENT_SOL * sol, 6), "last_price": price, "peak_price": price}

def sim_sell(o, a, frac=1.0):
    """Simulated sell of `frac` of position o at live attributes a. Returns the closed-record fields (no state change)."""
    price = float(a["base_token_price_usd"]); sol = float(a.get("quote_token_price_usd") or 0) or o.get("sol_usd")
    qty = o["qty"] * frac; cost = o["cost_usd"] * frac
    slip = slippage(qty * price, quote_reserve_usd(o["venue"], price, sol, float(a.get("reserve_in_usd") or 0)))
    fill_px = price * (1 - slip); proceeds_gross = qty * fill_px
    fee, fr = total_fee(proceeds_gross, o["venue"], float(a.get("market_cap_usd") or a.get("fdv_usd") or 0), sol)
    proceeds = proceeds_gross - fee
    r = {"qty": qty, "cost_usd": cost, "partial": frac < 1.0, "exit_time": now().isoformat(), "exit_mid": price, "exit_price": fill_px,
         "exit_slippage": round(slip, 5), "exit_fee": round(fee, 6), "exit_fee_rate": fr, "proceeds_usd": round(proceeds, 6), "pnl": round(proceeds - cost, 6)}
    if frac >= 1.0 and o.get("rent_sol"):   # account closed with the final sell -> rent deposit back (0 P&L)
        r["rent_refund_usd"] = round(o["rent_sol"] * (sol or o.get("sol_usd") or 0), 6)
    return r

def close_position(o, a, reason, p, frac=1.0):
    """Simulated sell of `frac` of the position (1.0 = all) at live price - slippage - fees."""
    f = sim_sell(o, a, frac); qty, cost, fill_px, pnl = f["qty"], f["cost_usd"], f["exit_price"], f["pnl"]
    slip, fee = f["exit_slippage"], f["exit_fee"]
    c = {**o, **f, "exit_reason": reason}
    if frac >= 1.0: p["open"] = [x for x in p["open"] if x["pool"] != o["pool"]]
    else: o["qty"] -= qty; o["cost_usd"] = round(o["cost_usd"] - cost, 6)
    p["closed"].append(c)
    trade_log({"type": "SELL", "simulated": True, **c})
    log(f"[FILLS] SELL {('HALF ' if abs(frac - 0.5) < 1e-6 else 'PART ') if frac < 1.0 else ''}{ltag(o.get('token'))}{o['name']} (SIMULATED pump.fun) qty {qty:.4g} @ {fill_px:.10g} slip {slip:.2%} fee ${fee:.4f} -> pnl {pnl:+.4f} | {reason}")
    try: cooldown_on_close(o, c, frac)
    except Exception as e: log(f"[RISK] cooldown write failed: {e}")

# ---------------- EXIT rules (shared by the real book and the shadow book) ----------------
def exit_plan(o):
    """NEW PAIRS positions carry their tier plan (frozen at entry); main-sleeve positions use MAIN_EXIT.
    Legacy main positions (before 2026-10-20 19:5x) get qty_initial/tp_hits derived from tp_done (half already sold)."""
    if o.get("exit"): return o["exit"]
    if "qty_initial" not in o: o["qty_initial"] = o["qty"] * (2 if o.get("tp_done") else 1)
    if "tp_hits" not in o: o["tp_hits"] = [0.5] if o.get("tp_done") else []
    return MAIN_EXIT

def exit_decision(o, mark, ratio=None, vmode="", safety=None, t=None):
    """One exit check at `mark`. Updates peak/tp_hits on o. Returns (frac or None, text). Order (first match wins):
    hard stop -> safety (new pairs) -> trailing (armed at +trail_arm; tightened to trail_tight[1] once peak >= +trail_tight[0];
    force-armed after the time stop while in profit if trail_after_time_stop) -> time stop (optionally only if not in profit) ->
    max hold -> next take-profit tier (fraction of INITIAL qty) -> volume decay."""
    t = t or now()
    o["peak_price"] = max(o.get("peak_price") or o["entry_mid"], mark)
    entry = o["entry_price"]; held_min = (t - dt.datetime.fromisoformat(o["entry_time"])).total_seconds() / 60
    chg = mark / entry - 1; peak_g = o["peak_price"] / entry - 1
    sl = o.get("stop_loss") or STOP_LOSS.get(o.get("venue"), 0.20)
    ex = exit_plan(o)
    t_arm, t_stop = ex.get("trail_arm", TRAIL_ARM), ex.get("trail", TRAIL_STOP)
    tight = ex.get("trail_tight")
    if tight and peak_g >= tight[0]: t_stop = min(t_stop, tight[1])
    ts_min = ex.get("time_stop_min", TIME_STOP_MIN); ts_profit_ok = ex.get("time_stop_only_if_not_profit", False)
    max_hold = ex.get("max_hold_min"); ladder = ex.get("tp") or []
    armed = peak_g >= t_arm; forced = False
    if ex.get("trail_after_time_stop") and held_min >= ts_min and chg > 0 and not armed: armed = forced = True
    tag = f" [NEW PAIR {o.get('tier', '').upper()}]" if o.get("sleeve") == "newpairs" else ""
    hits = o.setdefault("tp_hits", [])
    nxt = ladder[len(hits)] if len(hits) < len(ladder) else None
    if mark <= entry * (1 - sl):
        return 1.0, f"stop-loss: mark {chg:+.1%} vs entry <= -{sl:.0%}{tag}"
    if safety:
        return 1.0, f"{safety} (mark {chg:+.1%}){tag}"
    if armed and mark <= o["peak_price"] * (1 - t_stop):
        how = "after time stop, in profit" if forced else f"armed at +{t_arm:.0%}" + (f", tightened at peak +{tight[0]:.0%}" if tight and peak_g >= tight[0] else "")
        return 1.0, f"trailing stop: mark {mark/o['peak_price']-1:+.1%} from peak <= -{t_stop:.0%} ({how}){tag}"
    l_trig, l_floor = ex.get("lock_trigger", LOCK_TRIGGER), ex.get("lock_floor", LOCK_FLOOR)
    locked = l_trig is not None and peak_g >= l_trig
    if locked and mark <= entry * (1 + l_floor):
        return 1.0, f"profit lock: mark {chg:+.1%} vs entry <= +{l_floor:.0%} (peak {peak_g:+.0%} >= +{l_trig:.0%}){tag}"
    if held_min >= ts_min and not (ts_profit_ok and chg > 0):
        return 1.0, f"time stop: held {held_min:.0f} min >= {ts_min} (mark {chg:+.1%}){tag}"
    if max_hold and held_min >= max_hold:
        return 1.0, f"max hold {max_hold} min reached (mark {chg:+.1%}){tag}"
    if nxt and mark >= entry * (1 + nxt[0]):
        frac = min(1.0, nxt[1] * (o.get("qty_initial") or o["qty"]) / o["qty"]); hits.append(round(nxt[0], 2)); o["tp_done"] = True
        return (frac if frac < 0.999 else 1.0), f"take-profit {len(hits)}/{len(ladder)}: {nxt[1]:.0%} of initial at {chg:+.1%} >= +{nxt[0]:.0%}{tag}"
    if ratio is not None and ratio < EXIT_RATIO:
        return 1.0, f"volume decay {vmode} = {ratio:.2f} < {EXIT_RATIO}{tag}"
    vr = f"vol ratio {ratio:.2f} [{vmode}]" if ratio is not None else vmode
    return None, (f"mark {mark:.10g} ({chg:+.1%} vs entry, SL -{sl:.0%}, trail -{t_stop:.0%} " + ("armed" if armed else "off (arms +" + format(t_arm, ".0%") + ")")
                  + f", peak {o['peak_price']:.10g} ({peak_g:+.0%})" + (f", lock >= +{l_floor:.0%}" if locked else "") + f", TP {len(hits)}/{len(ladder)}, {held_min:.0f}/{ts_min} min"
                  + (" (only if not in profit)" if ts_profit_ok else "") + f", {vr})")

# ---------------- JUDGE helpers ----------------
def pick_shadow_hook(top, gate_enabled=None):
    """Shadow fields for the final pick (I-18 twin share, V-01 fresh count). Returns a block reason ONLY if the I-18 gate is
    enabled and the share is >= I18_BLOCK_SHARE; otherwise None. Never raises; a timeout/error never blocks a buy.
    Gate off: the work runs in a detached child (`timeout 60`), so the buy is not delayed. Gate on: <= 1 pump.fun call, hard
    timeout PICK_SHADOW_TIMEOUT_S in this process, then the child only does the RPC wallet-age lookups."""
    gate = I18_GATE_ENABLED if gate_enabled is None else gate_enabled
    args = {"token": top.get("base_token"), "name": top.get("name"), "venue": top.get("venue"), "lead": lead_id(top.get("base_token") or ""),
            "sleeve": "main", "pick_ts": time.time(), "gate_enabled": bool(gate)}
    reason = None
    try:
        if gate:
            import pick_shadow
            f = pick_shadow.twin_share_sync(args["token"], args["pick_ts"], PICK_SHADOW_TIMEOUT_S)
            args["i18"] = f if f else None
            if f and f.get("i18_twin_share") is not None and (f.get("i18_n_buys") or 0) >= I18_MIN_BUYS and f["i18_twin_share"] >= I18_BLOCK_SHARE:
                reason = f"I-18 twin-buy share {f['i18_twin_share']:.0%} >= {I18_BLOCK_SHARE:.0%} (same second, same SOL, other wallet)"
            if not f: args["i18"] = {"i18_twin_share": None, "i18_n_buys": None, "top": []}; args["note"] = "i18 timeout/error -> fail-open (not blocked)"
            args["blocked"] = bool(reason)
        import subprocess
        subprocess.Popen(["timeout", "60", sys.executable, os.path.join(DESK, "pick_shadow.py"), json.dumps(args)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except Exception as e:
        log(f"[SHADOW] pick fields failed: {type(e).__name__}: {str(e)[:100]}")
    return reason

def rugpattern_fails(c):
    """rule 7 / rule 8 skip reasons for a candidate (rugpattern.py). Returns (fails, notes); notes = data n/a -> allowed."""
    import rugpattern
    try: return rugpattern.check(c["base_token"], newpairs=False)
    except Exception as e: return [], [f"rule 7/8 check error {type(e).__name__}: {str(e)[:80]} -> allowed"]

def chase_cooldown(fails, keys, name):
    """USER ORDER 2026-10-23 17:43: a rule 9 (chase) / rule 10 (dump candle) block puts mint + pool(s) on a
    rugpattern.CHASE_COOLDOWN_MIN cooldown (meme_cooldown.json = state, survives ticks and runner restarts) so the coin is not
    bought minutes later once the 10/15-min window rolls past. Main AND new pairs. Never raises; returns until or None."""
    try:
        hit = next((x for x in (fails or []) if x.startswith(("rule 9 ·", "rule 10 ·"))), None)
        if not hit: return None
        import rugpattern, scan
        until = scan.cooldown_add(keys, name, f"rule 9/10 block {rugpattern.CHASE_COOLDOWN_MIN} min: {hit}", minutes=rugpattern.CHASE_COOLDOWN_MIN)
        log(f"[RISK] cooldown: {name} blocked for re-entry until {dt.datetime.fromisoformat(until).astimezone(BER):%H:%M %Z} ({hit[:60]})")
        return until
    except Exception as e:
        log(f"[RISK] chase cooldown write failed: {type(e).__name__}: {str(e)[:80]}"); return None

def judge_metrics(c, watch=False):
    """Deterministic entry gates on scan data. Returns list of failure strings (empty = pass).
    watch=True (coin already on the dip watchlist): price h1 lower bound relaxed to J_PC_H1_WATCH_MIN."""
    f = []; h1 = c.get("tx_h1") or {}; m15 = c.get("tx_m15") or {}
    ub = h1.get("buyers"); buys = h1.get("buys") or 0
    if ub is None: f.append("unique buyers h1 n/a")
    elif ub < J_MIN_BUYERS_H1: f.append(f"unique buyers h1 {ub} < {J_MIN_BUYERS_H1}")
    b15, s15 = m15.get("buys") or 0, m15.get("sells") or 0
    r15 = (b15 / s15) if s15 else (float("inf") if b15 else 0.0)
    if r15 < J_MIN_BS_M15: f.append(f"buys/sells m15 {b15}/{s15} = {r15:.2f} < {J_MIN_BS_M15}")
    if ub is not None and buys and ub / buys < J_MIN_BUYERS_PER_BUY: f.append(f"buyers/buy h1 {ub}/{buys} = {ub/buys:.2f} < {J_MIN_BUYERS_PER_BUY} (bot-like)")
    pc = c.get("pc_h1")
    if pc is None: f.append("price change h1 n/a")
    else:
        lo = J_PC_H1_WATCH_MIN if watch else J_PC_H1[0]
        if not (lo <= pc <= J_PC_H1[1]): f.append(f"price h1 {pc:+.0f}% outside {lo:+.0f}..+{J_PC_H1[1]:.0f}%" + (" (watchlist)" if watch else ""))
    return f

class RugCheckDown(RuntimeError): pass

def _rc_cache():
    try: return json.load(open(RC_CACHE))
    except (FileNotFoundError, ValueError): return {}

def rugcheck_report(mint):
    """Full RugCheck report, cached per mint for RC_TTL s (only successful reports are cached)."""
    import time, requests
    cache = _rc_cache(); hit = cache.get(mint)
    if hit and time.time() - hit["ts"] < RC_TTL: return hit["r"], True
    try:
        r = requests.get(RC_URL.format(mint), timeout=RC_TIMEOUT, headers={"User-Agent": "desk-meme/1.0"})
        if r.status_code != 200: raise RugCheckDown(f"HTTP {r.status_code}")
        rep = r.json()
    except RugCheckDown: raise
    except Exception as e: raise RugCheckDown(type(e).__name__)
    keep = {k: rep.get(k) for k in ("mint", "mintAuthority", "freezeAuthority", "transferFee", "rugged", "risks", "creator", "creatorBalance",
                                     "token", "topHolders", "knownAccounts", "graphInsidersDetected", "score_normalised")}
    keep["markets"] = [{"pubkey": m.get("pubkey"), "marketType": m.get("marketType"), "liquidityA": m.get("liquidityA"),
                        "liquidityB": m.get("liquidityB"), "lpLockedPct": (m.get("lp") or {}).get("lpLockedPct")} for m in rep.get("markets") or []]
    cache = {k: v for k, v in _rc_cache().items() if time.time() - v["ts"] < RC_TTL}; cache[mint] = {"ts": time.time(), "r": keep}
    tmp = RC_CACHE + ".tmp"; json.dump(cache, open(tmp, "w")); os.replace(tmp, RC_CACHE)
    return keep, False

def rugcheck_gates(c, rep):
    """Hard gates. Returns list of failure strings (empty = pass)."""
    f = []
    tok = rep.get("token") or {}
    if rep.get("mintAuthority") or tok.get("mintAuthority"): f.append("mint authority set")
    if rep.get("freezeAuthority") or tok.get("freezeAuthority"): f.append("freeze authority set")
    if ((rep.get("transferFee") or {}).get("pct") or 0) != 0: f.append(f"transfer fee {(rep.get('transferFee') or {}).get('pct')}%")
    if rep.get("rugged"): f.append("flagged rugged")
    dang = [x.get("name") for x in rep.get("risks") or [] if x.get("level") == "danger"]
    if dang: f.append("danger: " + ", ".join(dang))
    mk = rep.get("markets") or []
    if c["venue"] == "pumpswap":
        m = next((m for m in mk if m.get("pubkey") == c["pool"]), None)
        if not m: f.append("pool not in RugCheck markets (LP lock unknown)")
        elif (m.get("lpLockedPct") or 0) < RC_LP_LOCKED_MIN: f.append(f"LP locked {m.get('lpLockedPct') or 0:.0f}% < {RC_LP_LOCKED_MIN:.0f}%")
    supply = float(tok.get("supply") or 0)
    cpct = (float(rep.get("creatorBalance") or 0) / supply * 100) if supply else 0.0
    if cpct > RC_CREATOR_MAX: f.append(f"creator holds {cpct:.1f}% > {RC_CREATOR_MAX:.0f}%")
    known = rep.get("knownAccounts") or {}
    pool_keys = {c["pool"]} | {m.get("pubkey") for m in mk} | {m.get("liquidityA") for m in mk} | {m.get("liquidityB") for m in mk} \
                | {k for k, v in known.items() if (v or {}).get("type") in ("AMM", "LOCKER")}
    holders = [h for h in rep.get("topHolders") or [] if h.get("owner") not in pool_keys and h.get("address") not in pool_keys]
    top = max((h.get("pct") or 0 for h in holders), default=0.0)
    if top > RC_HOLDER_MAX: f.append(f"largest non-pool holder {top:.1f}% > {RC_HOLDER_MAX:.0f}%")
    ins = rep.get("graphInsidersDetected") or 0
    if ins > RC_INSIDERS_MAX: f.append(f"insiders {ins} > {RC_INSIDERS_MAX}")
    return f

def ohlcv_highs(pool, deadline):
    """[(epoch, high_usd)] 1-min candles, last 60 min (1 GT call)."""
    d = gt.get(f"/networks/solana/pools/{pool}/ohlcv/minute", {"aggregate": 1, "limit": DIP_WINDOW_MIN, "currency": "usd"}, deadline=deadline)
    return [(float(r[0]), float(r[2])) for r in ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []]

def dip_check(c, w, ohlcv_left, deadline):
    """Returns (ok, text, highs_to_store, used_ohlcv). w = existing watchlist entry or None."""
    t = now().timestamp(); px = c.get("price_usd")
    if not px: return False, "dip: price n/a", [], False
    highs = [(t, px)] + [(float(a), float(b)) for a, b in (w or {}).get("highs", [])]
    for k, mins in (("pc_m5", 5), ("pc_m15", 15), ("pc_m30", 30), ("pc_h1", 60)):
        v = c.get(k)
        if v is not None and v > -99: highs.append((t - mins * 60, px / (1 + v / 100)))
    used = False
    if ohlcv_left > 0 and not (w or {}).get("ohlcv_at"):
        try: highs += ohlcv_highs(c["pool"], min(deadline, time.time() + 4)); used = True
        except Exception: pass
    highs = [(a, b) for a, b in highs if t - a <= DIP_WINDOW_MIN * 60 and b > 0]
    hi = max(b for _, b in highs); pull = 1 - px / hi; m5 = c.get("pc_m5")
    txt = f"pullback {pull:.0%} from 60-min high (need {DIP_MIN:.0%}..{DIP_MAX:.0%}), m5 {m5 if m5 is not None else float('nan'):+.0f}%"
    keep = sorted(highs, key=lambda x: -x[1])[:20]
    if pull < DIP_MIN: return False, "watchlist: no dip yet — " + txt, keep, used
    if pull > DIP_MAX: return False, "dip too deep (trend broken) — " + txt, keep, used
    if m5 is not None and m5 < DIP_M5_MIN: return False, f"watchlist: falling knife m5 {m5:+.0f}% < {DIP_M5_MIN:.0f}% — " + txt, keep, used
    if not used and not (w or {}).get("ohlcv_at"):   # samples miss intra-window spikes -> never enter without a real candle high
        return False, "watchlist: dip on sampled prices, 60-min candle high not yet fetched (GT budget) — " + txt, keep, used
    return True, "dip entry — " + txt, keep, used

SHADOW_RC_NEW = 3          # uncached RugCheck calls per run for shadow-only evaluations
SHADOW_SCAN_SINGLES = 15   # single-SCAN-filter rejects evaluated per run for the shadow book

def gate_key(text):
    """Stable gate name from a failure text: 'unique buyers h1 12 < 50' -> 'unique buyers h1'."""
    m_ = re.match(r"rule (\d+) · ([A-Za-z\- ]+)", str(text).strip())
    if m_: return f"rule {m_.group(1)} {m_.group(2).strip()}"[:60]
    k = re.split(r"\s[\d+\-~$(<>=]|:\s", str(text).strip(), maxsplit=1)[0] if not str(text).startswith("danger:") else str(text)[:60]
    return k.strip()[:60] or "?"

def dip_key(dtxt):
    for k, v in (("no dip yet", "dip: no dip yet"), ("too deep", "dip: too deep"), ("falling knife", "dip: falling knife"),
                 ("candle high not yet fetched", "dip: candle not fetched (data guard)"), ("price n/a", "dip: price n/a")):
        if k in dtxt: return v
    return "dip: other"

def cooldown_on_close(o, c, frac):
    """24h cooldown for mint + pool(s) after a full close that is a stop-out or a loss."""
    import scan
    if frac < 1.0: return
    r = c.get("exit_reason") or ""
    if c["pnl"] < 0 or r.startswith("stop-loss"):   # hard stop always; trailing/time/volume/DD exits only when at a loss
        until = scan.cooldown_add([o.get("token"), o.get("pool"), o.get("pool_original")], o["name"], r)
        log(f"[RISK] cooldown: {o['name']} blocked for re-entry until {dt.datetime.fromisoformat(until).astimezone(BER):%Y-%m-%d %H:%M %Z} ({r[:50]})")

def pipeline(dry=False):
    """dry=True: scan without persisting + full Judge incl. RugCheck, no fill, nothing written (verification)."""
    import scan, time
    t0 = time.time()
    p = load_pos()
    eq, ms = desk_equity()
    halted = check_daily_dd(eq) if not dry else (risk_state().get("halted", False) and DAILY_DD_ENABLED)
    sc = scan.scan(dry=dry)
    dial, age = latest_dial()
    cands = sc["candidates"]
    _log = log if not dry else (lambda l: print("[DRY] " + l))
    # ---- JUDGE (deterministic, no LLM): candidates in rank order, buy the first that passes every gate ----
    reason = None
    if halted: reason = "daily drawdown halt active"
    elif not dial: reason = "no dial file"
    elif age > DIAL_MAX_AGE_H: reason = f"dial is {age:.1f}h old (>24h)"
    elif "liquidity" in dial["degraded"] or any(x in dial["degraded"] for x in ("WALCL", "WTREGEN", "RRPONTSYD", "VIXCLS", "BTC/USD", "SOL/USD")):
        reason = f"meme dial inputs degraded {dial['degraded']}"
    elif dial["dial"]["meme"] < 0.50: reason = f"meme dial {dial['dial']['meme']} < 0.50 (stand down)"
    elif not cands: reason = "no candidates passed SCAN"
    elif len([o for o in p["open"] if o.get("sleeve") != "newpairs"]) >= MAX_OPEN: reason = f"max {MAX_OPEN} open positions reached"
    elif len(p["open"]) >= TOTAL_MAX_OPEN: reason = f"overall max {TOTAL_MAX_OPEN} open positions (incl. new pairs) reached"
    decisions, top, rc_down, passers = [], None, None, []
    use_jev = bool(jev and jev.active()); want = jev.max_cands() if use_jev else 1
    held = {o.get("token") for o in p["open"]} | {o["pool"] for o in p["open"]}
    wl = scan.watchlist_active(); wl_added = wl_hit = 0; ohlcv_left = OHLCV_PER_RUN
    cool = scan.cooldown_active()
    # ---- SHADOW (upgrade 3): virtual trades for candidates blocked by capacity (max open / one buy per run), by the
    #      bonding-curve rule (upgrade 4) or by exactly ONE failing gate. Side-effect free: no watchlist writes, no OHLCV
    #      (dip uses sampled highs; 'candle not fetched' is a data guard and only counts when it is the only failure),
    #      RugCheck from cache or <= SHADOW_RC_NEW per run. Never touches the bank (shadow_positions.json). ----
    sh = []; cap_block = "blocked:max_open" if (reason and "max" in reason and "open" in reason) else None; rc_new = [0]
    def rc_try(c):
        hit = _rc_cache().get(c["base_token"])
        if not (hit and time.time() - hit["ts"] < RC_TTL):
            if rc_new[0] >= SHADOW_RC_NEW or time.time() - t0 > JUDGE_BUDGET_S: return None
            rc_new[0] += 1
        try: rep_, _ = rugcheck_report(c["base_token"]); return [("rugcheck: " + gate_key(x), x) for x in rugcheck_gates(c, rep_)]
        except Exception: return None
    def dip_sampled(c, w):
        ok, dtxt, _, _ = dip_check(c, w, 0, time.time() + 1)
        return [] if ok or "candle high not yet fetched" in dtxt else [(dip_key(dtxt), dtxt)]
    def chain(c, w, pre=None):
        f = [("judge: " + gate_key(x), x) for x in (judge_metrics(c, watch=bool(w)) if pre is None else pre)]
        if len(f) > 1: return f
        g = rc_try(c)
        if g is None: return None          # RugCheck unknown -> no shadow
        f += g
        return f if len(f) > 1 else f + dip_sampled(c, w)
    def add_shadow(c, fails, blocked=None):
        if fails is None: return
        if not fails and blocked: sh.append(("main:" + blocked, c, "all gates pass"))
        elif len(fails) == 1 and c["venue"] == "pumpswap": sh.append(("main:gate:" + fails[0][0], c, fails[0][1]))
    for c in cands:
        w = wl.get(c["pool"]); over = time.time() - t0 > JUDGE_BUDGET_S
        is_held = c["base_token"] in held or c["pool"] in held; is_cool = c["base_token"] in cool or c["pool"] in cool
        free = not (over or is_held or is_cool)
        if reason:
            r = reason
            if free: add_shadow(c, chain(c, w), cap_block)
        elif len(passers) >= want:
            r = ("not judged: Jev shortlist full" if use_jev else "not judged: already picked one (max one new buy per run)")
            if free: add_shadow(c, chain(c, w), "blocked:one_per_run")
        elif rc_down: r = f"rugcheck unavailable ({rc_down}) -> no buy"
        elif over: r = "not judged: run time budget"
        elif is_held: r = "already held (1 position per coin)"
        elif is_cool: r = "cooldown: " + ((cool.get(c["base_token"]) or cool.get(c["pool"]) or {}).get("reason") or "stopped out / losing close < 24h ago")[:90]
        elif c["venue"] == "bonding_curve":   # upgrade 4 (2026-10-20 19:5x): main sleeve makes no real buys on the curve
            r = "bonding curve: main sleeve makes no real buys on the curve (shadow only)"
            add_shadow(c, chain(c, w), "blocked:bonding_curve")
        else:
            f = judge_metrics(c, watch=bool(w))
            if not f:   # USER ORDER 2026-10-21 19:34/19:37: rule 7 (first-candle launch pump) + rule 8 (bot-wash), pump.fun candles, 0 GT calls
                f, rp_notes = rugpattern_fails(c)
                for n_ in rp_notes: _log(f"[JUDGE] [{lead_id(c.get('base_token'))}] {c['name']}: {n_}")
                chase_cooldown(f, [c.get("base_token"), c.get("pool")], c["name"])
            if f:
                r = ("judge: " if not w else "judge (watchlist): ") + "; ".join(f)
                if len(f) == 1: add_shadow(c, chain(c, w, pre=f))
            else:
                try:
                    rep, cached = rugcheck_report(c["base_token"]); g = rugcheck_gates(c, rep)
                    r = ("rugcheck: " + "; ".join(g)) if g else None
                    if g and w: wl.pop(c["pool"], None)
                    if len(g) == 1: add_shadow(c, [("rugcheck: " + gate_key(g[0]), g[0])] + dip_sampled(c, w))
                    if r is None:
                        ok, dtxt, highs, used = dip_check(c, w, ohlcv_left, t0 + scan.SCAN_BUDGET_S + 10)
                        if used: ohlcv_left -= 1
                        c["_dip"] = dtxt
                        if ok:
                            c["_rc_score"] = rep.get("score_normalised"); passers.append(c); r = None
                            if w: wl_hit += 1
                        else:
                            r = dtxt; add_shadow(c, [(dip_key(dtxt), dtxt)])
                            if dtxt.startswith("dip too deep"): wl.pop(c["pool"], None)
                            else:
                                tnow = now()
                                if not w: wl_added += 1
                                wl[c["pool"]] = {"pool": c["pool"], "mint": c["base_token"], "name": c["name"], "venue": c["venue"],
                                                 "added_at": (w or {}).get("added_at") or tnow.isoformat(timespec="seconds"),
                                                 "expires_at": (w or {}).get("expires_at") or (tnow + dt.timedelta(minutes=WATCH_TTL_MIN)).isoformat(timespec="seconds"),
                                                 "highs": [[round(a), b] for a, b in highs], "ohlcv_at": (w or {}).get("ohlcv_at") or (tnow.isoformat(timespec="seconds") if used else None),
                                                 "last_price": c.get("price_usd"), "last_seen": tnow.isoformat(timespec="seconds"), "last_reason": dtxt[:160],
                                                 "src": c.get("src")}
                except RugCheckDown as e:
                    rc_down = str(e); r = f"rugcheck unavailable ({rc_down}) -> no buy"
                    _log(f"[JUDGE] rugcheck unavailable ({rc_down}) for {c['name']} -> no buy this run")
        decisions.append({"lead": lead_id(c.get("base_token")), "pool": c["pool"], "name": c["name"], "venue": c["venue"], "score": c["score"],
                          "decision": "PASS" if r is None else ("WATCH" if (r or "").startswith("watchlist") else "DECLINED"),
                          "reason": r or ("passes all gates incl. RugCheck + " + c.get("_dip", "dip")), "src": c.get("src"), "wallet": c.get("wallet")})
    # single SCAN-filter rejects (PumpSwap): shadow if every JUDGE/RugCheck/dip gate would pass
    for c in (sc.get("single_fail") or [])[:SHADOW_SCAN_SINGLES]:
        if time.time() - t0 > JUDGE_BUDGET_S: break
        if c.get("venue") != "pumpswap" or c["base_token"] in held or c["pool"] in held: continue
        f = chain(c, wl.get(c["pool"]))
        if f == []: sh.append(("main:gate:scan: " + c["fail_keys"][0], c, (c.get("fails") or ["?"])[0]))
    jev_info = None
    if passers and not use_jev: top = passers[0]
    elif passers:
        try:
            idx, jev_info = jev.choose(passers); top = passers[idx] if idx is not None else None
            _log(f"[JUDGE] Jev ({jev_info.get('model')}) among {len(passers)} gate-passer(s): choice {jev_info.get('choice')} conf {jev_info.get('confidence'):.2f} nouls {jev_info.get('nouls')} -> {top['name'] if top else 'no buy'} (${jev_info.get('cost_usd'):.6f})")
            if not top: reason = f"Jev declined all {len(passers)} gate-passer(s): {jev_info.get('declined') or 'choice none'}"
        except Exception as e:
            if jev.fail_mode() == "rule": top = passers[0]; _log(f"[JUDGE] Jev unavailable ({e}) -> rule-based pick (first passer)")
            else: reason = f"Jev unavailable ({e}) and JEV_FAIL=skip -> no buy"
    if top is not None:
        for c in passers:
            if c["pool"] != top["pool"]: sh.append(("main:blocked:one_per_run", c, "passed all gates; another coin picked"))
    for d in decisions:
        if d["decision"] == "PASS":
            if top is not None and d["pool"] == top["pool"]: d["decision"] = "PICK"; d["reason"] += (" | Jev pick" if jev_info else "")
            else: d["decision"] = "DECLINED"; d["reason"] = "passed gates; " + ("Jev chose another / none" if jev_info else "not picked")
    if not reason and not top:
        reason = (f"rugcheck unavailable ({rc_down})" if rc_down else
                  f"none of {len(cands)} candidate(s) passed Judge/RugCheck: " + " | ".join(f"[{d.get('lead')}] {d['name']}: {d['reason']}" for d in decisions[:3]))
    # CONTROL BOT (2026-10-20 research): shadow baselines the gates must beat - one random PumpSwap scan-passer and the
    # top-ranked one per run, regardless of Judge/RugCheck/dip/capacity (same exits, same fill model, virtual only).
    ctl = [c for c in cands if c.get("venue") == "pumpswap" and c["base_token"] not in held]
    if ctl:
        import random as _r
        sh.append(("control:top_scan_pass", ctl[0], "control baseline: top-ranked scan passer, no judge gates"))
        sh.append(("control:random_scan_pass", _r.Random(str(sc.get("run_id"))).choice(ctl), "control baseline: random scan passer, no judge gates"))
    if top is not None: wl.pop(top["pool"], None)
    wl = {k: v for k, v in wl.items() if v.get("venue") != "bonding_curve"}   # upgrade 4: no real curve buys -> don't watch curve coins
    if len(wl) > WATCH_MAX: wl = dict(sorted(wl.items(), key=lambda kv: kv[1]["added_at"])[-WATCH_MAX:])
    if wl_added or wl_hit: _log(f"[JUDGE] watchlist: +{wl_added} new, {wl_hit} dip-entry candidate(s), {len(wl)} watched")
    if not dry:
        try: scan.save_json(scan.WATCH_FILE, wl)
        except Exception as e: log(f"[JUDGE] could not save watchlist: {e}")
        try: scan.record_judge(sc.get("run_id"), (decisions if cands else [{"decision": "NONE", "reason": reason}]) + [{"decision": "META", "watchlist": len(wl), "watch_added": wl_added, "cooldown": len(cool), "shadow": len(sh)}])
        except Exception as e: log(f"[JUDGE] could not persist decisions: {e}")
    sh_res = None
    def _feat(c):   # 2026-10-22 SELF-LEARN: entry features of shadow trades (recording only)
        try:
            import learner as _learner; return _learner.features(c, now().isoformat(), c.get("base_token"))
        except Exception: return None
    def _shadow(extra=None):
        allsh = sh + (extra or [])
        if dry: print("[DRY] shadow candidates: " + "; ".join(f"{k} {c['name']} ({n[:50]})" for k, c, n in allsh)); return
        if not allsh: return
        try:
            import shadow
            meq = ms["equity"]; dm = (dial or {}).get("dial", {}).get("meme") or 1.0
            ent = [{"cat": k, "note": n, "pool": c["pool"], "token": c["base_token"], "name": c["name"], "venue": c["venue"],
                    "price": c.get("price_usd"), "sol": c.get("sol_usd"), "liq": c.get("liquidity_usd"), "mcap": c.get("mcap_usd"),
                    "ticket": round(min(FIXED_TICKET_USD, LIQ_CAP * (c.get("liquidity_usd") or 0)), 2), "exit": MAIN_EXIT, "sleeve": "main",
                    "url": c.get("url"), "feat": _feat(c)} for k, c, n in allsh]
            shadow.open_entries(ent)
        except Exception as e: log(f"[SHADOW] open failed: {type(e).__name__}: {str(e)[:120]}")
    if not top:
        _shadow(); _log(f"[JUDGE] no trade: {reason}"[:600]); return {"scan": sc, "decisions": decisions, "reason": reason, "watchlist": wl, "shadow": sh}
    _log(f"[JUDGE] PICK {top['name']} [{top['venue']}] {top.get('_dip', '')} | buyers h1 {top['tx_h1'].get('buyers')} price h1 {top['pc_h1']:+.0f}% mcap ${top['mcap_usd']:,.0f} liq ${top['liquidity_usd']:,.0f} | RugCheck ok | meme dial {dial['dial']['meme']} (age {age:.1f}h)")
    if dry: _shadow(); return {"scan": sc, "decisions": decisions, "pick": top, "watchlist": wl, "shadow": sh}
    blk_i18 = pick_shadow_hook(top)   # I-18 gate (fail-open) + shadow fields; None = buy proceeds
    if blk_i18:
        log(f"[JUDGE] skip {ltag(top['base_token'])}{top['name']}: {blk_i18}"); _shadow([("main:blocked:i18", top, blk_i18)]); return
    # ---- SIZE ----
    meme_bank = ms["equity"]
    t1, t2 = FIXED_TICKET_USD, LIQ_CAP * top["liquidity_usd"]   # fixed 10 EUR (user order 2026-10-21)
    ticket = round(min(t1, t2, ms["cash"]), 2)
    fee_est, fr = total_fee(ticket, top["venue"], top["mcap_usd"], top["sol_usd"])
    if ticket < MIN_TICKET or fee_est >= 0.10 * ticket:
        log(f"[SIZE] skip: ticket ${ticket:.2f} (fixed 10 EUR = ${t1:.2f}, 2% liq=${t2:.2f}, cash ${ms['cash']:.2f}) "
            f"min ${MIN_TICKET:.2f}, fee ${fee_est:.3f}"); _shadow(); return
    log(f"[SIZE] ticket ${ticket:.2f} = min({TICKET_PCT:.0%} x meme bank ${meme_bank:.2f} x dial {dial['dial']['meme']} = ${t1:.2f}, 2% liq ${t2:.2f}); fee rate {fr:.2%} + ${NETWORK_FEE_USD + PRIORITY_FEE_USD:.3f} network/priority")
    # ---- FILLS (simulated) at a fresh live price: DexScreener first (0 GT calls), GT multi fallback (1 call, 15 s budget) ----
    a = None
    try: a = ds_prices([{"pool": top["pool"], "token": top["base_token"], "venue": "pumpswap", "sol_usd": top["sol_usd"]}]).get(top["pool"])
    except Exception as e: log(f"[FILLS] DexScreener refresh failed ({type(e).__name__}); GT fallback")
    if not a:
        try: a = pools_multi([top["pool"]], deadline=time.time() + 15).get(top["pool"])
        except Exception: a = None
    if not a: log(f"[FILLS] abort: could not refresh {top['pool']}"); _shadow(); return
    price = float(a["base_token_price_usd"]); sol = float(a.get("quote_token_price_usd") or top["sol_usd"])
    liq = float(a.get("reserve_in_usd") or top["liquidity_usd"])
    b = sim_buy(ticket, top["venue"], price, sol, liq, float(a.get("market_cap_usd") or top["mcap_usd"]))
    o = {"lead": lead_id(top["base_token"]), "pool": top["pool"], "token": top["base_token"], "name": top["name"], "venue": top["venue"], "url": top["url"],
         "entry_time": now().isoformat(), **b, "tp_done": False, "tp_hits": [], "stop_loss": STOP_LOSS[top["venue"]], "exit": MAIN_EXIT,
         "dip": top.get("_dip"), "src": top.get("src"), "wallet": top.get("wallet"), "last_check": now().isoformat(), "simulated": True}
    try:   # 2026-10-22 SELF-LEARN: entry features for the learner journal (recording only, no decision uses this)
        import learner as _learner; o["feat"] = _learner.features(top, o["entry_time"], top.get("base_token"))
    except Exception as e: log(f"[LEARN] entry features failed: {type(e).__name__}")
    try: blk = book_add(o, MAX_OPEN, TICKET_PCT)   # locked re-check vs the book as it is now (halt, caps, 1 per coin)
    except TimeoutError: blk = "positions lock busy"
    if blk:
        log(f"[FILLS] abort {ltag(top['base_token'])}{top['name']}: {blk} (book changed during the run)")
        _shadow([("main:blocked:max_open", top, "passed all gates; book full at fill time")] if "max" in blk else None); return
    log(f"[FILLS] BUY {ltag(top['base_token'])}{top['name']}{(' [Wallet: ' + str(top['wallet']['n']) + ' of ' + str(top['wallet']['of']) + ']') if top.get('wallet') else ''} (SIMULATED pump.fun {top['venue']}) ${ticket:.2f} @ {b['entry_price']:.10g} (mid {price:.10g}, slip {b['entry_slippage']:.2%}, fee ${b['entry_fee']:.4f} = {b['entry_fee_rate']:.2%} + ${NETWORK_FEE_USD + PRIORITY_FEE_USD:.3f}; rent deposit ${b['rent_usd']:.3f} refundable)")
    _shadow()

def risk_check(i, errs):
    """One fast exit check of the REAL book. Network (prices, new-pair safety) happens outside the lock; the state change
    (reload -> exits -> save) happens inside poslock, so pipeline/newpairs buys and these exits never overwrite each other."""
    p0 = load_pos()
    if not p0["open"]: return 0
    data = fast_prices(p0["open"], errs=errs)
    stale = [o["pool"] for o in p0["open"] if o["pool"] not in data and o.get("price_missing_since")
             and (now() - dt.datetime.fromisoformat(o["price_missing_since"])).total_seconds() >= STALE_GT_S]
    if stale and i in (0, 2):   # fallback: <= 2 GeckoTerminal calls/min, only while a held position has no price
        try:
            for k, v in pools_multi(stale, deadline=time.time() + 8).items(): data[k] = {**v, "_src": "geckoterminal fallback"}
        except Exception as e: errs.append(f"gt fallback {type(e).__name__}")
    saf, rc_at = {}, {}
    for o in p0["open"]:
        if o.get("sleeve") == "newpairs" and o["pool"] in data:
            try:
                import newpairs; saf[o["pool"]] = newpairs.position_safety(o); rc_at[o["pool"]] = o.get("np_rc_at")
            except Exception as e: errs.append(f"new-pair safety {type(e).__name__}")
    n = 0
    with poslock():
        p = load_pos()
        for o in list(p["open"]):
            if rc_at.get(o["pool"]): o["np_rc_at"] = rc_at[o["pool"]]
            a = data.get(o["pool"])
            if not a:   # 2026-10-20 risk audit: missing price never silently disables the stops -> loud + GT fallback
                o.setdefault("price_missing_since", now().isoformat())
                miss_s = (now() - dt.datetime.fromisoformat(o["price_missing_since"])).total_seconds()
                o["stale_s"] = round(miss_s)
                if i == 0 or miss_s >= STALE_WARN_S:
                    log(f"[RISK] {ltag(o.get('token'))}{o['name']}: NO PRICE for {miss_s:.0f}s (check {i+1}) -> stops cannot fire until a price arrives" + (" [STALE]" if miss_s >= STALE_WARN_S else ""))
                continue
            o.pop("price_missing_since", None); o.pop("stale_s", None)
            if a.get("_migrated_to") and o["venue"] == "bonding_curve":
                log(f"[RISK] {o['name']}: graduated -> pricing/exit on PumpSwap pair {a['_migrated_to']}")
                o["pool_original"] = o["pool"]; o["pool"] = a["_migrated_to"]; o["venue"] = "pumpswap"
            mark = float(a["base_token_price_usd"]); v = a.get("volume_usd") or {}
            ratio, vmode = vol_decay(v, a.get("pool_created_at"))
            o["last_price"] = mark; o["last_check"] = now().isoformat()
            o["vol_ratio"] = round(ratio, 3) if ratio is not None else None; o["vol_mode"] = vmode
            frac, why = exit_decision(o, mark, ratio, vmode, saf.get(o.get("pool_original") or o["pool"]) or saf.get(o["pool"]))
            n += 1
            if frac:
                close_position(o, a, why + f" [check {i+1}/{RISK_CHECKS}]", p, frac=frac); save_pos(p)
            elif i == 0:
                tag = f" [NEW PAIR {o.get('tier', '').upper()}]" if o.get("sleeve") == "newpairs" else ""
                log(f"[RISK] {ltag(o.get('token'))}{o['name']}{tag} {why} ok [{a.get('_src', 'dexscreener')}] (fast exits: {RISK_CHECKS} checks/min)")
        save_pos(p)
    return n

def dd_check(errs):
    eq, ms = desk_equity()
    if check_daily_dd(eq):
        p0 = load_pos()
        if not p0["open"]: return
        data = fast_prices(p0["open"], errs=errs)
        with poslock():
            p = load_pos()
            for o in list(p["open"]):
                if o["pool"] in data: close_position(o, data[o["pool"]], "daily 4% drawdown flat rule", p); save_pos(p)
            save_pos(p)

def risk():
    """Fast exits (upgrade 1): RISK_CHECKS checks per cron minute, RISK_STEP_S apart, real book first, then the shadow book.
    Exit rules: exit_decision(). Daily 4% drawdown rule once per minute (after check 1; needs the Alpaca P&L call)."""
    t0 = time.time(); signal.alarm(RISK_HARD_S); errs, done, durs = [], 0, []
    for i in range(RISK_CHECKS):
        wait = t0 + i * RISK_STEP_S - time.time()
        if wait > 0: time.sleep(wait)
        if time.time() - t0 > RISK_LAST_START_S: break
        ts = time.time()
        try: risk_check(i, errs)
        except Exception as e: errs.append(f"check {i+1}: {type(e).__name__}: {str(e)[:80]}")
        if i == 0:
            try: dd_check(errs)
            except Exception as e: errs.append(f"dd: {type(e).__name__}: {str(e)[:60]}")
        try:
            import shadow; shadow.check(i, deadline=t0 + RISK_LAST_START_S + 3)
        except Exception as e: errs.append(f"shadow {i+1}: {type(e).__name__}: {str(e)[:80]}")
        done += 1; durs.append(time.time() - ts)
    print(f"{now().astimezone(BER):%H:%M:%S} risk: {done} checks, max {max(durs or [0]):.1f}s, total {time.time()-t0:.1f}s" + (f" | errors: {'; '.join(errs[-4:])}" if errs else ""))
    if errs and any(not e.startswith(("dexscreener", "chain curve")) for e in errs): log(f"[RISK] fast-exit errors: {'; '.join(errs[-3:])}"[:300])

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "state"
    if cmd in ("pipeline", "dry"):   # pipeline runs never overlap each other; risk no longer waits for the pipeline
        lock = open(f"{DESK}/.meme.lock", "w"); fcntl.flock(lock, fcntl.LOCK_EX)   # (positions file: poslock per write)
    if cmd == "pipeline": pipeline()
    elif cmd == "dry": r = pipeline(dry=True); print(json.dumps({"decisions": (r or {}).get("decisions"), "reason": (r or {}).get("reason")}, indent=1, default=str))
    elif cmd == "risk": risk()
    else: print(json.dumps(meme_state(), indent=1, default=str))
