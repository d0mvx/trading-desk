"""Open PAPER rows on GET /api/state. Display fields only; equity math stays put."""
import os
from fastapi.testclient import TestClient
from desk import account, config, db, links, util
from desk.agents import risk

M_FEE = "6m7frLtvpHUNRfBHQHjtZZs812kVwKsY16gxPj6vpump"
M_MISS = "8gZMwbqtKyhbfZg8yYVGBbD43RjwH7HXXCVPBZDwpump"
M_ZERO = "9zZMwbqtKyhbfZg8yYVGBbD43RjwH7HXXCVPBZDwpump"
M_NEG = "7zZMwbqtKyhbfZg8yYVGBbD43RjwH7HXXCVPBZDwpump"
M_OLD = "5zZMwbqtKyhbfZg8yYVGBbD43RjwH7HXXCVPBZDwpump"
M_LIVE = "4zZMwbqtKyhbfZg8yYVGBbD43RjwH7HXXCVPBZDwpump"
M_CLOSED = "3zZMwbqtKyhbfZg8yYVGBbD43RjwH7HXXCVPBZDwpump"
TOK = "pytest-desk2-open-positions"


def _auth(monkeypatch):
    monkeypatch.setattr("desk.api._token", lambda: TOK)
    return {"Authorization": f"Bearer {TOK}"}


def _pos(mint, entry, size, stop, fees, mode="PAPER", trail=0, peak=None, closed=None, pnl=None):
    db.x(
        "INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode,closed_at,exit_price,exit_reason,pnl_usd) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mint, util.iso(), entry, size, peak if peak is not None else entry, stop, trail, fees, mode,
         closed, None, "stop" if closed else None, pnl),
    )


def _client():
    from desk.api import app
    return TestClient(app)


def test_empty_state_is_a_real_empty_list(tdb, monkeypatch):
    h = _auth(monkeypatch)
    body = _client().get("/api/state", headers=h).json()
    assert body["mode"] == "PAPER"
    assert body["positions"] == []
    assert next(a["guarding"] for a in body["agents"] if a["name"] == "risk") == 0


def test_fee_aware_unrealized_matches_equity_term_not_coin_gross(tdb, monkeypatch):
    h = _auth(monkeypatch)
    db.upsert_coin(M_FEE, symbol="EX<A>&", name="Example")
    _pos(M_FEE, entry=1.0, size=16, stop=0.94, fees=0.2)
    db.price(M_FEE, 1.01, 10)
    body = _client().get("/api/state", headers=h).json()
    p = body["positions"][0]
    assert p["name"] == "EX<A>&"
    assert p["link"] == links.coin_url(M_FEE)
    assert p["size_usd"] == 16
    assert p["entry_price"] == 1.0
    assert p["last"] == 1.01
    assert p["last_at"]
    assert p["pnl_usd"] is None
    assert p["unrealized_usd"] == -0.04
    assert p["unrealized_pct"] == -0.25
    assert p["stop_pct"] == risk.stop_pct_of(db.one("SELECT * FROM positions WHERE mint=?", (M_FEE,)))
    assert p["trail_active"] == 0
    assert p["exit_line"] is None
    raw = 16 * (1.01 / 1.0 - 1) - 0.2
    assert p["unrealized_usd"] == round(raw, 4)
    coin = _client().get(f"/api/coin/{M_FEE}", headers=h).json()["position"]
    assert coin["unrealized"] == 16 * (1.01 / 1.0 - 1)
    assert abs(account.unrealized() - raw) < 1e-9


def test_missing_price_is_null_not_zero_or_entry_fallback(tdb, monkeypatch):
    h = _auth(monkeypatch)
    db.upsert_coin(M_MISS, symbol="EXAMPLE")
    _pos(M_MISS, entry=2.0, size=10, stop=1.88, fees=0.5)
    body = _client().get("/api/state", headers=h).json()
    p = body["positions"][0]
    assert p["last"] is None and p["last_at"] is None
    assert p["unrealized_usd"] is None and p["unrealized_pct"] is None
    assert account.unrealized() == -0.5


def test_zero_entry_does_not_divide(tdb, monkeypatch):
    h = _auth(monkeypatch)
    db.upsert_coin(M_ZERO, symbol="ZERO")
    _pos(M_ZERO, entry=0.0, size=16, stop=0.0, fees=0.2)
    db.price(M_ZERO, 1.0, 1)
    p = _client().get("/api/state", headers=h).json()["positions"][0]
    assert p["last"] == 1.0
    assert p["unrealized_usd"] is None and p["unrealized_pct"] is None
    assert p["stop_pct"] is None
    assert account.unrealized() == 0


def test_negative_last_price_is_marked_not_clamped(tdb, monkeypatch):
    h = _auth(monkeypatch)
    db.upsert_coin(M_NEG, symbol="NEG")
    _pos(M_NEG, entry=1.0, size=16, stop=0.94, fees=0.0)
    db.price(M_NEG, -0.5, 1)
    p = _client().get("/api/state", headers=h).json()["positions"][0]
    assert p["last"] == -0.5
    assert p["unrealized_usd"] == round(16 * (-0.5 / 1.0 - 1), 4)
    assert p["unrealized_usd"] != 0


def test_last_at_is_the_price_row_not_server_time(tdb, monkeypatch):
    h = _auth(monkeypatch)
    db.upsert_coin(M_OLD, symbol="OLD")
    _pos(M_OLD, entry=1.0, size=10, stop=0.94, fees=0.0, trail=1, peak=1.5)
    db.insert("prices", mint=M_OLD, ts="2020-01-01T00:00:00Z", price=1.2, volume_m5=1)
    body = _client().get("/api/state", headers=h).json()
    p = body["positions"][0]
    assert p["last"] == 1.2 and p["last_at"] == "2020-01-01T00:00:00Z"
    assert p["last_at"] != body["server_time"]
    s = config.all_settings()
    row = db.one("SELECT * FROM positions WHERE mint=?", (M_OLD,))
    assert p["exit_line"] == risk.exit_line(row, s)
    assert p["exit_line"] == max(0.94, 1.5 * (1 - s["risk.trail_pct"] / 100))


def test_closed_and_non_paper_rows_stay_out(tdb, monkeypatch):
    h = _auth(monkeypatch)
    db.upsert_coin(M_FEE, symbol="OPEN")
    db.upsert_coin(M_LIVE, symbol="LIVE")
    db.upsert_coin(M_CLOSED, symbol="CLOSED")
    _pos(M_FEE, entry=1, size=16, stop=0.94, fees=0)
    _pos(M_LIVE, entry=1, size=99, stop=0.94, fees=0, mode="LIVE")
    _pos(M_CLOSED, entry=1, size=8, stop=0.94, fees=0, closed=util.iso(), pnl=5)
    db.price(M_FEE, 1.1, 1)
    body = _client().get("/api/state", headers=h).json()
    mints = [p["mint"] for p in body["positions"]]
    assert mints == [M_FEE]
    assert all(p["mode"] == "PAPER" for p in body["positions"])
    assert next(a["guarding"] for a in body["agents"] if a["name"] == "risk") == 1
    for path in ("/api/account", "/api/chart?range=1D", "/api/activity", "/api/settings"):
        assert _client().get(path, headers=h).status_code == 200


def test_client_stamps_last_ok_only_on_success():
    root = os.path.join(os.path.dirname(__file__), "..", "web")
    js = open(os.path.join(root, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(root, "index.html"), encoding="utf-8").read()
    assert js.count("S.lastOk =") == 1
    assert "Offene PAPER-Trades" in js and "Keine offenen PAPER-Trades" in js
    assert "Verbindung weg" in js and "unrealized_usd" in js and "kein Kurs" in js
    assert "Auf pump.fun" in js
    assert 'src="/app.js?v=20261108-open-trades"' in html
