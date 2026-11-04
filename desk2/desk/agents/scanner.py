"""Scanner (PART 4): PumpPortal migrations -> waiting room -> 60s DexScreener batches (by pool) -> kills -> Auditor."""
from __future__ import annotations
import asyncio, datetime as dt, json, os, time
import websockets
from .. import db, util, config, bus, log, fields as F, sources as S, chain, shadow, tags as T

L = log.get("scanner")
WS = "wss://pumpportal.fun/api/data"
NAME = "scanner"
room: dict[str, dict] = {}            # mint -> {"t0": epoch entered, "report": rugcheck report or None, "source": fresh|established,
                                      #          "first_liq", "peak" (max price seen in the room), "rocket", "top10": (pct, t)}
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
    db.upsert_coin(mint, migrated_at=util.iso(), source="fresh")
    room[mint] = {"t0": time.time(), "report": None, "scan_liq": None, "source": "fresh"}
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
            room[mint]["report_t"] = time.time()
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
        r = room.get(mint) or {}
        tg = list(r.get("tags") or []) + (["established"] if r.get("source") == "established" else [])
        db.decide(NAME, mint, c.get("symbol") or c.get("name"), f"{verdict}: {reason}", verdict == "pass", tags=tg)
        if verdict != "pass":
            shadow.record(mint, NAME, reason, v.get("price") if v else None, v.get("liquidity") if v else None,
                          tags=tg, source=r.get("source"))

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

POOL_RETRY_S = 120       # a mint without a known pool asks DexScreener token-pairs at most every 2 min
TOP10_TTL_S = 300        # top-10 (2 RPC calls) is re-read at most every 5 min per coin

async def _top10(mint, c, entry):
    t = entry.get("top10")
    if t and time.time() - t[1] < TOP10_TTL_S:
        return t[0]
    mi_supply = F.read(entry["report"] or {}, F.RUGCHECK_REPORT, "supply")
    if not mi_supply:
        mi_supply = (await chain.mint_info(mint))["supply"]
    v = await chain.top10_pct(mint, float(mi_supply), chain.amm_accounts(entry["report"], c.get("pool")))
    entry["top10"] = (v, time.time())
    return v

def _log_wait(mint, v, top10, age, key, reason):
    """waits are logged at most every 10 min per kind (the room can hold 60 coins polled every minute)."""
    e = room[mint]
    if time.time() - e.get(key, 0) >= 600:
        e[key] = time.time()
        _scan(mint, v, top10, int(age), "wait", reason)

async def poll_once():
    if not room or db.paused(NAME):
        return
    s = config.all_settings()
    pools = {}
    for mint in list(room):
        c = db.coin(mint) or {}
        pool = c.get("pool")
        if not pool and time.time() - room[mint].get("pool_try", 0) >= POOL_RETRY_S:
            room[mint]["pool_try"] = time.time()
            pool = await _pool_from_dex(mint)
        if pool: pools[pool] = mint
    pairs = await S.dex_pairs(list(pools)) if pools else {}     # 30 pools per call
    day = util.now().astimezone(util.TZ).date().isoformat()
    for mint in list(room):
        if mint not in room:
            continue
        e = room[mint]
        c = db.coin(mint) or {}
        waited = (time.time() - e["t0"]) / 60
        v = chain.pair_view(pairs.get(c.get("pool"))) if c.get("pool") else None
        if v and v["price"] is not None:
            db.price(mint, v["price"], v["vol_m5"])
            e["peak"] = max(e.get("peak") or 0, v["price"])
            if v["ch_h24"] is not None and v["ch_h24"] >= s["scanner.runner_h24_pct"]:
                runners[mint] = {"name": v["name"], "symbol": v["symbol"], "day": day}
        if not v or v["liquidity"] is None:
            if waited >= s["scanner.max_wait_min"]:
                _scan(mint, v, None, int(waited), "drop", "never qualified"); _out(mint)
            else:
                _log_wait(mint, v, None, waited, "nodex_log", "DexScreener doesn't know it yet")
            continue
        age = (time.time() * 1000 - v["created_ms"]) / 60000 if v["created_ms"] else waited
        e.setdefault("first_liq", v["liquidity"])
        # kills, first hit wins, in order
        if v["liquidity"] < s["scanner.min_liquidity_usd"]:
            # thin pools stay in the waiting room and are re-read every poll; only after max_wait they die
            if waited >= s["scanner.max_wait_min"]:
                _scan(mint, v, None, int(age), "kill", f"liq {util.money(v['liquidity'])}"); _out(mint)
            else:
                _log_wait(mint, v, None, age, "liq_log", f"liq {util.money(v['liquidity'])}")
            continue
        try:
            top10 = await _top10(mint, c, e)
        except S.RateLimited:
            raise
        except Exception as ex:
            _log_wait(mint, v, None, age, "top10_log", f"top10 no data ({ex})"); continue
        if top10 > s["scanner.max_top10_pct"]:
            _scan(mint, v, top10, int(age), "kill", f"top10 {top10:.0f}%"); _out(mint); continue
        if v["ch_h1"] is None:
            _log_wait(mint, v, top10, age, "h1_log", "no 1h change yet"); continue
        if v["ch_h1"] > s["scanner.max_h1_change_pct"]:
            if not s["scanner.rocket_pullback_on"]:
                _scan(mint, v, top10, int(age), "kill", f"h1 +{v['ch_h1']:.0f}%"); _out(mint); continue
            # mid-rocket: wait in the room for a pullback of rocket_pullback_pct from the peak seen in the room
            e["rocket"] = True
            off = (1 - v["price"] / e["peak"]) * 100 if v["price"] and e.get("peak") else 0
            if off < s["scanner.rocket_pullback_pct"]:
                if waited >= s["scanner.max_wait_min"]:
                    _scan(mint, v, top10, int(age), "kill", f"h1 +{v['ch_h1']:.0f}% (no pullback)"); _out(mint)
                else:
                    _log_wait(mint, v, top10, age, "rocket_log", f"rocket h1 +{v['ch_h1']:.0f}% · {off:.0f}% off peak")
                continue
        cc = _copycat_of(mint, v)
        if cc:
            _scan(mint, v, top10, int(age), "kill", f"copycat of {cc}"); _out(mint); continue
        if age >= s["scanner.min_pool_age_min"]:
            item = {"mint": mint, "scan_liq": v["liquidity"], "scan_price": v["price"], "pair": v,
                    "report": e["report"], "source": e.get("source") or "fresh", "tags": [], "scan_t": e.get("report_t") or time.time(),
                    "top10": top10}
            if item["source"] == "established":
                T.add(item, "established", NAME)
            if (e.get("first_liq") or 0) < s["scanner.min_liquidity_usd"]:
                T.add(item, "waiting_room_liq", NAME)
            if top10 > T.OLD["scanner.max_top10_pct"]:
                T.add(item, "top10_30", NAME)
            if e.get("rocket"):
                T.add(item, "pullback", NAME)
            e["tags"] = [t for t in item["tags"] if t != "established"]
            extra = f" · {((1 - v['price'] / e['peak']) * 100):.0f}% off peak" if e.get("rocket") and e.get("peak") else ""
            agetxt = f"{age / 1440:.1f}d" if age >= 2880 else f"{age:.0f}m"
            _scan(mint, v, top10, int(age), "pass", f"liq {util.money(v['liquidity'])} · top10 {top10:.0f}% · age {agetxt}{extra}")
            db.upsert_coin(mint, name=c.get("name") or v["name"], symbol=c.get("symbol") or v["symbol"], **({"image": v["image"]} if v.get("image") else {}))
            await bus.to_auditor.put(item)
            _out(mint)
        elif waited >= s["scanner.max_wait_min"]:
            _scan(mint, v, top10, int(age), "drop", "never qualified"); _out(mint)
        else:
            _log_wait(mint, v, top10, age, "age_log", f"age {age:.0f}m < {s['scanner.min_pool_age_min']}m")

# ---------------------------------------------------------------- established scanner
GT_SORTS = ("h24_volume_usd_desc", "h24_tx_count_desc")
GT_PAGES = 4
DS_LISTS = ("token-boosts/top/v1", "token-boosts/latest/v1", "token-profiles/latest/v1")
last_established: dict = {"ts": None, "candidates": 0, "added": 0, "sources": {}, "error": None}

def _blocked(mint: str, s: dict) -> str | None:
    if mint in room: return "in room"
    if _skipped(mint): return "skipped"
    if db.one("SELECT 1 FROM positions WHERE mint=? AND closed_at IS NULL", (mint,)): return "open position"
    c = db.coin(mint) or {}
    cd = util.iso(util.now() - dt.timedelta(hours=s["scanner.established_cooldown_h"]))
    if c.get("established_at") and c["established_at"] > cd: return "cooldown"
    if c.get("migrated_at") and c["migrated_at"] > cd: return "fresh graduate"
    return None

async def established_candidates(s: dict) -> tuple[list[dict], dict]:
    """pump.fun-origin coins (mint ...pump) with a PumpSwap pool aged min..max days and liquidity >= min.
    Discovery: GeckoTerminal PumpSwap pool lists + DexScreener boosts/profiles; every candidate is confirmed on
    DexScreener tokens/v1 (PumpSwap pair, pairCreatedAt, liquidity.usd) before it goes into the room."""
    lo, hi, mliq = s["scanner.established_min_age_days"], s["scanner.established_max_age_days"], s["scanner.established_min_liq_usd"]
    found, src = {}, {"geckoterminal": 0, "dexscreener": 0}
    now = time.time()
    for sort in GT_SORTS:
        if src.get("gt_rate_limited"): break
        for page in range(1, GT_PAGES + 1):
            try:
                rows = await S.gt_pumpswap_pools(page, sort)
            except S.RateLimited:      # free tier ~30/min: keep what we have, retry next scan
                src["gt_rate_limited"] = True
                break
            except S.NoData:
                break
            for p in rows:
                bid = F.read(p, F.GECKO_POOL, "base_id") or ""
                mint = bid.removeprefix("solana_")
                created = F.read(p, F.GECKO_POOL, "created_at")
                try:
                    liq = float(F.read(p, F.GECKO_POOL, "reserve_usd") or 0)
                    days = (now - util.parse(created).timestamp()) / 86400
                except Exception:
                    continue
                if mint.endswith("pump") and lo <= days <= hi and liq >= mliq and mint not in found:
                    found[mint] = "geckoterminal"; src["geckoterminal"] += 1
    for path in DS_LISTS:
        try:
            for t in await S.dex_list(path):
                mint = F.read(t, F.DEXSCREENER_LIST, "mint") or ""
                if F.read(t, F.DEXSCREENER_LIST, "chain") == "solana" and mint.endswith("pump") and mint not in found:
                    found[mint] = "dexscreener"
        except (S.NoData, S.RateLimited):
            pass
    pairs = await S.dex_tokens(list(found)) if found else []
    out = []
    for mint, origin in found.items():
        vs = [chain.pair_view(p) for p in pairs if F.read(p, F.DEXSCREENER_PAIR, "base_mint") == mint]
        vs = [v for v in vs if v and v["dex"] == "pumpswap" and v["liquidity"] is not None and v["created_ms"]]
        if not vs: continue
        v = max(vs, key=lambda x: x["liquidity"])
        days = (now * 1000 - v["created_ms"]) / 86_400_000
        if lo <= days <= hi and v["liquidity"] >= mliq:
            out.append({"mint": mint, "pool": v["pool"], "liq": v["liquidity"], "days": days, "origin": origin, "pair": v})
            if origin == "dexscreener": src["dexscreener"] += 1
    out.sort(key=lambda x: -x["liq"])
    return out, src

async def established_once() -> int:
    s = config.all_settings()
    if not s["scanner.established_on"] or db.paused(NAME):
        return 0
    cands, src = await established_candidates(s)
    added = 0
    for cd in cands:
        if added >= s["scanner.established_max_per_scan"]:
            break
        if _blocked(cd["mint"], s):
            continue
        v, mint = cd["pair"], cd["mint"]
        c = db.coin(mint) or {}
        kw = {"pool": cd["pool"], "source": "established", "established_at": util.iso()}
        if not c.get("migrated_at"):   # PumpSwap pool creation = graduation
            kw["migrated_at"] = util.iso(dt.datetime.fromtimestamp(v["created_ms"] / 1000, dt.timezone.utc))
        if not c.get("name") and v["name"]: kw["name"] = v["name"]
        if not c.get("symbol") and v["symbol"]: kw["symbol"] = v["symbol"]
        db.upsert_coin(mint, **kw)
        room[mint] = {"t0": time.time(), "report": None, "scan_liq": None, "source": "established"}
        _scan(mint, v, None, int(cd["days"] * 1440), "wait",
              f"established · {cd['days']:.1f}d · liq {util.money(cd['liq'])} · via {cd['origin']}")
        asyncio.create_task(_resolve(mint))
        added += 1
    last_established.update(ts=util.iso(), candidates=len(cands), added=added, sources=src, error=None,
                            mints=[{"mint": c["mint"], "liq": round(c["liq"]), "days": round(c["days"], 1)} for c in cands[:30]])
    L.info("established scan: %d candidates, %d into the room", len(cands), added)
    return added

async def established_loop():
    await asyncio.sleep(45)
    while True:
        try:
            await established_once()
        except S.RateLimited as ex:
            last_established["error"] = f"429 {ex}"; L.warning("established 429 %s", ex)
        except Exception as ex:
            last_established["error"] = str(ex)[:200]; L.exception("established scan: %s", ex)
        await asyncio.sleep(config.get("scanner.established_every_min") * 60)

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

def _restore_one(mint: str, t0_iso: str, source: str):
    """rebuild a room entry from the DB: entry time, first liquidity, peak price and rocket flag since entry."""
    last = db.one("SELECT verdict FROM scans WHERE mint=? AND ts>=? ORDER BY id DESC LIMIT 1", (mint, t0_iso))
    if last and last["verdict"] in ("kill", "pass", "drop"):
        return False
    e = {"t0": util.parse(t0_iso).timestamp(), "report": None, "scan_liq": None, "source": source}
    f = db.one("SELECT liquidity_usd l FROM scans WHERE mint=? AND ts>=? AND liquidity_usd IS NOT NULL ORDER BY id LIMIT 1", (mint, t0_iso))
    if f: e["first_liq"] = f["l"]
    pk = db.one("SELECT MAX(price) p FROM prices WHERE mint=? AND ts>=?", (mint, t0_iso))
    if pk and pk["p"]: e["peak"] = pk["p"]
    if db.one("SELECT 1 FROM scans WHERE mint=? AND ts>=? AND reason LIKE 'rocket%'", (mint, t0_iso)): e["rocket"] = True
    room[mint] = e
    asyncio.create_task(_resolve(mint))
    return True

def restore():
    """after a restart (handoff), put unfinished coins back in the room: fresh graduates and established coins that
    entered less than max_wait ago and have no kill/pass/drop since they entered."""
    since = util.iso(util.now() - dt.timedelta(minutes=config.get("scanner.max_wait_min")))
    for c in db.q("SELECT * FROM coins WHERE migrated_at > ?", (since,)):
        _restore_one(c["mint"], c["migrated_at"], "fresh")
    for c in db.q("SELECT * FROM coins WHERE established_at > ?", (since,)):
        if c["mint"] not in room:
            _restore_one(c["mint"], c["established_at"], "established")
    L.info("restored %d coins to the room", len(room))

async def run():
    restore()
    await asyncio.gather(ws_loop(), poll_loop(), established_loop())
