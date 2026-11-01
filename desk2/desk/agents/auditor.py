"""Auditor (PART 4): 8 layers, stop at the first red. Retry each read N times 2s apart; no data = red."""
from __future__ import annotations
import asyncio, time
from .. import db, util, config, bus, log, fields as F, sources as S, chain, links, webpush

L = log.get("auditor")
NAME = "auditor"
LAYERS = {1: "Mint authority", 2: "Freeze authority", 3: "Dev wallet", 4: "Top 10 holders",
          5: "Liquidity lock", 6: "Pool age", 7: "Bundled wallets", 8: "Delegations"}
NODATA = {1: "mint", 2: "freeze", 3: "dev", 4: "top10", 5: "lp", 6: "age", 7: "bundles", 8: "delegations"}
SOURCE = {1: "rpc", 2: "rpc", 3: "rpc", 4: "rpc", 5: "rugcheck+dexscreener", 6: "dexscreener", 7: "rugcheck", 8: "rpc"}

class Ctx:
    def __init__(self, mint, item):
        self.mint, self.item, self.cache = mint, item, {}
    async def get(self, key, fn, retries):
        if key in self.cache:
            return self.cache[key]
        last = None
        for i in range(retries):
            try:
                v = await fn()
                self.cache[key] = v
                return v
            except S.RateLimited as e:
                last = e; await asyncio.sleep(30)
            except Exception as e:
                last = e
                if i < retries - 1:
                    await asyncio.sleep(2)
        raise S.NoData(str(last))

async def layer(n: int, c: Ctx, s: dict) -> tuple[bool | None, str]:
    """returns (pass, value_text). pass None only for layer 7's documented 'None' case -> counts as pass."""
    m, R = c.mint, s["auditor.retries"]
    coin = db.coin(m) or {}
    if n in (1, 2):
        mi = await c.get("mint", lambda: chain.mint_info(m), R)
        k = "mint_authority" if n == 1 else "freeze_authority"
        if mi[k] is None:
            return True, "Revoked"
        return False, f"{'mint' if n == 1 else 'freeze'} authority live · {util.short(mi[k])}"
    if n == 3:
        creator = coin.get("creator")
        if not creator:
            rep = await c.get("report", lambda: S.rug_report(m), R)
            creator = F.read(rep, F.RUGCHECK_REPORT, "creator")
            if creator: db.upsert_coin(m, creator=creator)
        at_mig = coin.get("creator_balance_at_migration")
        if not creator or at_mig is None:
            raise S.NoData("creator or balance at migration unknown")
        mi = await c.get("mint", lambda: chain.mint_info(m), R)
        bal = await c.get("dev", lambda: chain.owner_balance(creator, m), R)
        pct = bal / mi["supply"] * 100 if mi["supply"] else None
        if pct is None:
            raise S.NoData("supply")
        sold = max(0.0, at_mig - bal)
        if pct >= s["auditor.max_dev_pct"]:
            return False, f"dev holds {pct:.1f}%"
        if sold > 0:
            return False, f"dev sold {sold / at_mig * 100:.0f}% since migration"
        return True, f"{pct:.1f}% · sold 0"
    if n == 4:
        mi = await c.get("mint", lambda: chain.mint_info(m), R)
        rep = await c.get("report", lambda: S.rug_report(m), R)
        t = await c.get("top10", lambda: chain.top10_pct(m, mi["supply"], chain.amm_accounts(rep, coin.get("pool"))), R)
        return (t < s["auditor.max_top10_pct"]), f"{t:.0f}%"
    if n == 5:
        rep = await c.get("report", lambda: S.rug_report(m), R)
        mk = chain.market_of(rep, coin.get("pool"))
        if not mk:
            raise S.NoData("pool market not in RugCheck")
        lp = chain.fnum(F.get(mk, F.RUGCHECK_REPORT["market_lp_locked_pct"]))
        if lp is None:
            raise S.NoData("lpLockedPct")
        pair = await c.get("pair", lambda: _pair(coin.get("pool")), R)
        if lp < s["auditor.min_lp_locked_pct"]:
            return False, f"LP {lp:.0f}% burned/locked"
        before = c.item.get("scan_liq")
        if before and pair["liquidity"] is not None and pair["liquidity"] < before * (1 - s["auditor.max_liq_drop_pct"] / 100):
            return False, f"liquidity {(pair['liquidity'] / before - 1) * 100:.0f}% since Scanner"
        return True, f"{lp:.0f}% burned/locked"
    if n == 6:
        pair = await c.get("pair", lambda: _pair(coin.get("pool")), R)
        if not pair["created_ms"]:
            raise S.NoData("pairCreatedAt")
        age = (time.time() * 1000 - pair["created_ms"]) / 60000
        return (age >= s["auditor.min_pool_age_min"]), f"{age:.0f} min"
    if n == 7:
        rep = await c.get("report", lambda: S.rug_report(m), R)
        g = await c.get("graph", lambda: S.rug_graph(m), R)
        if isinstance(g, list) and len(g) == 0:
            if F.read(rep, F.RUGCHECK_REPORT, "graph_insiders_detected") == 0:
                return True, "None"
            return False, "no data: bundles"
        big = chain.biggest_bundle(g)
        if big is None:
            return False, "no data: bundles"
        if big >= s["auditor.max_bundled"]:
            return False, f"{big} bundled wallets"
        return True, "None" if big < 2 else f"{big} linked"
    if n == 8:
        accs = await c.get("holders", lambda: chain.holder_accounts(m), R)
        holding = [a for a in accs if a["amount"] > 0]
        db.upsert_coin(m, holders=len({a["owner"] for a in holding}))
        per = {}
        for a in holding:
            if a["delegate"]:
                per[a["delegate"]] = per.get(a["delegate"], 0) + 1
        if per:
            d, k = max(per.items(), key=lambda kv: kv[1])
            if k >= s["auditor.max_delegated_accounts"]:
                return False, f"{k} wallets → {util.short(d)}"
            return True, f"max {k} on one"
        return True, "None"
    raise ValueError(n)

async def _pair(pool):
    if not pool:
        raise S.NoData("no pool")
    v = chain.pair_view((await S.dex_pairs([pool])).get(pool))
    if not v:
        raise S.NoData("pair")
    return v

async def audit(item: dict, record: bool = True) -> bool:
    m = item["mint"]
    s = config.all_settings()
    coin = db.coin(m) or {}
    name = coin.get("symbol") or coin.get("name") or util.short(m)
    c = Ctx(m, item)
    red_at, reason = None, None
    bus.emit("audit_start", {"mint": m, "name": name})
    for n in range(1, 9):
        if red_at:
            db.x("INSERT INTO audits(mint,ts,layer,name,value_text,pass,source) VALUES(?,?,?,?,?,?,?)",
                 (m, util.iso(), n, LAYERS[n], "not checked", None, SOURCE[n]))
            bus.emit("audit_layer", {"mint": m, "layer": n, "name": LAYERS[n], "value": "not checked", "pass": None})
            continue
        try:
            ok, val = await layer(n, c, s)
        except Exception as e:
            ok, val = False, f"no data: {NODATA[n]}"
            L.info("%s layer %d no data: %s", m, n, e)
        db.x("INSERT INTO audits(mint,ts,layer,name,value_text,pass,source) VALUES(?,?,?,?,?,?,?)",
             (m, util.iso(), n, LAYERS[n], val, 1 if ok else 0, SOURCE[n]))
        bus.emit("audit_layer", {"mint": m, "layer": n, "name": LAYERS[n], "value": val, "pass": bool(ok)})
        if not ok:
            red_at, reason = n, val
    if red_at and not record:
        return False
    if red_at:
        db.activity("rejected", m, "Auditor", f"Rejected {name}", f"Auditor · {reason}", "Skipped")
        db.decide(NAME, m, name, f"Rejected · {reason} (layer {red_at})", False)
        L.info("REJECT %s layer %d %s", m, red_at, reason)
        if s["desk.push_rejects"]:
            await webpush.push(f"Rejected {name}", f"Auditor · {reason}", m, "rejected")
        return False
    if not record:
        return True
    db.decide(NAME, m, name, "Cleared · 8/8 parts", True)
    L.info("CLEAR %s 8/8", m)
    return True

async def run():
    while True:
        item = await bus.to_auditor.get()
        db.heartbeat(NAME)
        while db.paused(NAME):
            await asyncio.sleep(5)
        try:
            if not config.get("auditor.enabled"):
                db.decide(NAME, item["mint"], None, "Take-apart OFF · passed through unchecked", True)
                item["audit"] = "off"
                await bus.to_analyst.put(item); continue
            if await audit(item):
                item["audit"] = "8/8"
                await bus.to_analyst.put(item)
        except Exception as e:
            L.exception("audit crash %s: %s", item.get("mint"), e)

async def beat():
    while True:
        db.heartbeat(NAME); await asyncio.sleep(30)
