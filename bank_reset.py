#!/usr/bin/env python3
"""Start a new MEME bank epoch. PAPER only. Alpaca sleeves are never touched (separate book).
EXCEPTION: with --start-eur N (USER ORDER 2026-10-24 21:27: 100 EUR) the new bank is N EUR, no SOL quote, for that reset only.
STANDING RULE (USER ORDER 2026-10-23 19:23): on EVERY reset the new meme bank = the live price of 1 SOL in EUR at
reset time. The bank stays EUR-denominated as before (accounting in USD via meme.EURUSD, start_eur shown on the dashboard),
the SOL/EUR price used is recorded in bank.json (sol_eur_start, sol_source). Price = median of CoinGecko SOL/EUR and
Kraken SOLEUR (sanity 10..1000 EUR); if no quote passes -> abort, nothing changed (never guess).
History: epoch 2 = USER ORDER 2026-10-21 20:19 (flat 100 EUR, run by hand on the box); epoch 3 = USER ORDER 2026-10-23
19:15/19:23 (1 SOL in EUR, run ONCE on the GitHub runner via gh/crontab.gh with --once, so the runner itself writes the
new state: no race between a box commit and the runner's 5-min state commits).
Under the positions lock: close every open meme position (main + new pairs) at the live DexScreener mark with the normal
simulated exit (slippage + fees, reason 'reset: ...'), drop the cooldowns those reset closes created (reset != loss
signal), archive the closed book of the old epoch (archive/, mirrored to branch state), start the new epoch in bank.json
(start_capital = new start in USD, started_at = now, previous epochs listed), rotate history.csv, reset today's risk
day-open equity (explicit epoch_reset journal record). Ticket (10 EUR), caps, stops unchanged.
CLI: bank_reset.py [--order "YYYY-MM-DD HH:MM"] [--once] [--dry]
  --once: do nothing if bank.json already carries reset_order == --order (idempotent cron one-shot)."""
import os, sys, json, shutil, argparse, statistics, urllib.request, datetime as dt
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
import meme

WSOL = "So11111111111111111111111111111111111111112"

def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "desk-paper/1.0", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def sol_eur(fetch=_get):
    """Live SOL/EUR = median of CoinGecko + Kraken. Returns (price, sources). Raises if nothing sane (-> abort reset)."""
    q = {}
    try: q["coingecko"] = float(fetch("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=eur")["solana"]["eur"])
    except Exception: pass
    try:
        r = fetch("https://api.kraken.com/0/public/Ticker?pair=SOLEUR")
        if not r.get("error"): q["kraken"] = float(next(iter(r["result"].values()))["c"][0])
    except Exception: pass
    q = {k: v for k, v in q.items() if 10 <= v <= 1000}
    if not q: raise RuntimeError("no sane SOL/EUR quote (CoinGecko + Kraken failed) -> reset aborted, nothing changed")
    return round(statistics.median(q.values()), 2), "+".join(sorted(q))

def main(dry=False, order=None, once=False, price_fn=None, start_eur=None):
    bank0 = json.load(open(f"{DESK}/bank.json"))
    if once and order and bank0.get("reset_order") == order: return None      # already done
    now = meme.now(); nb = now.astimezone(meme.BER); tag = nb.strftime("%Y%m%d_%H%M"); order = order or f"{nb:%Y-%m-%d %H:%M}"
    if start_eur is not None:                                                  # explicit EUR amount (USER ORDER 2026-10-24 21:27: 100 EUR): no SOL quote needed
        px, src = None, "explicit"; start_eur_v = float(start_eur)
        label = f"{start_eur_v:.2f} EUR (fixed, USER ORDER {order})"
    else:
        px, src = (price_fn or sol_eur)()                                      # raises before any change if no quote
        start_eur_v = px; label = f"{start_eur_v:.2f} EUR (= 1 SOL @ {px:.2f} EUR/SOL, {src})"
    start_usd = round(start_eur_v * meme.EURUSD, 2)
    arch = f"{DESK}/archive"; os.makedirs(arch, exist_ok=True)
    with meme.poslock(wait=60):
        p = meme.load_pos(); reset_keys = set()
        if p["open"]:
            a = meme.ds_prices(p["open"])
            missing = [o["name"] for o in p["open"] if o["pool"] not in a]
            if missing: raise SystemExit(f"no DexScreener mark for {missing} -> abort, nothing changed")
            if dry:
                for o in p["open"]: print("[DRY] would close", o["name"], meme.sim_sell(o, a[o["pool"]]))
                print("[DRY] new start", label); return None
            for o in list(p["open"]):
                reset_keys |= {o.get("token"), o.get("pool"), o.get("pool_original")} - {None}
                meme.close_position(o, a[o["pool"]], f"reset: bank reset to {label} (USER ORDER {order})", p)
            meme.save_pos(p)
        if dry: print("[DRY] no open positions; new start", label); return None
        if reset_keys: drop_reset_cooldowns(reset_keys)
        ms = meme.meme_state(p); bank = json.load(open(f"{DESK}/bank.json"))
        n = len(bank.get("epochs", [])) + 1
        prev = {"epoch": n, "start_usd": float(bank["start_capital"]), "started_at": bank["started_at"],
                "ended_at": nb.isoformat(timespec="seconds"), "end_equity_usd": round(ms["equity"], 4), "realized_usd": round(ms["realized"], 4),
                "closed_trades": len(ms["closed"]), "wins": ms["wins"], "losses": ms["losses"],
                "archive": f"archive/meme_epoch{n}_{tag}.json", "history": f"archive/history_epoch{n}_{tag}.csv"}
        if bank.get("start_eur") is not None: prev["start_eur"] = bank["start_eur"]
        if bank.get("sol_eur_start") is not None: prev["sol_eur_start"] = bank["sol_eur_start"]
        json.dump({"summary": prev, "closed": p["closed"]}, open(f"{DESK}/{prev['archive']}", "w"), indent=1, default=str)
        p["closed"] = []; meme.save_pos(p)
        bank.setdefault("epochs", []).append(prev)
        bank.update({"start_capital": start_usd, "start_eur": start_eur_v, "eurusd": meme.EURUSD, "started": nb.date().isoformat(),
                     "started_at": nb.isoformat(timespec="seconds"), "epoch": n + 1, "reset_order": order,
                     "epoch_note": f"epoch {n + 1}: fresh start {label} (USER ORDER {order}); accounting in USD; previous epochs in 'epochs', archived books in archive/"})
        if start_eur is None:
            bank.update(sol_eur_start=px, sol_source=src, bank_rule="start = 1 SOL in EUR at reset (USER ORDER 2026-10-23 19:23)")
        else:   # one-off exception by explicit order; the standing 1-SOL rule applies again at the next reset without --start-eur
            bank.update(bank_rule=f"epoch {n + 1}: explicit start {start_eur_v:.2f} EUR (USER ORDER {order}); standing rule 'start = 1 SOL in EUR at reset' (2026-10-23 19:23) unchanged for future resets")
            bank.pop("sol_eur_start", None); bank.pop("sol_source", None)
        tmp = f"{DESK}/bank.json.tmp"; json.dump(bank, open(tmp, "w"), indent=1); os.replace(tmp, f"{DESK}/bank.json")
        h = f"{DESK}/history.csv"
        if os.path.exists(h): shutil.move(h, f"{DESK}/{prev['history']}")
        with open(h, "w") as f:
            f.write("timestamp_berlin,desk_equity,desk_cash,realized,unrealized\n")
            f.write(f"{nb.isoformat(timespec='seconds')},{start_usd:.4f},{start_usd:.4f},0.0000,0.0000\n")
    try:   # fresh epoch = fresh loss-streak counter (a pause earned with the old bank must not block the new one)
        import entry_rules; entry_rules._save({"streak": 0, "paused_until": None, "history": entry_rules._load().get("history", [])[-20:]})
    except Exception as e: meme.log(f"[BANK] loss-streak reset failed: {type(e).__name__}")
    with meme.poslock(path=f"{DESK}/.riskstate.lock"):
        rs = {"date": nb.date().isoformat(), "day_open_equity": start_usd, "halted": False, "epoch_reset": nb.isoformat(timespec="seconds")}
        with open(meme.RISK_JOURNAL, "a") as f: f.write(json.dumps(rs) + "\n")
        tmp = meme.RISKST + ".tmp"; json.dump(rs, open(tmp, "w"), indent=1); os.replace(tmp, meme.RISKST)
    meme.log(f"[BANK] new epoch {n + 1}: meme bank reset to {label} (USER ORDER {order}); epoch {n} ended at "
             f"${prev['end_equity_usd']:.2f} (realized {prev['realized_usd']:+.2f}, {prev['closed_trades']} closes, {prev['wins']}W/{prev['losses']}L), archived {prev['archive']}")
    print(json.dumps(prev, indent=1)); print("new start", label)
    return prev

def drop_reset_cooldowns(keys):
    """Remove the cooldown entries the reset closes just created (a reset is not a loss signal)."""
    import scan
    try:
        d = json.load(open(scan.COOLDOWN_FILE))
        for k in list(keys):
            v = d.get(k) if isinstance(d, dict) else None
            if isinstance(v, dict) and str(v.get("reason", "")).startswith("reset:"): d.pop(k)
        tmp = scan.COOLDOWN_FILE + ".tmp"; json.dump(d, open(tmp, "w"), indent=1); os.replace(tmp, scan.COOLDOWN_FILE)
    except Exception as e: meme.log(f"[BANK] cooldown cleanup failed: {type(e).__name__}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--order"); ap.add_argument("--once", action="store_true"); ap.add_argument("--dry", action="store_true")
    ap.add_argument("--start-eur", type=float, default=None, help="explicit start bank in EUR instead of 1 SOL (one-off, by explicit user order)")
    a = ap.parse_args()
    main(dry=a.dry, order=a.order, once=a.once, start_eur=a.start_eur)
