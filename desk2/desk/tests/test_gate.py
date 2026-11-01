"""STEP 13: gate rejects alive 0.69 / organic 0.64 / chase 0.31 / score 69; all-at-threshold passes; rules label."""
from desk import config
from desk.agents import analyst
from .conftest import arun

def S(tdb): return config.all_settings()
BASE = {"alive_6h": 0.70, "organic": 0.65, "flush": 0.75, "chase": 0.30}

def test_threshold_pass(tdb):
    sc, ok, f = analyst.gate(dict(BASE), S(tdb)); assert ok and sc == 70, (sc, f)

def test_each_reject(tdb):
    s = S(tdb)
    for k, v, want in (("alive_6h", 0.69, "alive_6h"), ("organic", 0.64, "organic"), ("chase", 0.31, "chase"), ("flush", 0.71, "score 69")):
        a = dict(BASE); a[k] = v
        sc, ok, f = analyst.gate(a, s)
        assert not ok and any(x.startswith(want) for x in f), (k, sc, f)

def test_rules_label(tdb):
    from desk import db
    config.set("analyst.mode", "rules", "test")
    analyst._record("M1", "X", {"answers": {"alive_6h": .1, "organic": .1, "flush": 0, "chase": .9}, "score": 8, "passed": False,
                                "failed": ["alive_6h 0.10"], "model": "rules", "inputTokens": 0}, None)
    assert db.one("SELECT subtitle FROM activity")["subtitle"].startswith("Analyst (rules) · ")
