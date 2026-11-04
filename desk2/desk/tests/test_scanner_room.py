"""Thin pools stay in the waiting room until max_wait instead of dying on the first look."""
import asyncio, time
import pytest
from desk.agents import scanner

def _pair(liq):
    return {"liquidity": liq, "price": 0.001, "vol_m5": 1, "ch_h24": 0, "ch_h1": 5, "created_ms": time.time()*1000 - 60_000,
            "name": "T", "symbol": "T", "pool": "POOL1"}

@pytest.mark.parametrize("waited,expect_in_room", [(1, True), (61, False)])
def test_thin_pool_waits(tdb, monkeypatch, waited, expect_in_room):
    mint = "MINTxpump"
    scanner.room.clear()
    scanner.room[mint] = {"t0": time.time() - waited*60, "report": None, "scan_liq": None}
    logged = []
    monkeypatch.setattr(scanner.db, "coin", lambda m: {"pool": "POOL1"})
    monkeypatch.setattr(scanner.db, "paused", lambda n: False)
    monkeypatch.setattr(scanner.db, "price", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_scan", lambda m, v, t, a, verdict, reason: logged.append(verdict))
    async def pairs(_): return {"POOL1": {}}
    monkeypatch.setattr(scanner.S, "dex_pairs", pairs)
    monkeypatch.setattr(scanner.chain, "pair_view", lambda p: _pair(15000))
    asyncio.run(scanner.poll_once())
    assert (mint in scanner.room) == expect_in_room
    assert logged == (["wait"] if expect_in_room else ["kill"])
