"""Scanner (PART 4): PumpPortal migrations -> waiting room -> 60s DexScreener batches (by pool) -> kills -> Auditor."""
from __future__ import annotations
import asyncio, json, os, time
import websockets
from .. import db, util, config, bus, log, fields as F, sources as S, chain

L = log.get("scanner")
WS = "wss://pumpportal.fun/api/data"
NAME = "scanner"
room: dict[str, dict] = {}            # mint -> {"t0": monotonic-ish epoch, "report": rugcheck report or None}
runners: dict[str, dict] = {}         # coins seen today with h24 >= runner pct: mint -> {"name","symbol","day"}
_last_msg = time.time()

def _tonight_seen(mint: str) -> bool:
    c = db.coin(mint)
    if not c or not c.get("migrated_at"):
        return False
    return util.parse(c["migrated_at"]) >= util.night_start(config.get("desk.report_time"))

def _skipped(mint: str) -> bool:
    return db.one("SELECT 1 FROM skips WHERE mint=? AND until>?", (mint, util.iso())) is not None

async def on_migration(mint: str, raw: dict | None = None):
    if db.paused(NAME):
        L.info("paused, ignoring migration %s", mint); return
    if mint in room or _tonight_seen(mint) or _skipped(mint):
        return
    db.upsert_coin(mint, migrated_at=util.iso())
    room[mint] = {"t0": time.time(), "report": None, "scan_liq": None}
    L.info("migration %s -> waiting room (%d)", mint, len(room))
    bus.emit("scan", {"mint": mint, "verdict": "wait", "reason": "graduated", "room": len(room)})
    asyncio.create_task(_resolve(mint))

async def _resolve(mint: str):
    """creator (RugCheck when not in the message), pool, name; creator balance AT MIGRATION."""
    for attempt in range(8):
        if mint not in room:
            return
        try:
            rep = await S.rug_report(mint)
            room[mint]["report"] = rep
            r = lambda k: F.read(rep, F.RUGCHECK_REPORT, k)
            m = chain.market_of(rep)
            kw = {"name": r("name"), "symbol": r("symbol"), "creator": r("creator")}
            if m: kw["pool"] = F.get(m, F.RUGCHECK_REPORT["market_pool"])
            db.upsert_coin(mint, **{k: v for k, v in kw.items() if v})
            c = db.coin(mint)
            if c.get("creator") and c.get("creator_balance_at_migration") is None:
                try:
                    bal = await chain.owner_balance(c["creator"], mint)
                    db.upsert_coin(mint, creator_balance_at_migration=bal)
                except Exception as e:
                    L.warning("creator balance %s: %s", mint, e)
                    continue
            if c.get("pool"):
                return
        except S.RateLimited:
            await asyncio.sleep(30)
        except Exception as e:
            L.info("resolve %s try %d: %s", mint, attempt, e)
        await asyncio.sleep(min(10 * (attempt + 1), 60))

async def _pool_from_dex(mint: str):
    try:
        for p in await S.dex_token_pairs(mint):
            v = chain.pair_view(p)
            if v and v["dex"] == "pumpswap":
                db.upsert_coin(mint, pool=v["pool"], **({"name": v["name"]} if not (db.coin(mint) or {}).get("name") else {}),
                               **({"symbol": v["symbol"]} if not (db.coin(mint) or {}).get("symbol") else {}))
                return v["pool"]
    except S.RateLimited:
        raise
    except Exception as e:
        L.info("token-pairs %s: %s", mint, e)

def _scan(mint, v, top10, age, verdict, reason):
    db.insert("scans", mint=mint, ts=util.iso(), liquidity_usd=v.get("liquidity") if v else None, top10_pct=top10,
              h1_change_pct=v.get("ch_h1") if v else None, age_min=age, verdict=verdict, reason=reason)
    c = db.coin(mint) or {}
    bus.emit("scan", {"mint": mint, "name": c.get("name") or c.get("symbol"), "verdict": verdict, "reason": reason,
                      "liquidity": v.get("liquidity") if v else None, "room": len(room)})
    if verdict in ("kill", "pass", "drop"):
        db.decide(NAME, mint, c.get("symbol") or c.get("name"), f"{verdict}: {reason}", verdict == "pass")

def _out(mint):
    room.pop(mint, None)

def _copycat_of(mint, v) -> str | None:
    day = util.now().astimezone(util.TZ).date().isoformat()
    nm, sy = (v.get("name") or "").strip().lower(), (v.get("symbol") or "").strip().lower()
    for m, r in runners.items():
        if m == mint or r["day"] != day:
            continue
        if (nm and nm == (r["name"] or "").lower()) or (sy and sy == (r["symbol"] or "").lower()):
            return r["symbol"] or r["name"]
    return None

async def poll_once():
    if not room or db.paused(NAME):
        return
    s = config.all_settings()
    pools = {}
    for mint in list(room):
        c = db.coin(mint) or {}
        pool = c.get("pool") or await _pool_from_dex(mint)
        if pool: pools[pool] = mint
    pairs = await S.dex_pairs(list(pools)) if pools else {}
    day = util.now().astimezone(util.TZ).date().isoformat()
    for mint in list(room):
        c = db.coin(mint) or {}
        waited = (time.time() - room[mint]["t0"]) / 60
        v = chain.pair_view(pairs.get(c.get("pool"))) if c.get("pool") else None
        if v and v["price"] is not None:
            db.price(mint, v["price"], v["vol_m5"])
            if v["ch_h24"] is not None and v["ch_h24"] >= s["scanner.runner_h24_pct"]:
                runners[mint] = {"name": v["name"], "symbol": v["symbol"], "day": day}
        if not v or v["liquidity"] is None:
            if waited >= s["scanner.max_wait_min"]:
                _scan(mint, v, None, int(waited), "drop", "never qualified"); _out(mint)
            else:
                _scan(mint, v, None, int(waited), "wait", "DexScreener doesn't know it yet")
            continue
        age = (time.time() * 1000 - v["created_ms"]) / 60000 if v["created_ms"] else waited
        room[mint].setdefault("first_liq", v["liquidity"])
        # kills, first hit wins, in order
        if v["liquidity"] < s["scanner.min_liquidity_usd"]:
            _scan(mint, v, None, int(age), "kill", f"liq {util.money(v['liquidity'])}"); _out(mint); continue
        try:
            mi_supply = F.read(room[mint]["report"] or {}, F.RUGCHECK_REPORT, "supply")
            if not mi_supply:
                mi_supply = (await chain.mint_info(mint))["supply"]
            top10 = await chain.top10_pct(mint, float(mi_supply), chain.amm_accounts(room[mint]["report"], c.get("pool")))
        except S.RateLimited:
            raise
        except Exception as e:
            _scan(mint, v, None, int(age), "wait", f"top10 no data ({e})"); continue
        if top10 > s["scanner.max_top10_pct"]:
            _scan(mint, v, top10, int(age), "kill", f"top10 {top10:.0f}%"); _out(mint); continue
        if v["ch_h1"] is None:
            _scan(mint, v, top10, int(age), "wait", "no 1h change yet"); continue
        if v["ch_h1"] > s["scanner.max_h1_change_pct"]:
            _scan(mint, v, top10, int(age), "kill", f"h1 +{v['ch_h1']:.0f}%"); _out(mint); continue
        cc = _copycat_of(mint, v)
        if cc:
            _scan(mint, v, top10, int(age), "kill", f"copycat of {cc}"); _out(mint); continue
        if age >= s["scanner.min_pool_age_min"]:
            _scan(mint, v, top10, int(age), "pass", f"liq {util.money(v['liquidity'])} · top10 {top10:.0f}% · age {age:.0f}m")
            db.upsert_coin(mint, name=c.get("name") or v["name"], symbol=c.get("symbol") or v["symbol"], **({"image": v["image"]} if v.get("image") else {}))
            await bus.to_auditor.put({"mint": mint, "scan_liq": v["liquidity"], "scan_price": v["price"], "pair": v,
                                      "report": room[mint]["report"]})
            _out(mint)
        elif waited >= s["scanner.max_wait_min"]:
            _scan(mint, v, top10, int(age), "drop", "never qualified"); _out(mint)
        else:
            _scan(mint, v, top10, int(age), "wait", f"age {age:.0f}m < {s['scanner.min_pool_age_min']}m")

async def poll_loop():
    while True:
        db.heartbeat(NAME)
        try:
            await poll_once()
        except S.RateLimited as e:
            L.warning("429 %s, waiting 30s", e); db.event("429", f"scanner {e}")
            await asyncio.sleep(30); continue
        except Exception as e:
            L.exception("poll error: %s", e)
        await asyncio.sleep(config.get("scanner.poll_s"))

async def ws_loop():
    global _last_msg
    backoff = 1
    raw_log = os.path.join(util.LOGS, "migrations.jsonl")
    while True:
        try:
            async with websockets.connect(WS, ping_interval=20, ping_timeout=20, open_timeout=20) as ws:
                await ws.send(json.dumps({"method": "subscribeMigration"}))
                db.event("ws_connect", "pumpportal"); L.info("ws connected")
                backoff = 1
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=120)
                    except asyncio.TimeoutError:
                        L.info("ws silent 120s, reconnecting"); db.event("ws_silent", "120s")
                        break
                    _last_msg = time.time()
                    db.heartbeat("scanner_ws")
                    try:
                        j = json.loads(msg)
                    except Exception:
                        continue
                    mint = F.read(j, F.PUMPPORTAL, "mint")
                    if mint and F.read(j, F.PUMPPORTAL, "tx_type") == "migrate":
                        with open(raw_log, "a") as fh:
                            fh.write(json.dumps({"recv": util.iso(), **j}) + "\n")
                        await on_migration(mint, j)
            await asyncio.sleep(1)
        except Exception as e:
            L.warning("ws closed: %s; retry in %ds", e, backoff); db.event("ws_closed", str(e)[:120])
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

def restore():
    """after a restart, put tonight's unfinished coins back in the room."""
    mw = config.get("scanner.max_wait_min")
    for c in db.q("SELECT * FROM coins WHERE migrated_at > ?", (util.iso(util.now() - __import__('datetime').timedelta(minutes=mw)),)):
        last = db.one("SELECT verdict FROM scans WHERE mint=? ORDER BY id DESC LIMIT 1", (c["mint"],))
        if last and last["verdict"] in ("kill", "pass", "drop"):
            continue
        room[c["mint"]] = {"t0": util.parse(c["migrated_at"]).timestamp(), "report": None, "scan_liq": None}
        asyncio.create_task(_resolve(c["mint"]))
    L.info("restored %d coins to the room", len(room))

async def run():
    restore()
    await asyncio.gather(ws_loop(), poll_loop())
