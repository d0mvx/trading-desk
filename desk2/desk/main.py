"""One asyncio process: 5 agents + FastAPI/uvicorn API + SSE (STEP 3). PAPER only."""
from __future__ import annotations
import asyncio, os, signal
import uvicorn
from . import db, util, config, account, log, bus, shadow
from .agents import scanner, auditor, analyst, executor, risk
from .api import app

L = log.get("main")
PORT = int(os.environ.get("DESK_PORT", "8787"))

_night = None

async def night_check():
    """at the start of every night: ticket check (STEP 9/PART 5); push the warning if any."""
    global _night
    key = util.iso(util.night_start(config.get("desk.report_time")))
    if key != _night:
        _night = key
        w = config.ticket_check()
        if w:
            from . import webpush
            await webpush.push("Ticket check", w, None, "warn")
            db.event("ticket_warning", w)

async def balance_loop():
    while True:
        try:
            await night_check()
            db.insert("balance", ts=util.iso(), value=round(account.equity(), 4))
            bus.emit("balance", {"balance": round(account.equity(), 2), "ts": util.iso()})
            db.heartbeat("main")
        except Exception as e:
            L.exception("balance: %s", e)
        await asyncio.sleep(60)

async def guarded(name, coro_fn):
    while True:
        try:
            await coro_fn()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            L.exception("%s crashed: %s; restarting in 5s", name, e)
            db.event("agent_crash", f"{name}: {e}"[:200])
            await asyncio.sleep(5)

async def main():
    db.conn()
    if config.get("desk.mode") != "PAPER":
        config.set("desk.mode", "PAPER", "main")   # LIVE locked
    L.info("desk starting PAPER on 127.0.0.1:%d", PORT)
    db.event("start", "PAPER")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False, proxy_headers=True))
    await asyncio.gather(server.serve(), balance_loop(), guarded("scanner", scanner.run), guarded("auditor", auditor.run),
                         guarded("auditor_beat", auditor.beat), guarded("analyst", analyst.run),
                         guarded("executor", executor.run), guarded("risk", risk.run), guarded("shadow", shadow.loop), _beats())

async def _beats():
    while True:
        for a in ("analyst", "executor"):
            db.heartbeat(a)
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
