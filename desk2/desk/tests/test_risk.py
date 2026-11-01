"""STEP 13: trail, stop -6.1%, timeout, loosening never moves an open stop, and the 'set stop to -8%' scenario."""
import datetime as dt
from desk import config, db, util, commands, account
from desk.agents import risk
from .conftest import arun
M1, M2 = "6m7frLtvpHUNRfBHQHjtZZs812kVwKsY16gxPj6vpump", "8gZMwbqtKyhbfZg8yYVGBbD43RjwH7HXXCVPBZDwpump"

def P(entry=1.0, stop_pct=6, opened=None, trail=0, peak=None):
    return {"id": 1, "mint": M1, "entry_price": entry, "stop_price": entry * (1 - stop_pct / 100), "trail_active": trail,
            "peak_price": peak or entry, "opened_at": util.iso(opened or util.now()), "size_usd": 16, "fees_usd": 0.2, "mode": "PAPER"}

def test_trail(tdb):
    s = config.all_settings(); p = P(); n = util.now()
    u, r = risk.decide(p, 1.25, n, s); assert r is None and u["trail_active"] == 1
    p.update(u); u, r = risk.decide(p, 1.25 * 0.87, n, s); assert r == "trail"

def test_stop_61(tdb):
    u, r = risk.decide(P(), 0.939, util.now(), config.all_settings()); assert r == "stop"

def test_timeout(tdb):
    u, r = risk.decide(P(opened=util.now() - dt.timedelta(hours=3, minutes=1)), 1.04, util.now(), config.all_settings()); assert r == "timeout"

def test_loosen_never_moves_open_stop(tdb):
    config.set("risk.stop_pct", 8, "t"); p = P()
    u, r = risk.decide(p, 0.95, util.now(), config.all_settings())
    assert "stop_price" not in u and risk.stop_pct_of(p) == 6

def test_set_stop_8_scenario(tdb, sent):
    db.upsert_coin(M1, symbol="OLD", pool="p1"); db.upsert_coin(M2, symbol="NEW", pool="p2")
    old = P(); db.x("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode) VALUES(?,?,?,?,?,?,?,?,?)",
                    (M1, old["opened_at"], 1.0, 16, 1.0, 0.94, 0, 0.2, "PAPER"))
    rep = commands.run("set stop to -8%"); assert "-6% -> -8%" in rep["text"], rep
    s = config.all_settings()
    db.x("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode) VALUES(?,?,?,?,?,?,?,?,?)",
         (M2, util.iso(), 1.0, 16, 1.0, 1.0 * (1 - s["risk.stop_pct"] / 100), 0, 0.2, "PAPER"))
    new = db.one("SELECT * FROM positions WHERE mint=?", (M2,))
    u, r = risk.decide(new, 0.919, util.now(), s); assert r == "stop"
    arun(risk.close(new, 0.919, r, None, s))
    assert "-8% stop" in sent[-1]["title"]
    assert db.one("SELECT subtitle FROM activity WHERE mint=?", (M2,))["subtitle"] == "Risk · -8% stop"
    from fastapi.testclient import TestClient
    from desk.api import app
    h = {"Authorization": f"Bearer {util.secret('app_token')}"}
    marks = TestClient(app).get("/api/chart?range=1D", headers=h).json()["marks"]
    assert any(m["kind"] == "stop" and m["label"].startswith("-8%") for m in marks), marks
    st = TestClient(app).get("/api/state", headers=h).json()
    o = db.one("SELECT * FROM positions WHERE mint=?", (M1,)); assert risk.stop_pct_of(o) == 6
    rk = next(a for a in st["agents"] if a.get("name") == "risk" or a.get("agent") == "risk")
    assert rk["stop_pct"] == 8, rk
