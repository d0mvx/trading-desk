from desk import db, health

def _ev(kind, n):
    for _ in range(n): db.event(kind, "t")

def test_planned_reconnects_do_not_count(tdb):
    _ev("start", 5); _ev("ws_connect", 14); _ev("ws_silent", 9)
    assert not any("ws reconnects" in b for b in health.check())

def test_unexpected_reconnects_count(tdb):
    _ev("start", 1); _ev("ws_connect", 13)
    assert any("ws reconnects 12/h" in b for b in health.check())
