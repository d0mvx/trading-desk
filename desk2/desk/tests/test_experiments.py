"""Shadow list, established scanner, mid-rocket pullback, experiment tags, borderline half size, restore, migrations."""
import asyncio, datetime as dt, json, sqlite3, time
import pytest
from desk import db, util, config, shadow, tags as T
from desk.agents import scanner, executor, analyst, auditor

MINT = "RockETmint1111111111111111111111111111pump"

def _v(price, liq=60_000, h1=150, pool="POOL1", created_min=30, dex="pumpswap", mint=MINT):
    return {"liquidity": liq, "price": price, "vol_m5": 1, "ch_h24": 0, "ch_h1": h1, "created_ms": time.time() * 1000 - created_min * 60_000,
            "name": "R", "symbol": "R", "pool": pool, "dex": dex, "base_mint": mint, "image": None, "mcap": 1e6, "sol_usd": 150,
            "ch_m5": 0, "buys_m5": 1, "sells_m5": 1, "buys_h1": 1, "sells_h1": 1, "vol_h1": 1}

def _poll(monkeypatch, v, top10=20.0):
    async def pairs(_): return {"POOL1": {}}
    async def t10(*a): return top10
    monkeypatch.setattr(scanner.S, "dex_pairs", pairs)
    monkeypatch.setattr(scanner.chain, "pair_view", lambda p: v)
    monkeypatch.setattr(scanner, "_top10", lambda m, c, e: t10())
    asyncio.run(scanner.poll_once())

@pytest.fixture
def room(tdb):
    scanner.room.clear()
    while not scanner.bus.to_auditor.empty(): scanner.bus.to_auditor.get_nowait()
    db.upsert_coin(MINT, pool="POOL1", migrated_at=util.iso(), source="fresh")
    yield scanner.room
    scanner.room.clear()

def _last_scan():
    return db.one("SELECT verdict, reason FROM scans ORDER BY id DESC LIMIT 1")

def test_rocket_waits_then_passes_on_pullback(room, monkeypatch):
    room[MINT] = {"t0": time.time() - 120, "report": None, "scan_liq": None, "source": "fresh"}
    _poll(monkeypatch, _v(1.0))
    assert MINT in room and room[MINT]["rocket"] and _last_scan()["reason"].startswith("rocket")
    _poll(monkeypatch, _v(1.2))           # new peak
    _poll(monkeypatch, _v(1.1))           # only 8% off the peak -> still waiting
    assert MINT in room and room[MINT]["peak"] == 1.2
    _poll(monkeypatch, _v(1.0))           # 16.7% off the 1.2 peak -> pass, tagged pullback
    assert MINT not in room
    assert _last_scan()["verdict"] == "pass"
    item = scanner.bus.to_auditor.get_nowait()
    assert item["tags"] == ["pullback"]
    assert db.one("SELECT tag FROM tag_events WHERE mint=?", (MINT,))["tag"] == "pullback"
    assert "[pullback]" in db.one("SELECT text FROM decisions WHERE agent='scanner' ORDER BY id DESC LIMIT 1")["text"]

def test_rocket_without_pullback_dies_at_max_wait(room, monkeypatch):
    room[MINT] = {"t0": time.time() - 61 * 60, "report": None, "scan_liq": None, "source": "fresh", "peak": 1.0}
    _poll(monkeypatch, _v(0.95))
    assert MINT not in room and _last_scan()["reason"] == "h1 +150% (no pullback)"
    assert db.one("SELECT rule FROM shadow WHERE mint=?", (MINT,))["rule"] == "scanner: h1 (no pullback)"

def test_rocket_flag_off_kills_at_once(room, monkeypatch):
    config.set("scanner.rocket_pullback_on", False, "t")
    room[MINT] = {"t0": time.time() - 120, "report": None, "scan_liq": None, "source": "fresh"}
    _poll(monkeypatch, _v(1.0))
    assert MINT not in room and _last_scan()["verdict"] == "kill"

def test_loosened_rule_tags(room, monkeypatch):
    config.set("scanner.max_top10_pct", 30, "t")
    room[MINT] = {"t0": time.time() - 120, "report": None, "scan_liq": None, "source": "fresh", "first_liq": 15_000}
    _poll(monkeypatch, _v(1.0, h1=10), top10=28.0)
    item = scanner.bus.to_auditor.get_nowait()
    assert sorted(item["tags"]) == ["top10_30", "waiting_room_liq"]
    assert item["top10"] == 28.0

def test_room_scales_dex_batches_and_throttles(room, monkeypatch):
    """60 coins: 2 DexScreener batch calls per poll; mints without a pool ask token-pairs once per 2 min."""
    calls = {"pairs": 0, "tp": 0}
    for i in range(60):
        m = f"M{i:02d}xpump"
        if i < 50: db.upsert_coin(m, pool=f"P{i}")
        room[m] = {"t0": time.time() - 60, "report": None, "scan_liq": None, "source": "fresh"}
    room.pop(MINT, None)
    async def tp(m): calls["tp"] += 1; return []
    real = scanner.S.dex_pairs
    async def get(url, lim):
        calls["pairs"] += 1; return {"pairs": []}
    monkeypatch.setattr(scanner.S, "dex_token_pairs", tp)
    monkeypatch.setattr(scanner.S, "_get", get)
    asyncio.run(scanner.poll_once()); asyncio.run(scanner.poll_once())
    assert calls["pairs"] == 4          # 50 pools -> 2 calls per poll
    assert calls["tp"] == 10            # 10 pool-less mints, once each across both polls
    assert len(room) == 60

def test_restore_rebuilds_room(tdb):
    scanner.room.clear()
    t0 = util.iso(util.now() - dt.timedelta(minutes=20))
    db.upsert_coin("A1pump", migrated_at=t0, source="fresh")
    db.upsert_coin("B1pump", migrated_at=util.iso(util.now() - dt.timedelta(days=5)), established_at=t0, source="established")
    db.upsert_coin("C1pump", migrated_at=t0)
    db.insert("scans", mint="A1pump", ts=t0, liquidity_usd=12_000, verdict="wait", reason="liq $12K")
    db.insert("scans", mint="A1pump", ts=util.iso(), liquidity_usd=30_000, verdict="wait", reason="rocket h1 +120%")
    db.price("A1pump", 2.0, 1); db.insert("scans", mint="C1pump", ts=util.iso(), verdict="kill", reason="top10 40%")
    async def go():
        async def nores(m): return None
        scanner._resolve = nores
        scanner.restore()
    orig = scanner._resolve
    try:
        asyncio.run(go())
    finally:
        scanner._resolve = orig
    assert set(scanner.room) == {"A1pump", "B1pump"}
    a = scanner.room["A1pump"]
    assert a["first_liq"] == 12_000 and a["rocket"] and a["peak"] == 2.0
    assert scanner.room["B1pump"]["source"] == "established"
    scanner.room.clear()

def _gt(mint, days, liq):
    return {"attributes": {"address": "pool_" + mint, "pool_created_at": util.iso(util.now() - dt.timedelta(days=days)),
                           "reserve_in_usd": str(liq)}, "relationships": {"base_token": {"data": {"id": "solana_" + mint}}}}

def _ds(mint, days, liq, dex="pumpswap"):
    return {"chainId": "solana", "dexId": dex, "pairAddress": "pool_" + mint, "baseToken": {"address": mint, "name": mint, "symbol": mint[:4]},
            "priceUsd": "0.01", "liquidity": {"usd": liq}, "pairCreatedAt": int((time.time() - days * 86400) * 1000)}

def test_established_scan(tdb, monkeypatch):
    scanner.room.clear()
    gt = [_gt("Good1pump", 5, 150_000), _gt("Young1pump", 0.3, 500_000), _gt("Old1pump", 90, 500_000),
          _gt("Thin1pump", 5, 50_000), _gt("NotPumpMint", 5, 900_000)]
    async def gtp(page, sort): return gt if page == 1 else []
    async def lst(path): return [{"chainId": "solana", "tokenAddress": "Boost1pump"}, {"chainId": "base", "tokenAddress": "0xpump"}]
    async def toks(mints): return [_ds("Good1pump", 5, 160_000), _ds("Good1pump", 5, 1_000, dex="pumpfun"), _ds("Boost1pump", 12, 300_000)]
    monkeypatch.setattr(scanner.S, "gt_pumpswap_pools", gtp)
    monkeypatch.setattr(scanner.S, "dex_list", lst)
    monkeypatch.setattr(scanner.S, "dex_tokens", toks)
    async def nores(m): return None
    monkeypatch.setattr(scanner, "_resolve", nores)
    assert asyncio.run(scanner.established_once()) == 2
    assert scanner.last_established["candidates"] == 2 and scanner.last_established["sources"] == {"geckoterminal": 1, "dexscreener": 1}
    assert {m: e["source"] for m, e in scanner.room.items()} == {"Boost1pump": "established", "Good1pump": "established"}
    c = db.coin("Good1pump")
    assert c["source"] == "established" and c["pool"] == "pool_Good1pump" and c["established_at"] and c["migrated_at"]
    scanner.room.clear()
    assert asyncio.run(scanner.established_once()) == 0          # 6h cooldown
    config.set("scanner.established_on", False, "t")
    assert asyncio.run(scanner.established_once()) == 0

def test_shadow_record_check_summary(tdb, monkeypatch):
    old = util.iso(util.now() - dt.timedelta(hours=25))
    for i, (m, rule) in enumerate([("W1pump", "liq"), ("W2pump", "liq"), ("D1pump", "liq"), ("G1pump", "liq")]):
        db.insert("shadow", mint=m, ts=old, stage="scanner", rule="scanner: liq", reason="liq $20K", price=1.0, liq=20_000, source="fresh")
    shadow.record("So11111111111111111111111111111111111111112", "scanner", "liq $1")       # noise
    shadow.record("Fresh1pump", "auditor", "dev holds 30%", 1.0, 50_000, rule="auditor: Dev wallet")
    shadow.record("Fresh1pump", "auditor", "dev holds 30%", 1.0, 50_000)                      # dedup 6h
    assert db.one("SELECT COUNT(*) n FROM shadow")["n"] == 5
    seen = []
    async def toks(mints):
        seen.append(len(mints))
        return [_ds("W1pump", 1, 50_000) | {"priceUsd": "2.5"}, _ds("W2pump", 1, 10_000) | {"priceUsd": "3"},
                _ds("D1pump", 1, 2_000) | {"priceUsd": "0.9"}]
    monkeypatch.setattr(shadow.S, "dex_tokens", toks)
    assert asyncio.run(shadow.check_once()) == 8      # 4 rows x (+6h, +24h); Fresh1pump not due
    r = shadow.summary(util.iso(util.now() - dt.timedelta(days=3)))
    d = r["rules"]["scanner: liq"]
    assert d["rejected"] == 4 and d["x2_24h"] == 1 and d["x1_5_24h"] == 1     # W2 ran 3x but liq < $20K
    assert d["died_24h"] == 2 and d["gone_24h"] == 1                         # D1 liq < $5K, G1 not listed
    assert r["top_missed"][0]["mint"] == "W1pump" and r["top_missed"][0]["multiple"] == 2.5
    assert r["rules"]["auditor: Dev wallet"]["rejected"] == 1
    assert "Shadow" in "\n".join(shadow.markdown(util.iso(util.now() - dt.timedelta(days=3)), "Shadow list"))

def test_shadow_backfill(tdb):
    t = util.iso(util.now() - dt.timedelta(hours=3))
    db.price("K1pump", 0.5, 1)
    db.x("UPDATE prices SET ts=? WHERE mint='K1pump'", (util.iso(util.now() - dt.timedelta(hours=4)),))
    db.insert("decisions", ts=t, agent="scanner", mint="K1pump", name="K", text="kill: top10 40%", ok=0)
    db.insert("decisions", ts=t, agent="auditor", mint="K2pump", name="K", text="Rejected · dev holds 30% (layer 3)", ok=0)
    db.insert("decisions", ts=t, agent="analyst", mint="K3pump", name="K", text="Score 55 · alive_6h 0.40, score 55", ok=0)
    assert shadow.backfill() == 3
    rows = {r["mint"]: r for r in db.q("SELECT * FROM shadow")}
    assert rows["K1pump"]["rule"] == "scanner: top10" and rows["K1pump"]["price"] == 0.5
    assert rows["K2pump"]["rule"] == "auditor: Dev wallet"
    assert rows["K3pump"]["rule"] == "analyst: alive_6h"
    assert shadow.backfill() == 0

def test_jev_loose_and_borderline(tdb):
    s = config.all_settings()
    s.update({"analyst.min_alive_6h": 0.60, "analyst.min_organic": 0.55, "analyst.max_chase": 0.45, "analyst.min_score": 50})
    a = {"alive_6h": 0.65, "organic": 0.8, "flush": 0.5, "chase": 0.2}
    score, ok, _ = analyst.gate(a, s)
    assert ok and not analyst.gate(a, {**s, **{k: T.OLD[k] for k in T.OLD if k.startswith("analyst.")}})[1]
    assert "alive_6h near min" in analyst.borderline(a, score, s)
    assert analyst.borderline({"alive_6h": 0.9, "organic": 0.9, "flush": 0.9, "chase": 0.1}, 90, s) == []

def test_extra_state_text():
    e = {"holders": {"at_scan": 100, "now": 160, "minutes": 12}, "txns": {"buys_m5": 5, "sells_m5": 2, "buys_h1": None},
         "makers": {"buyers_m5": 4, "sellers_m5": 1}, "top_wallet_age_days": [{"pct": 3.2, "days": 0.4, "capped": False},
                                                                              {"pct": 2.0, "days": None, "capped": False}]}
    t = analyst.extra_text(e)
    assert "Holders 160 now (at scanner 100, +60 in 12 min)" in t and "m5 5 buys / 2 sells" in t
    assert "m5 4 buyers / 1 sellers" in t and "3.2% holder 0.4d" in t and "h1" not in t.split("Unique")[0]
    assert analyst.extra_text({"holders": None, "txns": {}, "makers": None, "top_wallet_age_days": None}) == ""

def test_borderline_half_size_and_experiments(tdb, monkeypatch):
    db.upsert_coin(MINT, pool="POOL1", symbol="R")
    async def pairs(_): return {"POOL1": {}}
    async def push(*a, **k): return "ok"
    monkeypatch.setattr(executor.S, "dex_pairs", pairs)
    monkeypatch.setattr(executor.chain, "pair_view", lambda p: _v(1.0, liq=1_000_000, h1=5))
    monkeypatch.setattr(executor.webpush, "push", push)
    monkeypatch.setattr(executor.account, "equity", lambda: 1000.0)
    monkeypatch.setattr(executor.account, "free", lambda: 1000.0)
    item = {"mint": MINT, "tags": ["bundled_6"], "analyst": {"score": 70, "price": 1.0, "borderline": []}, "audit": "8/8"}
    out = asyncio.run(executor.execute(item))
    assert out["status"] == "bought" and out["sizeUsd"] == 40          # 4% instead of 8%
    p = db.one("SELECT * FROM positions WHERE mint=?", (MINT,))
    assert p["tags"] == "bundled_6,half_size"
    db.x("UPDATE positions SET closed_at=?, pnl_usd=12.5 WHERE id=?", (util.iso(), p["id"]))
    ex = T.experiments()["tags"]
    assert ex["half_size"]["trades"] == 1 and ex["half_size"]["pnl_usd"] == 12.5 and ex["half_size"]["passed"] == {"executor": 1}
    assert ex["bundled_6"]["trades"] == 1 and ex["established"]["trades"] == 0
    # not borderline -> full 8%
    db.upsert_coin("Full1pump", pool="POOL1", symbol="F")
    out = asyncio.run(executor.execute({"mint": "Full1pump", "tags": [], "analyst": {"score": 90, "price": 1.0, "borderline": []}}))
    assert out["sizeUsd"] == 80

def test_migrations_add_columns(tmp_path):
    p = str(tmp_path / "old.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE coins (mint TEXT PRIMARY KEY, name TEXT)"); c.execute("CREATE TABLE verdicts (id INTEGER PRIMARY KEY, mint TEXT)")
    c.commit(); c.close()
    old = db.DB_PATH
    db.use(p)
    try:
        db.conn()
        cols = {r["name"] for r in db.q("PRAGMA table_info(coins)")}
        assert {"source", "established_at", "tags", "image"} <= cols
        assert {"extra", "tags"} <= {r["name"] for r in db.q("PRAGMA table_info(verdicts)")}
        assert db.q("SELECT * FROM shadow") == [] and db.q("SELECT * FROM tag_events") == []
    finally:
        db.use(old)

@pytest.mark.parametrize("big,tagged", [(6, True), (4, False)])
def test_auditor_bundled_6_tag(tdb, monkeypatch, big, tagged):
    async def layer(n, c, s):
        if n == 7: c.cache["bundle_n"] = big
        return True, "ok"
    monkeypatch.setattr(auditor, "layer", layer)
    item = {"mint": MINT, "tags": []}
    assert asyncio.run(auditor.audit(item))
    assert ("bundled_6" in item["tags"]) == tagged

def test_auditor_reject_goes_to_shadow(tdb, monkeypatch):
    async def layer(n, c, s):
        return (False, "dev holds 30.0%") if n == 3 else (True, "ok")
    monkeypatch.setattr(auditor, "layer", layer)
    assert not asyncio.run(auditor.audit({"mint": MINT, "scan_price": 0.5, "scan_liq": 70_000, "tags": ["established"]}))
    r = db.one("SELECT * FROM shadow WHERE mint=?", (MINT,))
    assert r["rule"] == "auditor: Dev wallet" and r["price"] == 0.5 and r["tags"] == "established"

def test_shadow_suspect_multiples_excluded(tdb):
    for m, liq, x in (("S1pump", 50, 3.0), ("S2pump", 30_000, 500.0), ("S3pump", 30_000, 3.0)):
        db.insert("shadow", mint=m, ts=util.iso(), stage="scanner", rule="scanner: liq", reason="liq", price=1.0, liq=liq,
                  p6=x, l6=50_000, x6=x, t6=util.iso())
    d = shadow.summary()["rules"]["scanner: liq"]
    assert d["x2_6h"] == 1 and d["suspect_6h"] == 2
    assert [w["mint"] for w in shadow.summary()["top_missed"]] == ["S3pump"]
