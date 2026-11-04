"""Analyst (PART 5): state -> Jev 4 noul questions -> code gate. Rules mode computes the same 4 names in code.
A Jev error in jev mode never falls back silently."""
from __future__ import annotations
import asyncio, hashlib, json, os, time, httpx
from .. import db, util, config, bus, log, fields as F, sources as S, chain, shadow, tags as T

L = log.get("analyst")
NAME = "analyst"
URL = "https://api.typesafe.ai/v1/systemone"
QUESTIONS = {
    "alive_6h": {"type": "noul", "instructions": "This coin is still actively traded 6 hours from now"},
    "organic": {"type": "noul", "instructions": "Most buyers in the last 30 minutes are separate real wallets"},
    "flush": {"type": "noul", "instructions": "Price just flushed down and buyers are absorbing it"},
    "chase": {"type": "noul", "instructions": "This entry is chasing a green candle that already ran"},
}
NAMES = list(QUESTIONS)

class NoAnswer(Exception): pass
class BadAnswer(Exception): pass

def _n(x, fmt="{:,.0f}"):
    return "n/a" if x is None else fmt.format(x)

def audit_values(mint) -> dict:
    rows = db.q("SELECT layer, value_text FROM audits WHERE mint=? ORDER BY id DESC LIMIT 8", (mint,))
    return {r["layer"]: r["value_text"] for r in rows}

def build_state(name, age_min, v: dict, audit: dict, max_chars=3000, extra: dict | None = None) -> str:
    dev = (audit.get(3) or "n/a").split("%")[0]
    ago = f"{age_min / 1440:.1f} days" if age_min >= 2880 else f"{age_min:.0f} min"
    st = (f"Coin {name} on Solana, graduated {ago} ago. Liquidity ${_n(v['liquidity'])}. Market cap ${_n(v['mcap'])}.\n"
          f"Last 5 min: {_n(v['buys_m5'], '{}')} buys, {_n(v['sells_m5'], '{}')} sells, volume ${_n(v['vol_m5'])}, price {_n(v['ch_m5'], '{:g}')}%.\n"
          f"Last 1h: {_n(v['buys_h1'], '{}')} buys, {_n(v['sells_h1'], '{}')} sells, volume ${_n(v['vol_h1'])}, price {_n(v['ch_h1'], '{:g}')}%.\n"
          f"Top 10 hold {(audit.get(4) or 'n/a').rstrip('%')}%. Dev holds {dev}%, sold 0. LP {audit.get(5) or 'n/a'}. "
          f"Bundled {audit.get(7) or 'n/a'}. Delegations {audit.get(8) or 'n/a'}.")
    if extra:
        st += "\n" + extra_text(extra)
    return st[:max_chars]

def extra_text(e: dict) -> str:
    h = e.get("holders") or {}
    tx = e.get("txns") or {}
    mk = e.get("makers") or {}
    lines = []
    if h.get("now") is not None or h.get("at_scan") is not None:
        ch = (f", {h['now'] - h['at_scan']:+,} in {h['minutes']:.0f} min" if h.get("now") is not None and h.get("at_scan") is not None
              and h.get("minutes") else "")
        lines.append(f"Holders {_n(h.get('now'))} now (at scanner {_n(h.get('at_scan'))}{ch}).")
    parts = [f"{w} {_n(tx.get('buys_' + w), '{}')} buys / {_n(tx.get('sells_' + w), '{}')} sells" for w in ("m5", "h1", "h6", "h24")
             if tx.get("buys_" + w) is not None]
    if parts: lines.append("Trades: " + ", ".join(parts) + ".")
    parts = [f"{w} {_n(mk.get('buyers_' + w), '{}')} buyers / {_n(mk.get('sellers_' + w), '{}')} sellers" for w in ("m5", "h1", "h24")
             if mk.get("buyers_" + w) is not None]
    if parts: lines.append("Unique wallets: " + ", ".join(parts) + ".")
    ages = [a for a in (e.get("top_wallet_age_days") or []) if a.get("days") is not None]
    if ages:
        lines.append("Top holder wallet ages (oldest of last 1000 tx): " +
                     ", ".join(f"{a['pct']:.1f}% holder {'>=' if a['capped'] else ''}{a['days']:.1f}d" for a in ages) + ".")
    return "\n".join(lines)

async def gather_extra(m: str, coin: dict, v: dict, item: dict) -> dict:
    """extra, sourced inputs for Jev (analyst.extra_data_on). Every field null when its source has no data.
    holders: RugCheck totalHolders at scanner vs now. txns: DexScreener buys/sells. makers: GeckoTerminal unique
    buyers/sellers. top_wallet_age_days: top 5 non-pool holders' owners, Helius getSignaturesForAddress (1 call each)."""
    e = {"holders": None, "txns": {k: v.get(k) for k in ("buys_m5", "sells_m5", "buys_h1", "sells_h1",
                                                          "buys_h6", "sells_h6", "buys_h24", "sells_h24")},
         "makers": None, "top_wallet_age_days": None}
    rep0 = item.get("report") or {}
    try:
        rep = await S.rug_report(m)
        at_scan = F.read(rep0, F.RUGCHECK_REPORT, "total_holders")
        now_h = F.read(rep, F.RUGCHECK_REPORT, "total_holders")
        mins = (time.time() - item["scan_t"]) / 60 if item.get("scan_t") else None
        e["holders"] = {"at_scan": at_scan, "now": now_h, "minutes": mins}
    except Exception as ex:
        rep = rep0; L.info("extra holders %s: %s", m, ex)
    try:
        if coin.get("pool"):
            g = await S.gt_pool(coin["pool"])
            if g:
                e["makers"] = {k: F.read(g, F.GECKO_POOL, k) for k in ("buyers_m5", "sellers_m5", "buyers_h1", "sellers_h1",
                                                                         "buyers_h24", "sellers_h24")}
    except Exception as ex:
        L.info("extra makers %s: %s", m, ex)
    try:
        excl = chain.amm_accounts(rep, coin.get("pool"))
        tops = [h for h in (F.read(rep, F.RUGCHECK_REPORT, "top_holders") or [])
                if h.get("owner") and h.get("owner") not in excl and h.get("address") not in excl][:5]
        ages = []
        for h in tops:
            try:
                d, capped = await chain.wallet_age_days(h["owner"])
            except Exception:
                d, capped = None, False
            ages.append({"owner": h["owner"], "pct": chain.fnum(h.get("pct")) or 0, "days": d, "capped": capped})
        e["top_wallet_age_days"] = ages or None
    except Exception as ex:
        L.info("extra wallet ages %s: %s", m, ex)
    return e

def gate(a: dict, s: dict) -> tuple[int, bool, list[str]]:
    score = round(100 * (a["alive_6h"] + a["organic"] + a["flush"] + (1 - a["chase"])) / 4)
    failed = []
    if a["alive_6h"] < s["analyst.min_alive_6h"]: failed.append(f"alive_6h {a['alive_6h']:.2f}")
    if a["organic"] < s["analyst.min_organic"]: failed.append(f"organic {a['organic']:.2f}")
    if a["chase"] > s["analyst.max_chase"]: failed.append(f"chase {a['chase']:.2f}")
    if score < s["analyst.min_score"]: failed.append(f"score {score}")
    return score, not failed, failed

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))

def rules(v: dict, bundled: int, s: dict) -> dict:
    alive = clamp((v["vol_h1"] or 0) / s["analyst.rules_alive_volume_h1"])
    organic = clamp((v["buys_h1"] or 0) / s["analyst.rules_organic_buys_h1"])
    if bundled >= s["analyst.rules_bundled_from"]:
        organic *= s["analyst.rules_bundled_penalty"]
    m5 = v["ch_m5"]
    if m5 is not None and m5 <= -s["analyst.rules_flush_drop_m5_pct"] and (v["buys_m5"] or 0) >= (v["sells_m5"] or 0):
        flush = 1.0
    elif m5 is not None and m5 < 0:
        flush = 0.5
    else:
        flush = 0.0
    chase = clamp((v["ch_h1"] or 0) / s["analyst.rules_chase_h1_pct"])
    return {"alive_6h": alive, "organic": organic, "flush": flush, "chase": chase}

async def ask_jev(state: str, timeout: float) -> tuple[dict, str, int, dict]:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise NoAnswer("no key")
    body = {"model": "jev-latest", "state": state, "questions": QUESTIONS}
    t_429 = time.time()
    attempt = 0
    async with httpx.AsyncClient(timeout=timeout) as c:
        while True:
            try:
                r = await c.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 429:
                    if time.time() - t_429 < 60:
                        await asyncio.sleep(3); continue
                    raise NoAnswer("429 for 60s")
                if r.status_code >= 400:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                raw = r.json()
                break
            except NoAnswer:
                raise
            except Exception as e:
                attempt += 1
                if attempt >= 2:
                    raise NoAnswer(f"{type(e).__name__}")
                await asyncio.sleep(2)
    ans = F.read(raw, F.JEV, "answers") or {}
    out = {}
    for n in NAMES:
        v = F.get(ans.get(n) or {}, F.JEV["noul"])
        if not isinstance(v, (int, float)) or not (0 <= v <= 1):
            L.warning("bad answer raw=%s", json.dumps(raw)[:2000])
            raise BadAnswer(n)
        out[n] = float(v)
    return out, F.read(raw, F.JEV, "model"), int(F.read(raw, F.JEV, "input_tokens") or 0), raw

async def analyse(item: dict) -> dict:
    m = item["mint"]
    s = config.all_settings()
    coin = db.coin(m) or {}
    name = coin.get("symbol") or coin.get("name") or util.short(m)
    if item.get("source") == "established":   # established coins come back after the cooldown, not once a night
        since = util.iso(util.now() - __import__("datetime").timedelta(hours=s["scanner.established_cooldown_h"]))
    else:
        since = util.iso(util.night_start(s["desk.report_time"]))
    if db.one("SELECT 1 FROM verdicts WHERE mint=? AND ts>=?", (m, since)):
        L.info("already scored %s recently, not re-asking", m)
        return {"skip": True}
    pools = [coin.get("pool")] if coin.get("pool") else []
    v = chain.pair_view((await S.dex_pairs(pools)).get(coin.get("pool"))) if pools else None
    if not v or v["price"] is None:
        out = {"agent": "analyst", "mint": m, "answers": None, "score": 0, "passed": False, "failed": ["no price"], "model": None, "inputTokens": 0}
        _record(m, name, out, None, item); return out
    db.price(m, v["price"], v["vol_m5"])
    audit = audit_values(m)
    age = (time.time() * 1000 - v["created_ms"]) / 60000 if v["created_ms"] else 0
    extra = None
    if s["analyst.extra_data_on"] and s["analyst.mode"] != "rules":
        extra = await gather_extra(m, coin, v, item)
    state = build_state(coin.get("name") or name, age, v, audit, s["analyst.max_state_chars"], extra)
    shash = hashlib.sha256(state.encode()).hexdigest()[:16]
    mode = s["analyst.mode"]
    try:
        if mode == "rules":
            bund_txt = audit.get(7) or "None"
            bundled = int(bund_txt.split()[0]) if bund_txt[:1].isdigit() else 0
            a, model, tokens = rules(v, bundled, s), "rules", 0
        else:
            a, model, tokens, _ = await ask_jev(state, s["analyst.timeout_s"])
        score, passed, failed = gate(a, s)
    except NoAnswer as e:
        a, model, tokens, score, passed, failed = None, None, 0, 0, False, ["no answer"]
        L.info("no answer %s: %s", m, e)
    except BadAnswer as e:
        a, model, tokens, score, passed, failed = None, None, 0, 0, False, ["bad answer"]
    out = {"agent": "analyst", "mint": m, "answers": a, "score": score, "passed": passed, "failed": failed,
           "model": model, "inputTokens": tokens, "price": v["price"], "state_hash": shash, "mode": mode, "extra": extra}
    if passed:
        if extra is not None:
            T.add(item, "jev_plus", NAME)
        if not gate(a, {**s, **{k: T.OLD[k] for k in T.OLD if k.startswith("analyst.")}})[1]:
            T.add(item, "jev_loose", NAME)     # the old gate 0.70 / 0.65 / 0.30 / 70 would have rejected it
        out["borderline"] = borderline(a, score, s)
    L.info("mint=%s state=%s answers=%s score=%s verdict=%s tokens=%s", m, shash, a, score, "pass" if passed else "reject", tokens)
    _record(m, name, out, v, item)
    return out

def _rule(f: str) -> str:
    w = f.split()[0] if f else "reject"
    return w if w in ("alive_6h", "organic", "chase", "score") else f

def borderline(a: dict, score: int, s: dict) -> list[str]:
    """why a passing verdict is borderline (Jev part; the executor adds bundled 5-6 / top10 25-30)."""
    why = []
    if score < 60: why.append(f"score {score}")
    if round(a["alive_6h"] - s["analyst.min_alive_6h"], 6) <= 0.05: why.append("alive_6h near min")
    if round(a["organic"] - s["analyst.min_organic"], 6) <= 0.05: why.append("organic near min")
    if round(s["analyst.max_chase"] - a["chase"], 6) <= 0.05: why.append("chase near max")
    if score - s["analyst.min_score"] <= 5: why.append("score near min")
    return why

def _record(m, name, out, v, item=None):
    item = item or {}
    a = out["answers"] or {}
    label = "Analyst (rules)" if out.get("model") == "rules" else "Analyst"
    db.x("INSERT INTO verdicts(mint,ts,alive_6h,organic,flush,chase,score,pass,reason,input_tokens,extra,tags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
         (m, util.iso(), a.get("alive_6h"), a.get("organic"), a.get("flush"), a.get("chase"), out["score"],
          1 if out["passed"] else 0, "; ".join(out["failed"]) or None, out["inputTokens"],
          json.dumps(out.get("extra"), separators=(",", ":")) if out.get("extra") is not None else None, T.s(T.of(item))))
    bus.emit("verdict", {"mint": m, "name": name, "score": out["score"], "pass": out["passed"], "failed": out["failed"], "answers": a})
    if out["passed"]:
        db.decide(NAME, m, name, f"Score {out['score']} · pass", True, tags=T.of(item))
    else:
        db.activity("rejected", m, label, f"Rejected {name}", f"{label} · {out['failed'][0]}", "Skipped")
        db.decide(NAME, m, name, f"Score {out['score']} · {', '.join(out['failed'])}", False, tags=T.of(item))
        shadow.record(m, NAME, out["failed"][0], v["price"] if v else None, v["liquidity"] if v else None,
                      tags=T.of(item), source=item.get("source"), rule="analyst: " + _rule(out["failed"][0]))

async def run():
    while True:
        item = await bus.to_analyst.get()
        db.heartbeat(NAME)
        while db.paused(NAME):
            await asyncio.sleep(5)
        try:
            out = await analyse(item)
            if out.get("passed"):
                item["analyst"] = out
                await bus.to_executor.put(item)
        except S.RateLimited:
            await asyncio.sleep(30); await bus.to_analyst.put(item)
        except Exception as e:
            L.exception("analyst crash %s: %s", item.get("mint"), e)
