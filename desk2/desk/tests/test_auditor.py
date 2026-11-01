"""STEP 13: a mint with freeze authority set -> layer 2 red, layers 3-8 'not checked'."""
from desk import db, util
from desk.agents import auditor
from desk import chain
from .conftest import arun
M = "6m7frLtvpHUNRfBHQHjtZZs812kVwKsY16gxPj6vpump"

def test_freeze_red(tdb, monkeypatch, sent):
    async def mi(m): return {"mint_authority": None, "freeze_authority": "FrZ1111111111111111111111111111111111111111", "supply": 1e9, "decimals": 6}
    monkeypatch.setattr(chain, "mint_info", mi)
    db.upsert_coin(M, symbol="FRZ", pool="p")
    ok = arun(auditor.audit({"mint": M, "pool": "p"}))
    assert ok is False
    rows = {r["layer"]: r for r in db.q("SELECT * FROM audits WHERE mint=?", (M,))}
    assert rows[1]["pass"] == 1 and rows[2]["pass"] == 0 and "freeze authority live" in rows[2]["value_text"]
    assert all(rows[n]["value_text"] == "not checked" for n in range(3, 9))
