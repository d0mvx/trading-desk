"""Analyst (PART 5): state -> Jev 4 noul questions -> code gate. Rules mode computes the same 4 names in code.
A Jev error in jev mode never falls back silently."""
from __future__ import annotations
import asyncio, hashlib, json, os, time, httpx
from .. import db, util, config, bus, log, fields as F, sources as S, chain

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

def build_state(name, age_min, v: dict, audit: dict, max_chars=3000) -> str:
    dev = (audit.get(3) or "n/a").split("%")[0]
    st = (f"Coin {name} on Solana, graduated {age_min:.0f} min ago. Liquidity ${_n(v['liquidity'])}. Market cap ${_n(v['mcap'])}.\n"
          f"Last 5 min: {_n(v['buys_m5'], '{}')} buys, {_n(v['sells_m5'], '{}')} sells, volume ${_n(v['vol_m5'])}, price {_n(v['ch_m5'], '{:g}')}%.\n"
          f"Last 1h: {_n(v['buys_h1'], '{}')} buys, {_n(v['sells_h1'], '{}')} sells, volume ${_n(v['vol_h1'])}, price {_n(v['ch_h1'], '{:g}')}%.\n"
          f"Top 10 hold {(audit.get(4) or 'n/a').rstrip('%')}%. Dev holds {dev}%, sold 0. LP {audit.get(5) or 'n/a'}. "
          f"Bundled {audit.get(7) or 'n/a'}. Delegations {audit.get(8) or 'n/a'}.")
    return st[:max_chars]

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
    if db.one("SELECT 1 FROM verdicts WHERE mint=? AND ts>=?", (m, util.iso(util.night_start(s["desk.report_time"])))):
        L.info("already scored %s tonight, not re-asking", m)
        return {"skip": True}
    pools = [coin.get("pool")] if coin.get("pool") else []
    v = chain.pair_view((await S.dex_pairs(pools)).get(coin.get("pool"))) if pools else None
    if not v or v["price"] is None:
        out = {"agent": "analyst", "mint": m, "answers": None, "score": 0, "passed": False, "failed": ["no price"], "model": None, "inputTokens": 0}
        _record(m, name, out, None); return out
    db.price(m, v["price"], v["vol_m5"])
    audit = audit_values(m)
    age = (time.time() * 1000 - v["created_ms"]) / 60000 if v["created_ms"] else 0
    state = build_state(coin.get("name") or name, age, v, audit, s["analyst.max_state_chars"])
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
           "model": model, "inputTokens": tokens, "price": v["price"], "state_hash": shash, "mode": mode}
    L.info("mint=%s state=%s answers=%s score=%s verdict=%s tokens=%s", m, shash, a, score, "pass" if passed else "reject", tokens)
    _record(m, name, out, v)
    return out

def _record(m, name, out, v):
    a = out["answers"] or {}
    label = "Analyst (rules)" if out.get("model") == "rules" else "Analyst"
    db.x("INSERT INTO verdicts(mint,ts,alive_6h,organic,flush,chase,score,pass,reason,input_tokens) VALUES(?,?,?,?,?,?,?,?,?,?)",
         (m, util.iso(), a.get("alive_6h"), a.get("organic"), a.get("flush"), a.get("chase"), out["score"],
          1 if out["passed"] else 0, "; ".join(out["failed"]) or None, out["inputTokens"]))
    bus.emit("verdict", {"mint": m, "name": name, "score": out["score"], "pass": out["passed"], "failed": out["failed"], "answers": a})
    if out["passed"]:
        db.decide(NAME, m, name, f"Score {out['score']} · pass", True)
    else:
        db.activity("rejected", m, label, f"Rejected {name}", f"{label} · {out['failed'][0]}", "Skipped")
        db.decide(NAME, m, name, f"Score {out['score']} · {', '.join(out['failed'])}", False)

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
