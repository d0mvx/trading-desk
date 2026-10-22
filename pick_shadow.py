#!/usr/bin/env python3
"""SHADOW fields for the main-sleeve final pick (2026-10-21, research I-18 + V-01). PAPER, read-only public data, no keys.
V-01 never changes a decision. I-18 gates only via meme.I18_GATE_ENABLED (True since 2026-10-21 19:24, Dominic); this file only logs.
- I-18 twin share: among BUYS of the last 15 min before the pick (<= 100 most recent trades, ONE pump.fun swap-api call),
  share of buys for which another wallet bought the identical SOL amount (4 dp) in the same second. Would block at >= 0.50
  (OOS: tests/backtest/reports/youtube_ideas.md, I-18 FINAL).
- V-01 fresh count: of the top-12 buyers by SOL in that window, how many have their first on-chain signature < 24 h before
  their buy (getSignaturesForAddress before = their buy tx, limit 300; 300 = old). Public Solana RPC only (no pump.fun calls).
Output: one JSON line per pick in ~/.desk/logs/pick_shadow.jsonl. Any error -> field null + error text; never raises.
CLI (spawned detached by meme.py, wrapped in `timeout 60`): pick_shadow.py '<json {token, name, venue, lead, pick_ts, i18?}>'"""
import os, sys, json, time, threading, datetime as dt
import requests
DESK = os.path.expanduser("~/.desk"); OUT = f"{DESK}/logs/pick_shadow.jsonl"
SWAP = "https://swap-api.pump.fun"; UA = {"User-Agent": "Mozilla/5.0 (desk-meme/1.0)", "Accept": "application/json"}
RPCS = ["https://solana-rpc.publicnode.com", "https://api.mainnet-beta.solana.com"]
WINDOW_S, TWIN_BLOCK, FRESH_BLOCK, TOPN = 900, 0.50, 9, 12
def _ts(s): return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
def fetch_tape(mint, t, timeout=5):
    cur = f"999999999999{0:06d}{0:08d}-{int(t * 1000)}"
    r = requests.get(f"{SWAP}/v2/coins/{mint}/trades", params={"limit": 100, "cursor": cur}, headers=UA, timeout=(3, timeout))
    r.raise_for_status(); return r.json().get("trades") or []
def twin_features(trades, t):
    b = [x for x in trades if x.get("type") == "buy" and t - WINDOW_S <= _ts(x["timestamp"]) < t + 1]
    out = {"i18_n_buys": len(b), "i18_twin_share": None, "top": []}
    if not b: return out
    amt = [round(float(x.get("amountSol") or 0), 4) for x in b]; sec = [int(_ts(x["timestamp"])) for x in b]; usr = [x.get("userAddress") for x in b]
    twin = sum(1 for i in range(len(b)) if any(j != i and sec[j] == sec[i] and amt[j] == amt[i] and usr[j] != usr[i] for j in range(len(b))))
    out["i18_twin_share"] = round(twin / len(b), 4)
    agg = {}
    for x, a in zip(b, amt):
        e = agg.setdefault(x.get("userAddress"), {"sol": 0.0, "tx": x.get("tx"), "ts": _ts(x["timestamp"])}); e["sol"] += a
    out["top"] = [[w, e["tx"], e["ts"]] for w, e in sorted(agg.items(), key=lambda kv: -kv[1]["sol"])[:TOPN] if w]
    return out
def twin_share_sync(mint, t, timeout):
    """For the (disabled) live gate: run the tape call in a thread, give up after `timeout` s -> None (never blocks a buy)."""
    res = {}
    def run():
        try: res["v"] = twin_features(fetch_tape(mint, t, timeout), t)
        except Exception as e: res["err"] = f"{type(e).__name__}"
    th = threading.Thread(target=run, daemon=True); th.start(); th.join(timeout)
    return res.get("v")
def wallet_fresh(w, sig, buy_ts):
    for u in RPCS:
        try:
            r = requests.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [w, {"limit": 300, "before": sig}]},
                              headers={"content-type": "application/json"}, timeout=(3, 8))
            j = r.json()
            if "result" in j:
                bt = [s.get("blockTime") for s in j["result"] if s.get("blockTime")]
                return len(j["result"]) < 300 and (not bt or buy_ts - min(bt) < 86400)
        except Exception: pass
        time.sleep(0.4)
    return None
def run(args):
    t = float(args.get("pick_ts") or time.time()); rec = {"ts": dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(), **{k: args.get(k) for k in ("lead", "token", "name", "venue", "sleeve", "blocked", "note")},
         "i18_gate_enabled": bool(args.get("gate_enabled")), "i18_twin_share": None, "i18_n_buys": None, "i18_would_block": None,
         "v01_n_top": None, "v01_n_known": None, "v01_n_fresh": None, "v01_would_block": None, "errors": []}
    f = args.get("i18")
    if f is None:
        try: f = twin_features(fetch_tape(args["token"], t), t)
        except Exception as e: rec["errors"].append(f"tape {type(e).__name__}")
    if f:
        rec["i18_twin_share"], rec["i18_n_buys"] = f.get("i18_twin_share"), f.get("i18_n_buys")
        if f.get("i18_twin_share") is not None: rec["i18_would_block"] = f["i18_twin_share"] >= TWIN_BLOCK
        top = f.get("top") or []; known = fresh = 0
        for w, sig, bts in top:
            v = wallet_fresh(w, sig, bts)
            if v is None: continue
            known += 1; fresh += int(v)
        rec["v01_n_top"], rec["v01_n_known"], rec["v01_n_fresh"] = len(top), known, fresh
        rec["v01_would_block"] = fresh >= FRESH_BLOCK if top else None
    rec["done_s"] = round(time.time() - t, 1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as fh: fh.write(json.dumps(rec) + "\n")
    return rec
if __name__ == "__main__":
    try: run(json.loads(sys.argv[1]))
    except Exception as e:
        try:
            with open(OUT, "a") as fh: fh.write(json.dumps({"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "errors": [f"fatal {type(e).__name__}: {str(e)[:120]}"]}) + "\n")
        except Exception: pass
