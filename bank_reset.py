#!/usr/bin/env python3
"""Start a new MEME bank epoch (USER ORDER 2026-10-21 20:19 "der bot soll wieder mit 100€ anfangen"). PAPER only.
Under the positions lock: close every open meme position (main + new pairs) at the live DexScreener mark with the normal
simulated exit (slippage + fees, reason 'reset: ...'), archive the closed book of the old epoch, start the new epoch in
bank.json (start_capital = new start, started_at = now, previous epochs listed), rotate history.csv, reset today's
risk day-open equity (halt flag cleared via an explicit epoch_reset journal record; DAILY_DD_ENABLED unchanged)."""
import os, sys, json, shutil, datetime as dt
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
import meme

def main(start_eur=100.0, dry=False):
    start_usd = round(start_eur * meme.EURUSD, 2)
    now = meme.now(); nb = now.astimezone(meme.BER); tag = nb.strftime("%Y%m%d_%H%M")
    arch = f"{DESK}/archive"; os.makedirs(arch, exist_ok=True)
    with meme.poslock(wait=60):
        p = meme.load_pos()
        if p["open"]:
            a = meme.ds_prices(p["open"])
            missing = [o["name"] for o in p["open"] if o["pool"] not in a]
            if missing: raise SystemExit(f"no DexScreener mark for {missing} -> abort, nothing changed")
            if dry:
                for o in p["open"]: print("[DRY] would close", o["name"], meme.sim_sell(o, a[o["pool"]]))
                return
            for o in list(p["open"]):
                meme.close_position(o, a[o["pool"]], f"reset: bank reset to {start_eur:.0f} EUR (USER ORDER {nb:%Y-%m-%d %H:%M})", p)
            meme.save_pos(p)
        if dry: print("[DRY] no open positions"); return
        ms = meme.meme_state(p); bank = json.load(open(f"{DESK}/bank.json"))
        prev = {"epoch": len(bank.get("epochs", [])) + 1, "start_usd": float(bank["start_capital"]), "started_at": bank["started_at"],
                "ended_at": nb.isoformat(timespec="seconds"), "end_equity_usd": round(ms["equity"], 4), "realized_usd": round(ms["realized"], 4),
                "closed_trades": len(ms["closed"]), "wins": ms["wins"], "losses": ms["losses"],
                "archive": f"archive/meme_epoch{len(bank.get('epochs', [])) + 1}_{tag}.json", "history": f"archive/history_epoch{len(bank.get('epochs', [])) + 1}_{tag}.csv"}
        json.dump({"summary": prev, "closed": p["closed"]}, open(f"{DESK}/{prev['archive']}", "w"), indent=1, default=str)
        p["closed"] = []; meme.save_pos(p)
        bank.setdefault("epochs", []).append(prev)
        bank.update({"start_capital": start_usd, "start_eur": start_eur, "eurusd": meme.EURUSD, "started": nb.date().isoformat(),
                     "started_at": nb.isoformat(timespec="seconds"), "epoch": prev["epoch"] + 1,
                     "epoch_note": f"epoch {prev['epoch'] + 1}: fresh start {start_eur:.0f} EUR = ${start_usd:.2f} (USER ORDER {nb:%Y-%m-%d %H:%M}); previous epochs in 'epochs', archived books in archive/"})
        tmp = f"{DESK}/bank.json.tmp"; json.dump(bank, open(tmp, "w"), indent=1); os.replace(tmp, f"{DESK}/bank.json")
        h = f"{DESK}/history.csv"
        if os.path.exists(h): shutil.move(h, f"{DESK}/{prev['history']}")
        with open(h, "w") as f:
            f.write("timestamp_berlin,desk_equity,desk_cash,realized,unrealized\n")
            f.write(f"{nb.isoformat(timespec='seconds')},{start_usd:.4f},{start_usd:.4f},0.0000,0.0000\n")
    with meme.poslock(path=f"{DESK}/.riskstate.lock"):
        rs = {"date": nb.date().isoformat(), "day_open_equity": start_usd, "halted": False, "epoch_reset": nb.isoformat(timespec="seconds")}
        with open(meme.RISK_JOURNAL, "a") as f: f.write(json.dumps(rs) + "\n")
        tmp = meme.RISKST + ".tmp"; json.dump(rs, open(tmp, "w"), indent=1); os.replace(tmp, meme.RISKST)
    meme.log(f"[BANK] new epoch {prev['epoch'] + 1}: meme bank reset to {start_eur:.0f} EUR = ${start_usd:.2f} (USER ORDER); epoch {prev['epoch']} ended at "
             f"${prev['end_equity_usd']:.2f} (realized {prev['realized_usd']:+.2f}, {prev['closed_trades']} closes, {prev['wins']}W/{prev['losses']}L), archived {prev['archive']}")
    print(json.dumps(prev, indent=1)); print("new start", start_usd)

if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
