"""STEP 13 (limited): replay logged migrations (logs/migrations.jsonl + the STEP 2 capture) through the Scanner into a temp DB,
one live DexScreener poll, PAPER. Real 2h-live evidence comes from the always-on desk's own DB."""
import json, os, asyncio
from desk import db
from desk.agents import scanner

def _mints():
    out = []
    fx = os.path.join(os.path.dirname(__file__), "fixtures")
    for f in (os.path.join(fx, "migrations.jsonl"), os.path.join(fx, "pumpportal_migration.jsonl")):
        if not os.path.exists(f): continue
        for l in open(f):
            j = json.loads(l); j = json.loads(j["raw"]) if "raw" in j else j
            if j.get("txType") == "migrate" and j.get("mint"): out.append(j["mint"])
    return list(dict.fromkeys(out))[:20]

def test_replay(tdb):
    ms = _mints(); assert ms
    async def go():
        scanner.room.clear()
        for m in ms: await scanner.on_migration(m)
        await asyncio.sleep(20)              # let _resolve fetch RugCheck pools
        for m in list(scanner.room): scanner.room[m]["t0"] -= 60 * 60   # pretend waited 60 min -> resolve or drop
        await scanner.poll_once()
    asyncio.run(go())
    rows = db.q("SELECT mint, verdict, reason FROM scans")
    print("\nREPLAY", len(ms), "mints:", [(r["mint"][:6], r["verdict"], r["reason"]) for r in rows])
    assert rows and all(r["verdict"] in ("kill", "pass", "drop", "wait") for r in rows)
