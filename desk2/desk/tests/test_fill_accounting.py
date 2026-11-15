"""How a -6% stop becomes a worse booked loss. Current PAPER behavior, measured on fixtures.

The stop and the trail compare the DexScreener spot. The exit is that same spot, even when it has
gapped through the line. Round-trip costs (pump fee + price impact + the 0.5% extra slippage +
0.0005 SOL gas, each side) are subtracted afterwards and are not part of the -6% line.
Entry is the signal spot; slippage is booked in fees_usd, once per side, not applied to the fill.
"""
import inspect
import pytest
from desk import config, db, fees, util
from desk.agents import executor, risk
from .conftest import arun

# $7.48 is 8% of a $93.50 stack. Pool $100k, mcap $50k, SOL $200 -> pump fee tier 1.25%.
SIZE, LIQ, MCAP, SOL = 7.48, 100_000, 50_000, 200
MINT = "AcctMint111111111111111111111111111pump"


def _view(price, liq=LIQ, mcap=MCAP, sol=SOL):
    return {"liquidity": liq, "price": price, "mcap": mcap, "sol_usd": sol, "vol_m5": 1,
            "name": "BIG", "symbol": "BIG", "pool": "POOL"}


def _arm(monkeypatch, price, liq=LIQ, mcap=MCAP, sol=SOL):
    async def pairs(_pools):
        return {"POOL": {"pair": "POOL"}}

    monkeypatch.setattr(executor.S, "dex_pairs", pairs)
    monkeypatch.setattr(executor.chain, "pair_view", lambda _p: _view(price, liq, mcap, sol))
    monkeypatch.setattr(executor.account, "equity", lambda: SIZE / 0.08)
    monkeypatch.setattr(executor.account, "free", lambda: SIZE / 0.08)


def _open(monkeypatch, price=1.0, **kw):
    _arm(monkeypatch, price, **kw)
    db.upsert_coin(MINT, pool="POOL", symbol="BIG")
    out = arun(executor.execute({"mint": MINT, "tags": [], "analyst": {"score": 90, "price": price}}))
    assert out["status"] == "bought" and out["sizeUsd"] == SIZE
    return db.one("SELECT * FROM positions WHERE mint=? AND closed_at IS NULL", (MINT,))


def test_open_fee_is_one_side_on_the_signal_price(tdb, monkeypatch):
    s = config.all_settings()
    one = fees.side_cost(SIZE, LIQ, MCAP, SOL, s["fees.gas_sol_per_side"], s["fees.extra_slippage_pct"])
    p = _open(monkeypatch)
    assert p["entry_price"] == 1.0                          # signal spot, not a slipped fill
    assert p["stop_price"] == pytest.approx(0.94)          # -6% of that spot
    assert p["fees_usd"] == pytest.approx(round(one["total_usd"], 4))
    assert one["fee_pct"] == 1.25
    assert one["slippage_pct"] == pytest.approx(0.515, abs=0.001)   # 0.5% extra + ~0.015% impact
    assert one["gas_usd"] == pytest.approx(0.10)           # 0.0005 SOL * $200
    assert p["fees_usd"] / SIZE * 100 == pytest.approx(3.10, abs=0.02)
    # the reported open on BIG, fees_usd 0.2331, sits next to this. A $40k pool is 0.2337.
    thin = fees.side_cost(SIZE, 40_000, MCAP, SOL, s["fees.gas_sol_per_side"], s["fees.extra_slippage_pct"])
    assert thin["total_usd"] == pytest.approx(0.2337, abs=0.0002)
    assert one["total_usd"] < 0.2331 < thin["total_usd"]
    assert p["fees_usd"] < one["total_usd"] * 1.01          # stored once, not twice


def test_stop_books_the_polled_price_plus_both_sides(tdb, monkeypatch):
    s = config.all_settings()
    assert s["risk.stop_pct"] == 6 and s["risk.poll_s"] == 15
    assert "confirm_window" not in inspect.getsource(risk)
    p = _open(monkeypatch)
    held, reason = risk.decide(p, 0.95, util.now(), s)
    assert reason is None and "stop_price" not in held     # -5% does not stop
    hit, reason = risk.decide(p, 0.94, util.now(), s)
    assert reason == "stop"
    arun(risk.close(p, 0.94, reason, _view(0.94), s))
    row = db.one("SELECT * FROM positions WHERE id=?", (p["id"],))
    assert row["exit_price"] == 0.94 and row["exit_reason"] == "stop"
    assert row["pnl_usd"] / SIZE * 100 == pytest.approx(-12.10, abs=0.05)
    # a print that has already gapped through is the fill. It is not pulled back to the -6% line.
    db.x("UPDATE positions SET closed_at=NULL, exit_price=NULL, exit_reason=NULL, pnl_usd=NULL, fees_usd=? WHERE id=?",
         (p["fees_usd"], p["id"]))
    p2 = db.one("SELECT * FROM positions WHERE id=?", (p["id"],))
    gap, reason = risk.decide(p2, 0.88, util.now(), s)
    assert reason == "stop"
    arun(risk.close(p2, 0.88, reason, _view(0.88), s))
    row = db.one("SELECT * FROM positions WHERE id=?", (p["id"],))
    assert row["exit_price"] == 0.88
    assert row["pnl_usd"] / SIZE * 100 == pytest.approx(-17.99, abs=0.05)
    assert row["fees_usd"] == pytest.approx(0.4481, abs=0.0002)   # entry side + exit side, once
    title = db.one("SELECT title FROM pushes ORDER BY id DESC LIMIT 1")["title"]
    assert "-6%" in title and row["pnl_usd"] < -1.3       # the push still says the -6% stop


def test_poll_fills_the_stop_at_the_price_it_just_saw(tdb, monkeypatch):
    p = _open(monkeypatch)
    seen = _view(0.88)

    async def pairs(_pools):
        return {"POOL": seen}

    monkeypatch.setattr(risk.S, "dex_pairs", pairs)
    monkeypatch.setattr(risk.chain, "pair_view", lambda raw: raw)
    arun(risk.poll_once())
    row = db.one("SELECT * FROM positions WHERE id=?", (p["id"],))
    assert row["exit_reason"] == "stop" and row["exit_price"] == 0.88
    assert row["pnl_usd"] / p["size_usd"] * 100 == pytest.approx(-17.99, abs=0.05)


def test_trail_after_plus_20_can_book_plus_1_or_a_loss(tdb, monkeypatch):
    s = config.all_settings()
    assert s["risk.trail_start_pct"] == 20 and s["risk.trail_pct"] == 12
    p = _open(monkeypatch, liq=100_000, mcap=30_000_000, sol=180)
    arm, reason = risk.decide(p, 1.20, util.now(), s)
    assert reason is None and arm["trail_active"] == 1     # the arming print does not sell
    p.update(arm)
    line = 1.20 * (1 - 12 / 100)
    assert line == pytest.approx(1.056)
    # just through the trail line: +5.3% in price, about +1.2% booked (HODL)
    u, reason = risk.decide(p, 1.053, util.now(), s)
    assert reason == "trail"
    arun(risk.close(p, 1.053, reason, _view(1.053, mcap=30_000_000, sol=180), s))
    hodl = db.one("SELECT * FROM positions WHERE id=?", (p["id"],))
    assert hodl["pnl_usd"] / SIZE * 100 == pytest.approx(1.22, abs=0.05)
    # a later print near flat is still a trail (price is above the -6% stop) and books about -6.4% (GLITCH)
    db.x("DELETE FROM positions")
    db.x("DELETE FROM signals WHERE mint=?", (MINT,))
    p = _open(monkeypatch)
    arm, reason = risk.decide(p, 1.20, util.now(), s)
    p.update(arm)
    u, reason = risk.decide(p, 0.998, util.now(), s)
    assert reason == "trail" and 0.998 > p["stop_price"]
    arun(risk.close(p, 0.998, reason, _view(0.998), s))
    glitch = db.one("SELECT * FROM positions WHERE id=?", (p["id"],))
    assert glitch["pnl_usd"] / SIZE * 100 == pytest.approx(-6.40, abs=0.05)
