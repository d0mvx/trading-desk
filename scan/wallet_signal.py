#!/usr/bin/env python3
"""Wallet signal (PAPER desk, read-only chain data, no keys). 2026-10-20, user request.
Records recent BUYS (last 6 h) of the wallets vetted as COPYABLE into scan/wallet_signal.json:
  {"updated_at", "wallets": [...], "of": N, "mints": {mint: {"wallets": [...], "first_buy_ts", "sol", "buys"}}, "errors"}
Used by SCAN only as an extra candidate source + ranking boost (1 wallet ranks up, 2+ higher). Every candidate still
goes through ALL scan/Judge/RugCheck/dip/cooldown gates. Sells are NOT copied. No trading happens here.
2026-10-21 00:4x: EwJYY4 moved to OBSERVE as well -> no COPYABLE wallet left, "mints" stays empty.
2026-10-20 23:2x: 215nhc moved from COPYABLE to OBSERVE (recorded in "observe_mints" only, no signal), see CHANGELOG_research.md.
Vetting 2026-10-20 (see README): COPYABLE = 215nhc... (whale, human pace, graduated PumpSwap coins, holds hours)
and EwJYY4... (low-frequency swing trader, mostly non-pump.fun tokens). Rejected: 29yFze (INSIDER-DEV: creates+dumps own
coins in seconds), 3VUNtV (SNIPER/fast scalper, median hold 77 s), FLyBjf (MEV/arb bot vault, never signs, inactive since 07:09).
Polite RPC: public keyless endpoints, <= ~1 sig call + <= MAX_TX tx calls per wallet per run, 0.3 s spacing, 25 s budget."""
import os, sys, json, time, requests
DESK = os.path.expanduser("~/.desk")
OUT = f"{DESK}/scan/wallet_signal.json"; STATE = f"{DESK}/scan/wallet_signal_state.json"
WALLETS = {}          # COPYABLE -> exported in "mints" (scan source + rank boost). 2026-10-21 00:4x: empty (EwJYY4 -> OBSERVE)
# 2026-10-20 23:2x (research): 215nhc is NOT copyable (I-13 copy test: copy @10 s -13 %/trade, median -42 %, 699 coins/90 d; edge gone
# after ~5 s; whale buys move the price; 25 copytrader wallets in the same/next slot). OBSERVE = still recorded, but ONLY under
# "observe_mints"; never in "mints", so scan/sources never see it as a candidate source or rank boost.
# 2026-10-21 00:4x: EwJYY4 also NOT copyable (Trader-Research: realised -316 SOL, 5/30 winners) -> OBSERVE.
OBSERVE = {"215nhcAHjQQGgwpQSJQ7zR26etbjjtVdW74NLzwEgQjP": "215n", "EwJYY4q2rcrdEH26doRbYX9JxbpYPSNZvRLgzhPKi418": "EwJY"}
TRACKED = {**WALLETS, **OBSERVE}
RPCS = ["https://solana-rpc.publicnode.com", "https://api.mainnet-beta.solana.com"]
WINDOW_S = 6 * 3600; MAX_TX = 12; SIG_LIMIT = 100; BUDGET_S = 25; SPACING = 0.3
WSOL = "So11111111111111111111111111111111111111112"
STABLE = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
UA = {"content-type": "application/json", "User-Agent": "curl/8.5.0 (desk-wallet-signal)"}
T0 = time.time(); DRY = "--dry" in sys.argv

def rpc(method, params, errs):
    for u in RPCS:
        if time.time() - T0 > BUDGET_S: raise TimeoutError("budget")
        try:
            r = requests.post(u, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers=UA, timeout=8)
            time.sleep(SPACING)
            if r.status_code == 200 and "result" in r.json(): return r.json()["result"]
            errs.append(f"{u.split('//')[1][:12]} {method} {r.status_code}")
        except Exception as e:
            errs.append(f"{u.split('//')[1][:12]} {method} {type(e).__name__}")
    return None

def sol_usd(st):
    if time.time() - st.get("sol_usd_at", 0) < 1800 and st.get("sol_usd"): return st["sol_usd"]
    try:
        v = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5).json()["solana"]["usd"]
        st["sol_usd"], st["sol_usd_at"] = float(v), time.time()
    except Exception: pass
    return st.get("sol_usd") or 150.0

def parse_buy(t, w, solusd):
    """BUY = wallet signed, exactly one non-quote token increased, quote (SOL/WSOL/USDC/USDT) decreased."""
    if not t or t["meta"]["err"]: return None
    keys = t["transaction"]["message"]["accountKeys"]
    if not any(k["pubkey"] == w and k.get("signer") for k in keys): return None
    m = t["meta"]; i = [k["pubkey"] for k in keys].index(w)
    q = (m["postBalances"][i] - m["preBalances"][i]) / 1e9; tok = {}
    for sgn, arr in ((-1, m.get("preTokenBalances") or []), (1, m.get("postTokenBalances") or [])):
        for b in arr:
            if b.get("owner") == w: tok[b["mint"]] = tok.get(b["mint"], 0) + sgn * float(b["uiTokenAmount"]["uiAmount"] or 0)
    q += tok.pop(WSOL, 0)
    for s in STABLE: q += tok.pop(s, 0) / solusd
    tok = {k: v for k, v in tok.items() if abs(v) > 1e-9}
    if len(tok) == 1 and list(tok.values())[0] > 0 and q < 0:
        return {"mint": list(tok)[0], "sol": round(-q, 4)}
    return None

def main():
    try: st = json.load(open(STATE))
    except (FileNotFoundError, ValueError): st = {}
    seen = st.setdefault("seen", {}); buys = st.setdefault("buys", [])
    errs = []; now = time.time(); solusd = sol_usd(st); stats = {}
    try:
        for w, tag in TRACKED.items():
            sigs = rpc("getSignaturesForAddress", [w, {"limit": SIG_LIMIT}], errs) or []
            sw = set(seen.get(w, []))
            todo = [s for s in sigs if not s.get("err") and (s.get("blockTime") or 0) >= now - WINDOW_S and s["signature"] not in sw]
            n = 0
            for s in todo[:MAX_TX]:
                t = rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}], errs)
                if t is None: continue
                sw.add(s["signature"]); n += 1
                b = parse_buy(t, w, solusd)
                if b: buys.append({"wallet": w, "ts": t["blockTime"], "sig": s["signature"], **b})
            seen[w] = [s["signature"] for s in sigs if s["signature"] in sw][:SIG_LIMIT * 2]
            stats[tag] = {"sigs": len(sigs), "pending": len(todo) - n, "fetched": n}
    except TimeoutError: errs.append("budget 25 s reached; rest next run")
    buys[:] = [b for b in buys if b["ts"] >= now - WINDOW_S]
    mints, obs = {}, {}
    for b in sorted(buys, key=lambda b: b["ts"]):
        if b["wallet"] not in TRACKED: continue
        e = (mints if b["wallet"] in WALLETS else obs).setdefault(b["mint"], {"wallets": [], "first_buy_ts": b["ts"], "sol": 0.0, "buys": 0})
        if b["wallet"] not in e["wallets"]: e["wallets"].append(b["wallet"])
        e["sol"] = round(e["sol"] + b["sol"], 4); e["buys"] += 1
    out = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "updated_ts": int(now), "window_h": WINDOW_S / 3600,
           "wallets": list(WALLETS), "tags": WALLETS, "of": len(WALLETS), "mints": mints,
           "observe": list(OBSERVE), "observe_tags": OBSERVE, "observe_mints": obs, "stats": stats, "errors": errs[-10:],
           "note": "signal only: candidates must still pass every SCAN/Judge/RugCheck gate; sells are never copied; paper only"}
    if DRY: print(json.dumps(out, indent=1)); return
    for path, d in ((STATE, st), (OUT, out)):
        tmp = path + ".tmp"; json.dump(d, open(tmp, "w")); os.replace(tmp, path)
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S %Z')} wallet_signal: {len(mints)} mint(s) bought in 6h {stats} {('errors ' + str(len(errs))) if errs else ''} {time.time()-T0:.1f}s")

if __name__ == "__main__": main()
