"""Shadow list: every coin the desk rejects (scanner kill/drop, auditor red, analyst reject, executor skip) is recorded with
its price + liquidity at rejection; a background job re-reads it on DexScreener (tokens/v1, 30 mints per call) at +6h and
+24h and stores price, liquidity and the multiple. Summaries per rule: report.py + GET /api/shadow.
One row per (mint, stage) per 6h at most; rows older than desk.shadow_keep_days are deleted -> the table stays small."""
from __future__ import annotations
import asyncio, datetime as dt, re
from collections import defaultdict
from . import db, util, config, log, links, sources as S, chain, fields as F

L = log.get("shadow")
# wrapped / stable / blue-chip mints that are never memecoin rejections
NOISE = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
         "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
         "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn", "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
         "3NZ9JMVBmGAqocybic2c8LQCJScmgsAZ6vQqTDzcqmJh", "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij"}
H6, H24 = 6, 24
WIN_LIQ, DEAD_LIQ = 20_000, 5_000

def is_noise(mint: str, source: str | None = None) -> bool:
    if not mint or mint in NOISE:
        return True
    # only pump.fun-origin coins (mint suffix 'pump' or a PumpSwap pool we found) are worth shadowing
    return not (mint.endswith("pump") or source in ("fresh", "established") or (db.coin(mint) or {}).get("pool"))

def rule_of(stage: str, reason: str) -> str:
    r = (reason or "").strip()
    if stage == "scanner":
        if r.startswith("copycat"): return "scanner: copycat"
        if r.startswith("top10 no data"): return "scanner: top10 no data"
        m = re.search(r"\s*\((.*)\)$", r)
        note = m.group(1) if m else None
        r = re.sub(r"\s*\(.*\)$", "", r)
        r = re.sub(r"\s+[$+\-]?[\d.,]+[KM%]?$", "", r).strip() or r
        return f"scanner: {r}" + (" (no pullback)" if note == "no pullback" else "")
    if stage == "analyst":
        return "analyst: " + (re.split(r"[ ;]", r)[0] or "reject")
    return f"{stage}: {r}"

def record(mint: str, stage: str, reason: str, price=None, liq=None, tags=None, source=None, rule=None):
    """called by the agents on every rejection. Never raises."""
    try:
        if not config.get("desk.shadow_on"):
            return
        c = db.coin(mint) or {}
        source = source or c.get("source") or "fresh"
        if is_noise(mint, source):
            return
        since = util.iso(util.now() - dt.timedelta(hours=H6))
        if db.one("SELECT 1 FROM shadow WHERE mint=? AND stage=? AND ts>?", (mint, stage, since)):
            return
        if price is None:   # last price the desk saw for it (scanner writes one every poll while the coin is in the room)
            r = db.one("SELECT price FROM prices WHERE mint=? AND price IS NOT NULL ORDER BY ts DESC LIMIT 1", (mint,))
            price = r["price"] if r else None
        tg = tags if isinstance(tags, str) or tags is None else (",".join(sorted(set(tags))) or None)
        db.insert("shadow", mint=mint, ts=util.iso(), stage=stage, rule=rule or rule_of(stage, reason), reason=(reason or "")[:120],
                  price=price, liq=liq, source=source, tags=tg)
    except Exception as e:
        L.warning("shadow record %s: %s", mint, e)

def best_pair(pairs: list[dict], mint: str) -> dict | None:
    """PumpSwap pair first (tokens/v1 can also return the old curve pair), else the most liquid pair of this base mint."""
    vs = [chain.pair_view(p) for p in pairs if F.read(p, F.DEXSCREENER_PAIR, "base_mint") == mint]
    vs = [v for v in vs if v]
    ps = [v for v in vs if v["dex"] == "pumpswap"] or vs
    return max(ps, key=lambda v: v["liquidity"] or 0) if ps else None

async def check_once(now: dt.datetime | None = None) -> int:
    now = now or util.now()
    done = 0
    for h, p, l, x, t in ((H6, "p6", "l6", "x6", "t6"), (H24, "p24", "l24", "x24", "t24")):
        rows = db.q(f"SELECT id, mint, price FROM shadow WHERE {t} IS NULL AND ts<=? ORDER BY ts LIMIT 600",
                    (util.iso(now - dt.timedelta(hours=h)),))
        mints = list(dict.fromkeys(r["mint"] for r in rows))
        for i in range(0, len(mints), 30):
            chunk = mints[i:i + 30]
            pairs = await S.dex_tokens(chunk)
            for r in rows:
                if r["mint"] not in chunk: continue
                v = best_pair(pairs, r["mint"])
                pr = v["price"] if v else None
                lq = v["liquidity"] if v else None
                mult = (pr / r["price"]) if (pr and r["price"]) else None
                db.x(f"UPDATE shadow SET {p}=?, {l}=?, {x}=?, {t}=? WHERE id=?", (pr, lq, mult, util.iso(), r["id"]))
                done += 1
    keep = config.get("desk.shadow_keep_days")
    db.x("DELETE FROM shadow WHERE ts<?", (util.iso(now - dt.timedelta(days=keep)),))
    return done

def backfill(hours: float = 24) -> int:
    """one-time seed when the table is empty: rejections already in decisions (last `hours`), price = last price the desk
    stored at or before the rejection. Rows keep their original time, so their +6h/+24h re-reads come due normally."""
    if db.one("SELECT 1 FROM shadow LIMIT 1"):
        return 0
    from .agents.auditor import LAYERS
    n = 0
    for d in db.q("SELECT * FROM decisions WHERE ok=0 AND ts>=? AND mint IS NOT NULL ORDER BY id",
                  (util.iso(util.now() - dt.timedelta(hours=hours)),)):
        st, t = d["agent"], re.sub(r"\s*\[[^\]]*\]$", "", d["text"] or "")
        rule = None
        if st == "scanner":
            t = t.split(": ", 1)[-1]
        elif st == "auditor":
            mm = re.search(r"\(layer (\d)\)", t)
            rule = f"auditor: {LAYERS[int(mm.group(1))]}" if mm else None
            t = re.sub(r"^Rejected · |\s*\(layer \d\)$", "", t)
        elif st == "analyst":
            t = t.split(" · ", 1)[-1].split(", ")[0]
            w = t.split()[0] if t else ""
            rule = "analyst: " + (w if w in ("alive_6h", "organic", "chase", "score") else t)
        elif st == "executor":
            t = t.replace("Skipped · ", "")
        else:
            continue
        if is_noise(d["mint"]) or db.one("SELECT 1 FROM shadow WHERE mint=? AND stage=?", (d["mint"], st)):
            continue
        p = db.one("SELECT price FROM prices WHERE mint=? AND ts<=? AND price IS NOT NULL ORDER BY ts DESC LIMIT 1", (d["mint"], d["ts"]))
        lq = db.one("SELECT liquidity_usd l FROM scans WHERE mint=? AND ts<=? AND liquidity_usd IS NOT NULL ORDER BY id DESC LIMIT 1",
                    (d["mint"], d["ts"]))
        c = db.coin(d["mint"]) or {}
        db.insert("shadow", mint=d["mint"], ts=d["ts"], stage=st, rule=rule or rule_of(st, t), reason=t[:120],
                  price=p["price"] if p else None, liq=lq["l"] if lq else None, source=c.get("source") or "fresh", tags=None)
        n += 1
    return n

async def loop():
    await asyncio.sleep(20)
    try:
        n = backfill()
        if n: L.info("shadow: backfilled %d rejections from decisions", n)
    except Exception as e:
        L.warning("shadow backfill: %s", e)
    while True:
        try:
            if config.get("desk.shadow_on"):
                n = await check_once()
                if n: L.info("shadow: %d re-reads", n)
        except S.RateLimited as e:
            L.warning("shadow 429 %s", e); await asyncio.sleep(60)
        except Exception as e:
            L.exception("shadow loop: %s", e)
        await asyncio.sleep(300)

SUSPECT_X, SUSPECT_LIQ = 100, 1000

def _suspect(r, x) -> bool:
    """price at rejection came from a dust pool (< $1K) or the move is > 100x: different pair/units, not a real miss."""
    return r[x] is not None and ((r["liq"] is not None and r["liq"] < SUSPECT_LIQ) or r[x] > SUSPECT_X)

def summary(since: str | None = None, top: int = 10) -> dict:
    rows = db.q("SELECT * FROM shadow WHERE ts>=? ORDER BY ts", (since or "0",))
    rules = defaultdict(lambda: {"rejected": 0, "no_price": 0, "checked_6h": 0, "x1_5_6h": 0, "x2_6h": 0, "died_6h": 0,
                                 "checked_24h": 0, "x1_5_24h": 0, "x2_24h": 0, "died_24h": 0, "gone_6h": 0, "gone_24h": 0,
                                 "suspect_6h": 0, "suspect_24h": 0})
    winners = []
    for r in rows:
        d = rules[r["rule"]]
        d["rejected"] += 1
        if not r["price"]: d["no_price"] += 1
        for h, p, l, x, t in (("6h", "p6", "l6", "x6", "t6"), ("24h", "p24", "l24", "x24", "t24")):
            if not r[t]: continue
            d[f"checked_{h}"] += 1
            if r[p] is None and r[l] is None:
                d[f"gone_{h}"] += 1
            if _suspect(r, x):
                d[f"suspect_{h}"] += 1; continue
            if r[x] is not None and (r[l] or 0) >= WIN_LIQ:
                if r[x] >= 1.5: d[f"x1_5_{h}"] += 1
                if r[x] >= 2: d[f"x2_{h}"] += 1
            if (r[x] is not None and r[x] < 0.5) or (r[l] is not None and r[l] < DEAD_LIQ) or (r[p] is None and r[l] is None):
                d[f"died_{h}"] += 1
        best = max([(r[x], r[l], h) for x, l, h in (("x6", "l6", "6h"), ("x24", "l24", "24h"))
                    if r[x] is not None and (r[l] or 0) >= WIN_LIQ and not _suspect(r, x)], default=None)
        if best and best[0] >= 1.5:
            c = db.coin(r["mint"]) or {}
            winners.append({"mint": r["mint"], "name": c.get("symbol") or c.get("name") or util.short(r["mint"]),
                            "link": links.coin_url(r["mint"]), "stage": r["stage"], "rule": r["rule"], "reason": r["reason"],
                            "rejected_at": r["ts"], "price": r["price"], "liq": r["liq"], "multiple": round(best[0], 2),
                            "at": best[2], "liq_then": best[1], "source": r["source"], "tags": r["tags"]})
    winners.sort(key=lambda w: -w["multiple"])
    return {"since": since, "rows": len(rows), "pending_6h": sum(1 for r in rows if not r["t6"]),
            "pending_24h": sum(1 for r in rows if not r["t24"]),
            "rules": dict(sorted(rules.items(), key=lambda kv: -kv[1]["rejected"])), "top_missed": winners[:top],
            "definitions": {"x1_5/x2": f"multiple vs rejection price, liquidity still >= ${WIN_LIQ:,}",
                            "suspect": f"rejection liquidity < ${SUSPECT_LIQ:,} or > {SUSPECT_X}x (pair/units mismatch): excluded",
                            "died": f"< 0.5x or liquidity < ${DEAD_LIQ:,} or no longer listed on DexScreener"}}

def markdown(since: str, title: str) -> list[str]:
    sm = summary(since)
    L_ = [f"\n## {title}", f"{sm['rows']} rejected coins tracked · waiting for +6h: {sm['pending_6h']} · for +24h: {sm['pending_24h']}"]
    if not sm["rules"]:
        L_.append("None yet."); return L_
    for rule, d in list(sm["rules"].items())[:20]:
        L_.append(f"- **{rule}** × {d['rejected']}: +6h ≥1.5x {d['x1_5_6h']} · ≥2x {d['x2_6h']} · died {d['died_6h']} (of {d['checked_6h']}) · "
                  f"+24h ≥1.5x {d['x1_5_24h']} · ≥2x {d['x2_24h']} · died {d['died_24h']} (of {d['checked_24h']})")
    if sm["top_missed"]:
        L_.append("Top missed winners: " + ", ".join(f"[{w['name']}]({w['link']}) {w['multiple']:g}x at {w['at']} ({w['rule']})"
                                                     for w in sm["top_missed"]))
    return L_
