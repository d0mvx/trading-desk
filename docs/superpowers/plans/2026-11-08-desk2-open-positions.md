# desk2 open PAPER trades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show open PAPER trades on the existing Home screen with fee-aware unrealized PnL, a real price time, and honest empty and stale states.

**Architecture:** `GET /api/state` adds display fields on the open-position list it already returns. `app.js` renders that list under the balance and reuses the current 30s poll plus the balance SSE event. Cached snapshots keep the timestamp of the last real HTTP 200.

**Tech Stack:** FastAPI, pytest, the existing vanilla `app.js`. No new package.

## Global Constraints

- PAPER display only. LIVE stays locked. No order path.
- Do not change scanner, Jev, risk decisions, experiments, tags, settings, fees, or executor sizing.
- Do not change `account.equity`, `account.unrealized`, or `account.free`.
- Missing last price, zero entry, or null size: `unrealized_usd` and `unrealized_pct` are JSON `null`. Never a fabricated 0.
- Fee-aware mark, rounded to 4 decimals, matching `positions.pnl_usd` storage: `round(size_usd * (last / entry_price - 1) - (fees_usd or 0), 4)`.
- Percent is that rounded USD divided by `size_usd` times 100, rounded to 4 decimals. UI labels it Unrealisiert. Do not display open-row `pnl_usd`.
- `last_at` is `prices.ts` of the latest non-null price. Do not write `S.lastOk` when serving `CACHE`.
- `.github/workflows/desk.yml` untouched. No `state` or `state-desk2` access. No force-push.
- No new JS test dependency. Browser check uses a disposable local DB only.

---

### Task 1: State payload

**Files:**
- Create: `desk2/desk/tests/test_state_positions.py`
- Modify: `desk2/desk/api.py` (`state()` positions list)

**Interfaces:**
- Consumes: `account.open_positions()`, `links.coin_url`, `risk.stop_pct_of`, `risk.exit_line`, `db` prices.
- Produces: each `positions[]` object includes `name`, `link`, `last`, `last_at`, `unrealized_usd`, `unrealized_pct`, `stop_pct`, `exit_line`, plus the original row. Ordered by `id`.

- [ ] **Step 1: Write the failing test**

```python
"""Open PAPER rows on GET /api/state. Display fields only; equity math stays put."""
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
```

Mints must match `links.coin_url` base58 length. Use the two mints already in `test_risk.py` plus further 32–44 character base58 strings that pass `links._B58`. If a chosen mint fails `coin_url`, replace it before trusting the link assertion.

- [ ] **Step 2: Run the test and watch it fail**

Run from `desk2/`: `.venv/bin/python -m pytest -q desk/tests/test_state_positions.py`

Expected: failures on missing `unrealized_usd` / `last_at` / `exit_line`, or a null last where the old code used `account.last_price` only. An empty list already passes `test_empty_state_is_a_real_empty_list`. That one test may pass before the change. The fee, missing-price, zero-entry, trail, and filter tests must fail.

- [ ] **Step 3: Implement `position_view` and use it in `state()`**

Add next to the other helpers in `desk2/desk/api.py`:

```python
def position_view(p: dict, settings: dict) -> dict:
    """Display fields for one open row. Does not use the entry-price fallback equity uses."""
    row = db.one(
        "SELECT price, ts FROM prices WHERE mint=? AND price IS NOT NULL ORDER BY ts DESC LIMIT 1",
        (p["mint"],),
    )
    last = row["price"] if row else None
    last_at = row["ts"] if row else None
    entry, size = p.get("entry_price"), p.get("size_usd")
    usd = pct = None
    if last is not None and entry not in (None, 0) and size is not None:
        usd = round(size * (last / entry - 1) - (p.get("fees_usd") or 0), 4)
        pct = round(usd / size * 100, 4) if size else None
    stop_pct = None
    if entry not in (None, 0) and p.get("stop_price") is not None:
        stop_pct = risk_agent.stop_pct_of(p)
    exit_line = None
    if p.get("trail_active") and p.get("peak_price") is not None and p.get("stop_price") is not None:
        exit_line = risk_agent.exit_line(p, settings)
    return {**p, "name": name_of(p["mint"]), "link": links.coin_url(p["mint"]),
            "last": last, "last_at": last_at, "unrealized_usd": usd, "unrealized_pct": pct,
            "stop_pct": stop_pct, "exit_line": exit_line}
```

In `state()`, build the list once:

```python
settings = config.all_settings()
positions = [position_view(p, settings) for p in sorted(account.open_positions(), key=lambda p: p["id"])]
```

Pass `positions` in the response. Do not change the equity line.

- [ ] **Step 4: Re-run the new file and `test_links.py` `test_risk.py`**

Expected: new file passes. Existing state consumers still pass.

- [ ] **Step 5: Commit** the test and `api.py` together once green.

### Task 2: Home section and honest snapshot time

**Files:**
- Modify: `desk2/desk/web/index.html` (script src)
- Modify: `desk2/desk/web/app.js` (`api`, `setOffline`, `loadState`, `onEvent` balance, `Home`, `paintHome`)
- Modify: `desk2/desk/web/app.css` (stack `#trades .pos` only)
- Test: extend `desk2/desk/tests/test_state_positions.py` with a source assertion that `S.lastOk =` appears once

**Interfaces:**
- Consumes: `state.positions[]` fields from Task 1, `state.mode`, `state.server_time`, existing `money`, `pct`, `price`, `hm`, `esc`.
- Produces: `#trades` HTML. `S.lastOk` updates only on a successful `api("state")`.

- [ ] **Step 1: Add the source regression to the pytest file and run it**

```python
def test_client_stamps_last_ok_only_on_success():
    root = os.path.join(os.path.dirname(__file__), "..", "web")
    js = open(os.path.join(root, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(root, "index.html"), encoding="utf-8").read()
    assert js.count("S.lastOk =") == 1
    assert "Offene PAPER-Trades" in js and "Keine offenen PAPER-Trades" in js
    assert "Verbindung weg" in js and "unrealized_usd" in js and "kein Kurs" in js
    assert "Auf pump.fun" in js
    assert 'src="/app.js?v=20261108-open-trades"' in html
```

Expected FAIL until the client contains those strings and a single assignment.

- [ ] **Step 2: Client behavior**

`api()` network failure with a cached GET throws `Error("Desk offline")` with `stale` and `body` set. It does not return the cache as success and it does not call `setOnline`.

`setOffline` sets `S.snapshotStale = true`, repaints Home when a state exists, and schedules one `loadState` retry. `setOnline` does not clear `snapshotStale` and does not write `lastOk`.

`loadState` on success: assign state, then `S.lastOk = new Date().toISOString()`, then `S.snapshotStale = false`, then `setOnline()`, then `paintHome()`. On `e.stale`: if `S.state` is null, adopt `e.body`, then `paintHome()` without touching `lastOk`.

Balance handler keeps `paintBalance` when the snapshot is fresh, and always calls `refreshSoon()` so open rows move with the equity tick.

`Home` inserts, after `#warn` and before the chart:

```html
<div class="sect"><h2>Offene PAPER-Trades <span id="openN"></span></h2></div>
<div id="trades"></div>
```

`paintHome` fills `#openN` and `#trades`. Renderer rules:

- mode other than PAPER: error text `Desk ist nicht im PAPER-Modus`, no cards
- stand line: `Stand ${hm(S.lastOk)}` after a 200; append ` · Verbindung weg` when `S.snapshotStale || S.offline`. If `lastOk` is null, the stand time is an em dash, not `new Date()`
- zero positions: `Keine offenen PAPER-Trades`
- else one `.pos` per row: `esc(name)`, Einsatz `money(size_usd)`, Unrealisiert from `unrealized_usd` / `unrealized_pct` or an em dash, Einstieg, Kurs or `kein Kurs`, Kurs time from `last_at`, orange when `server_time - last_at > 90000`, Stop from `stop_price` and `stop_pct`, Trail `price(exit_line)` only if `trail_active` and `exit_line != null`, else `Trail noch nicht aktiv`, anchor `esc(link)` with `target="_blank"` and `rel="noopener"`

Do not read `pnl_usd` in this renderer.

CSS:

```css
#trades .pos + .pos { margin-top: 10px; }
```

- [ ] **Step 3: `node --check desk/web/app.js` and pytest the new file**

- [ ] **Step 4: Commit** the web files and the source assertion.

### Task 3: Verify

- [ ] From `desk2/`: `.venv/bin/python -m pytest -q -p no:cacheprovider desk/tests`
- [ ] `node --check desk/web/app.js` and `.venv/bin/python -m py_compile desk/api.py`
- [ ] Disposable DB on `127.0.0.1` only, port other than 8787. Seed example symbols that start with `EXAMPLE`. Screenshot mobile Home for a filled book (fee-aware loss, missing price, old price) and for a genuine empty 200. Label the shots as example data. Do not point the fixture at ngrok, `desk.db` in the repo, or the state branches.
- [ ] Diff review against this plan before the PR. Do not merge or dispatch.

## Self-review

Spec coverage: inline Home section, fields, formula, null price, zero entry, negative price, trail line, PAPER filter, closed filter, empty versus stale, single `lastOk` write, cache-bust, no equity change, no workflow change. Each has a task above.

Placeholder scan: none.

Type consistency: `position_view` fields match the client keys `unrealized_usd`, `unrealized_pct`, `last_at`, `exit_line`, `stop_pct`, `link`.
