"""STEP 10 settings. Every setting has a range; out of range = refuse and say the range.
Values live in db.settings (key -> json); defaults below. Every change goes to db.change_log."""
from __future__ import annotations
import json, os, re
from . import db, util

# key: (default, type, min, max, label)
SPEC: dict[str, tuple] = {
    # Scanner
    "scanner.min_liquidity_usd": (40000, float, 0, 10_000_000, "min pool liquidity $"),
    "scanner.max_top10_pct": (25, float, 1, 100, "max top-10 holders %"),
    "scanner.max_h1_change_pct": (80, float, 0, 100_000, "max 1h price change %"),
    "scanner.poll_s": (60, int, 15, 600, "poll every s"),
    "scanner.min_pool_age_min": (10, int, 0, 240, "min pool age min"),
    "scanner.max_wait_min": (60, int, 5, 720, "max wait in room min"),
    "scanner.runner_h24_pct": (300, float, 0, 100_000, "runner = 24h change >= %"),
    "scanner.rocket_pullback_on": (True, bool, None, None, "h1 rocket waits for a pullback instead of a kill"),
    "scanner.rocket_pullback_pct": (15, float, 1, 90, "rocket passes after pulling back >= % from its room peak"),
    "scanner.established_on": (True, bool, None, None, "second scanner: established pump.fun coins"),
    "scanner.established_every_min": (10, int, 2, 240, "established scan every min"),
    "scanner.established_min_age_days": (1, float, 0, 3650, "established min pool age days"),
    "scanner.established_max_age_days": (30, float, 0, 3650, "established max pool age days"),
    "scanner.established_min_liq_usd": (100000, float, 0, 100_000_000, "established min PumpSwap liquidity $"),
    "scanner.established_cooldown_h": (6, float, 0.5, 168, "re-analyse an established coin at most every h"),
    "scanner.established_max_per_scan": (10, int, 1, 100, "established coins added to the room per scan"),
    # Auditor
    "auditor.enabled": (True, bool, None, None, "take apart before buying"),
    "auditor.max_dev_pct": (5, float, 0, 100, "max dev holding %"),
    "auditor.max_top10_pct": (25, float, 1, 100, "max top-10 %"),
    "auditor.min_lp_locked_pct": (99, float, 0, 100, "min LP burned/locked %"),
    "auditor.max_liq_drop_pct": (50, float, 0, 100, "max liquidity drop since Scanner %"),
    "auditor.min_pool_age_min": (10, int, 0, 240, "min pool age min"),
    "auditor.max_bundled": (5, int, 1, 1000, "max bundled wallets"),
    "auditor.max_delegated_accounts": (10, int, 1, 10_000, "max accounts on one delegate"),
    "auditor.retries": (3, int, 1, 10, "retries per layer"),
    # Analyst
    "analyst.mode": ("jev", str, ["jev", "rules"], None, "jev or rules"),
    "analyst.min_alive_6h": (0.70, float, 0, 1, "min alive_6h"),
    "analyst.min_organic": (0.65, float, 0, 1, "min organic"),
    "analyst.max_chase": (0.30, float, 0, 1, "max chase"),
    "analyst.min_score": (70, int, 0, 100, "min score"),
    "analyst.timeout_s": (10, float, 1, 60, "Jev timeout s"),
    "analyst.max_state_chars": (3000, int, 500, 20000, "max STATE chars"),
    "analyst.extra_data_on": (True, bool, None, None, "Jev gets holder trend, buyers/sellers, top-holder wallet age"),
    "analyst.rules_alive_volume_h1": (25000, float, 0, 10_000_000, "rules: alive if 1h volume >= $"),
    "analyst.rules_organic_buys_h1": (150, int, 0, 100_000, "rules: organic if 1h buys >="),
    "analyst.rules_bundled_penalty": (0.5, float, 0, 1, "rules: organic x this if bundled"),
    "analyst.rules_bundled_from": (3, int, 1, 1000, "rules: bundled from N wallets"),
    "analyst.rules_flush_drop_m5_pct": (5, float, 0, 100, "rules: flush done if 5m dropped >= %"),
    "analyst.rules_chase_h1_pct": (80, float, 0, 100_000, "rules: chase if 1h up > %"),
    # Executor
    "executor.stack_pct": (8, float, 0.1, 100, "size % of stack"),
    "executor.max_pool_pct": (2, float, 0.01, 100, "max % of pool liquidity"),
    "executor.borderline_on": (True, bool, None, None, "smaller ticket for borderline passes"),
    "executor.borderline_stack_pct": (4, float, 0.1, 100, "borderline size % of stack"),
    "executor.min_ticket_usd": (47.50, float, 0, 100_000, "min ticket $"),
    "executor.below_min": ("off", str, ["off", "bump", "skip"], None, "below min ticket: off|bump|skip"),
    "executor.recheck_liq_drop_pct": (20, float, 0, 100, "skip if liquidity down > %"),
    "executor.recheck_price_up_pct": (15, float, 0, 1000, "skip if price up > %"),
    "executor.confirm_window_min": (5, int, 1, 60, "confirm window min"),
    # Risk
    "risk.poll_s": (15, int, 5, 300, "poll every s"),
    "risk.stop_pct": (6, float, 0.5, 90, "stop %"),
    "risk.trail_start_pct": (20, float, 1, 10_000, "trail starts at +%"),
    "risk.trail_pct": (12, float, 0.5, 90, "trail % off the top"),
    "risk.timeout_h": (3, float, 0.25, 72, "timeout h"),
    "risk.timeout_min_gain_pct": (5, float, -100, 10_000, "timeout unless up >= %"),
    "risk.confirm_window_min": (2, int, 1, 60, "exit confirm window min"),
    "risk.no_price_polls": (4, int, 1, 100, "push after N polls with no price"),
    # Fees model (fees.py)
    "fees.gas_sol_per_side": (0.0005, float, 0, 0.1, "network+priority fee SOL per side"),
    "fees.extra_slippage_pct": (0.5, float, 0, 20, "slippage on top of price impact % per side"),
    # Desk
    "desk.mode": ("PAPER", str, ["PAPER", "LIVE"], None, "PAPER or LIVE"),
    "desk.paper_start_stack": (200, float, 1, 10_000_000, "PAPER start stack $"),
    "desk.live_stack": (0, float, 0, 10_000_000, "LIVE stack $ (you report it)"),
    "desk.report_time": ("08:00", str, r"^([01]\d|2[0-3]):[0-5]\d$", None, "report time HH:MM Berlin"),
    "desk.notifier": ("webpush", str, ["webpush"], None, "notifier"),
    "desk.rpc_url": ("https://mainnet.helius-rpc.com/?api-key=${HELIUS_API_KEY}", str, r"^https://", None, "RPC url template"),
    "desk.push_rejects": (False, bool, None, None, "push Auditor/Analyst rejects"),
    "desk.shadow_on": (True, bool, None, None, "shadow list: re-read rejected coins at +6h/+24h"),
    "desk.shadow_keep_days": (14, int, 2, 365, "keep shadow rows days"),
}

ALIASES = {"stop": "risk.stop_pct", "trail": "risk.trail_pct", "trail_start": "risk.trail_start_pct",
           "timeout": "risk.timeout_h", "size": "executor.stack_pct", "min_score": "analyst.min_score",
           "min_liquidity": "scanner.min_liquidity_usd", "liquidity": "scanner.min_liquidity_usd",
           "top10": "scanner.max_top10_pct", "dev": "auditor.max_dev_pct", "bundled": "auditor.max_bundled",
           "below_min": "executor.below_min", "min_ticket": "executor.min_ticket_usd", "report": "desk.report_time",
           "analyst": "analyst.mode", "push_rejects": "desk.push_rejects"}

class SettingError(ValueError):
    pass

def resolve_key(k: str) -> str:
    k = k.strip().lower().replace(" ", "_")
    if k in SPEC: return k
    if k in ALIASES: return ALIASES[k]
    hits = [s for s in SPEC if s.split(".", 1)[1] == k]
    if len(hits) == 1: return hits[0]
    raise SettingError(f"unknown setting '{k}'")

def _coerce(key: str, v):
    d, typ, lo, hi, _ = SPEC[key]
    if typ is bool:
        if isinstance(v, bool): return v
        s = str(v).strip().lower()
        if s in ("1", "true", "on", "yes"): return True
        if s in ("0", "false", "off", "no"): return False
        raise SettingError(f"{key} must be on or off")
    if typ is str:
        s = str(v).strip()
        if key in ("desk.mode", "analyst.mode", "executor.below_min"):
            s = s.upper() if key == "desk.mode" else s.lower()
        if isinstance(lo, list):
            if s not in lo: raise SettingError(f"{key} must be one of {', '.join(lo)}")
        elif isinstance(lo, str) and not re.match(lo, s):
            raise SettingError(f"{key} has the wrong format")
        return s
    try:
        n = typ(float(str(v).replace("%", "").replace("$", "").replace(",", "")))
    except Exception:
        raise SettingError(f"{key} must be a number")
    if n < lo or n > hi:
        raise SettingError(f"{key} must be between {lo:g} and {hi:g}")
    return n

def get(key: str):
    key = resolve_key(key)
    r = db.one("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else SPEC[key][0]

def all_settings() -> dict:
    stored = {r["key"]: json.loads(r["value"]) for r in db.q("SELECT key, value FROM settings")}
    return {k: stored.get(k, v[0]) for k, v in SPEC.items()}

def set(key: str, value, who: str = "app") -> tuple:
    key = resolve_key(key)
    if key == "desk.mode" and str(value).upper() == "LIVE":
        raise SettingError("LIVE is locked. The desk runs PAPER only")
    if key == "desk.stack":
        raise SettingError("use desk.live_stack")
    new = _coerce(key, value)
    old = get(key)
    db.x("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
         (key, json.dumps(new), util.iso()))
    db.insert("change_log", ts=util.iso(), key=key, old=json.dumps(old), new=json.dumps(new), who=who)
    return key, old, new

def describe() -> list[dict]:
    cur = all_settings()
    out = []
    for k, (d, typ, lo, hi, label) in SPEC.items():
        if k == "desk.rpc_url":
            cur_v = "https://mainnet.helius-rpc.com/?api-key=${HELIUS_API_KEY}" if "${HELIUS_API_KEY}" in str(cur[k]) else "(custom, hidden)"
        else:
            cur_v = cur[k]
        out.append({"key": k, "value": cur_v, "default": d, "type": typ.__name__,
                    "min": lo if not isinstance(lo, (list, str)) else None,
                    "max": hi, "choices": lo if isinstance(lo, list) else None, "label": label})
    return out

def rpc_url() -> str:
    """built at runtime from env; never logged."""
    t = get("desk.rpc_url")
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), t)

def stack() -> float:
    from . import account
    return account.equity()

def ticket_check() -> str | None:
    """STEP 10 ticket check. min_stack = min_ticket_usd / (stack_pct/100). below_min 'off' (desk default, approved) = no min ticket."""
    mode = get("executor.below_min")
    if mode == "off":
        return None
    st, pct, mt = stack(), get("executor.stack_pct"), get("executor.min_ticket_usd")
    min_stack = mt / (pct / 100)
    if st >= min_stack:
        return None
    if mode == "bump":
        return f"tickets bumped to ${mt:,.2f} = {mt / st * 100:.1f}% of stack"
    return f"every coin will be skipped, stack under ${min_stack:,.2f}. Switch below_min to bump or raise the stack."
