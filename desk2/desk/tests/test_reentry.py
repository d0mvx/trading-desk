"""A mint with a closed PAPER trade whose realized PnL is negative (net of fees) is not opened again.

The block is the positions table, so a new process sees it. A winner, a flat close, and any other mint
still follow the existing rules, including one signal per night. executor.block_after_loss defaults on.
"""
import asyncio
import datetime as dt
import sqlite3
from desk import config, db, util
from desk.agents import executor

LOSER = "LoseMint111111111111111111111111111pump"
WINNER = "WinMint1111111111111111111111111111pump"
OTHER = "OthrMint111111111111111111111111111pump"
LOSS = "lost on this mint before"


def _arm(monkeypatch, price=1.0, liq=100_000):
    async def pairs(_pools):
        return {"POOL": {"pair": "POOL"}}

    async def push(*_a, **_k):
        return "ok"

    monkeypatch.setattr(executor.S, "dex_pairs", pairs)
    monkeypatch.setattr(executor.chain, "pair_view", lambda _p: {
        "liquidity": liq, "price": price, "mcap": 1_000_000, "sol_usd": 180, "vol_m5": 1})
    monkeypatch.setattr(executor.webpush, "push", push)


def _closed(mint, pnl, mode="PAPER", symbol="T"):
    db.upsert_coin(mint, pool="POOL", symbol=symbol)
    db.x(
        "INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode,"
        "closed_at,exit_price,exit_reason,pnl_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mint, util.iso(util.now() - dt.timedelta(days=2)), 1.0, 16, 1.0, 0.94, 0, 0.4, mode,
         util.iso(util.now() - dt.timedelta(days=1)), 0.9, "stop", pnl))


def _buy(mint):
    return asyncio.run(executor.execute({"mint": mint, "tags": [], "analyst": {"score": 80, "price": 1.0}, "audit": "8/8"}))


def test_default_blocks_reentry_after_a_loss(tdb):
    assert config.all_settings()["executor.block_after_loss"] is True


def test_losing_mint_is_not_opened_again(tdb, monkeypatch):
    _arm(monkeypatch)
    _closed(LOSER, -1.25)
    out = _buy(LOSER)
    assert out["status"] == "skipped" and out["reason"] == LOSS
    assert db.one("SELECT 1 FROM positions WHERE mint=? AND closed_at IS NULL", (LOSER,)) is None
    d = db.one("SELECT text, ok FROM decisions WHERE mint=? AND agent='executor'", (LOSER,))
    assert d["ok"] == 0 and LOSS in d["text"]
    sh = db.one("SELECT reason, rule FROM shadow WHERE mint=?", (LOSER,))
    assert LOSS in sh["reason"] and LOSS in sh["rule"]


def test_loss_block_is_read_from_the_db_not_memory(tdb, monkeypatch):
    """A previous shift wrote the closed trade. This process has only the sqlite file."""
    _arm(monkeypatch)
    c = sqlite3.connect(tdb)
    opened = util.iso(util.now() - dt.timedelta(days=3))
    closed = util.iso(util.now() - dt.timedelta(days=2))
    c.execute("INSERT INTO coins(mint,symbol,pool) VALUES(?,?,?)", (LOSER, "HELL", "POOL"))
    c.execute(
        "INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode,"
        "closed_at,exit_price,exit_reason,pnl_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (LOSER, opened, 1.0, 7.48, 1.0, 0.94, 0, 0.2331, "PAPER", closed, 0.88, "stop", -0.91))
    c.commit()
    c.close()
    db._local.c = None
    out = _buy(LOSER)
    assert out["status"] == "skipped" and out["reason"] == LOSS
    assert db.one("SELECT COUNT(*) n FROM positions WHERE mint=?", (LOSER,))["n"] == 1


def test_winner_flat_and_other_mints_still_enter(tdb, monkeypatch):
    _arm(monkeypatch)
    _closed(WINNER, 2.5, symbol="HODL")
    _closed(LOSER, -0.5, symbol="HELL")
    db.upsert_coin(OTHER, pool="POOL", symbol="NEW")
    win = _buy(WINNER)
    other = _buy(OTHER)
    assert win["status"] == "bought" and other["status"] == "bought"
    _closed("FlatMint111111111111111111111111111pump", 0.0, symbol="FLAT")
    flat = _buy("FlatMint111111111111111111111111111pump")
    assert flat["status"] == "bought"


def test_fee_dragged_pnl_blocks_even_if_price_was_up(tdb, monkeypatch):
    _arm(monkeypatch)
    _closed(LOSER, -0.01)
    out = _buy(LOSER)
    assert out["reason"] == LOSS


def test_a_later_win_does_not_lift_an_earlier_loss(tdb, monkeypatch):
    _arm(monkeypatch)
    _closed(LOSER, -2.0)
    _closed(LOSER, 3.0)
    out = _buy(LOSER)
    assert out["reason"] == LOSS


def test_winner_still_obeys_one_signal_a_night(tdb, monkeypatch):
    _arm(monkeypatch)
    _closed(WINNER, 2.0)
    db.x("INSERT INTO signals(mint,ts,price,size_usd,stack_pct,link,mode,status) VALUES(?,?,?,?,?,?,?,?)",
         (WINNER, util.iso(), 1.0, 16, 8, "http://x", "PAPER", "bought"))
    out = _buy(WINNER)
    assert out["status"] == "skipped" and out["reason"] == "already signalled tonight"


def test_live_loss_does_not_block(tdb, monkeypatch):
    _arm(monkeypatch)
    _closed(LOSER, -4.0, mode="LIVE")
    assert _buy(LOSER)["status"] == "bought"


def test_setting_off_allows_reentry_after_a_paper_loss(tdb, monkeypatch):
    _arm(monkeypatch)
    _closed(LOSER, -4.0, mode="PAPER")
    config.set("executor.block_after_loss", False, "t")
    assert config.get("executor.block_after_loss") is False
    assert _buy(LOSER)["status"] == "bought"


def test_loss_reason_wins_when_there_is_no_price(tdb, monkeypatch):
    _arm(monkeypatch)
    db.upsert_coin(LOSER, symbol="HELL")
    db.x(
        "INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,fees_usd,mode,closed_at,pnl_usd) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (LOSER, util.iso(util.now() - dt.timedelta(days=2)), 1.0, 16, 1.0, 0.94, 0.4, "PAPER",
         util.iso(util.now() - dt.timedelta(days=1)), -1.0))
    out = _buy(LOSER)
    assert out["reason"] == LOSS
    assert db.one("SELECT text FROM decisions WHERE mint=?", (LOSER,))["text"].startswith("Skipped · " + LOSS)
