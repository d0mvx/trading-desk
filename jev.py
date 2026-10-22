"""JEV (TypeSafe AI 'System One' model) as an OPTIONAL meme Judge tie-breaker.
Official: https://typesafe.ai  docs https://docs.typesafe.ai  API POST https://api.typesafe.ai/v1/systemone
(Bearer key from https://console.typesafe.ai -> API Keys; $0.042 per 1M input tokens, output free; no free credits).
INACTIVE until a key exists: env JEV_API_KEY or TYPESAFE_API_KEY, or a line JEV_API_KEY=... in ~/.desk/jev.env (chmod 600).
Jev never bypasses the hard gates: it only CHOOSES among candidates that already passed the rule-based Judge
(buyers/flow/price gates) AND the RugCheck gates. One request per pipeline run, only when >= 1 candidate passed.
Answers used: choice 'pick' (one of cand_N or 'none') + noul 'cont_N' per candidate. Buy only if
pick != none, choice confidence >= JEV_MIN_CONF and noul(cont_pick) >= JEV_MIN_NOUL; otherwise no buy.
On API error: JEV_FAIL=rule (default) -> fall back to the rule-based pick (first passer in rank order); JEV_FAIL=skip -> no buy.
Keys are never logged or printed."""
import os, json, time, datetime as dt
DESK = os.path.expanduser("~/.desk"); ENVF = f"{DESK}/jev.env"; LOG = f"{DESK}/logs/jev.log"
PRICE_PER_MTOK = 0.042

def _conf():
    c = {"JEV_BASE_URL": "https://api.typesafe.ai", "JEV_MODEL": "jev-1.13.0", "JEV_MIN_CONF": "0.50", "JEV_MIN_NOUL": "0.55",
         "JEV_FAIL": "rule", "JEV_MAX_CANDS": "3", "JEV_TIMEOUT": "8"}
    if os.path.exists(ENVF):
        for l in open(ENVF):
            l = l.strip()
            if l and not l.startswith("#") and "=" in l:
                k, v = l.split("=", 1); c[k.strip().removeprefix("export ").strip()] = v.strip().strip('"\'')
    for k in list(c) + ["JEV_API_KEY", "TYPESAFE_API_KEY"]:
        if os.environ.get(k): c[k] = os.environ[k]
    c["key"] = c.get("JEV_API_KEY") or c.get("TYPESAFE_API_KEY") or ""
    return c

def active(): return bool(_conf()["key"])
def max_cands(): return int(_conf()["JEV_MAX_CANDS"])
def fail_mode(): return _conf()["JEV_FAIL"]

class JevError(RuntimeError): pass

def _log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f: f.write(json.dumps({"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), **rec}) + "\n")

def build_request(cands, model):
    st = {"task": "Solana memecoin paper-trading desk. Each candidate already passed hard safety gates (RugCheck: no mint/freeze "
                  "authority, LP locked, holder concentration limits) and flow gates. Exits: stop -20%, trailing -25%, half at +50%, 60 min time stop.",
          "candidates": {}}
    for i, c in enumerate(cands, 1):
        h1, m15 = c.get("tx_h1") or {}, c.get("tx_m15") or {}
        st["candidates"][f"cand_{i}"] = {"name": c.get("name"), "venue": c.get("venue"), "pool_age_hours": c.get("age_h"),
            "market_cap_usd": round(c.get("mcap_usd") or 0), "liquidity_usd": round(c.get("liquidity_usd") or 0),
            "volume_usd_h6": round(c.get("vol_h6") or 0), "volume_usd_h24": round(c.get("vol_h24") or 0),
            "price_change_h1_pct": c.get("pc_h1"), "unique_buyers_h1": h1.get("buyers"), "unique_buyers_h6": c.get("buyers_h6"),
            "buys_h1": h1.get("buys"), "sells_h1": h1.get("sells"), "buys_m15": m15.get("buys"), "sells_m15": m15.get("sells"),
            "rank_score": c.get("score"), "rugcheck_score_normalised": c.get("_rc_score")}
    crit = {f"cand_{i}": f"{c.get('name')}: the best short-term momentum entry of this set" for i, c in enumerate(cands, 1)}
    crit["none"] = "None of these is a good entry right now (momentum looks exhausted, wash-traded or too risky)"
    q = {"pick": {"type": "choice", "instructions": "Which candidate (if any) should the desk buy now for a hold of at most 60 minutes?", "criteria": crit}}
    for i, c in enumerate(cands, 1):
        q[f"cont_{i}"] = {"type": "noul", "instructions": f"Over the next 60 minutes, cand_{i} ({c.get('name')}) is more likely to rise "
                                                           f"by +50% than to fall by -20%."}
    return {"model": model, "state": st, "questions": q}

def choose(cands):
    """Returns (index or None, info dict). Raises JevError on transport/API failure."""
    import requests
    c = _conf()
    if not c["key"]: raise JevError("no key")
    body = build_request(cands, c["JEV_MODEL"]); t0 = time.time()
    try:
        r = requests.post(c["JEV_BASE_URL"].rstrip("/") + "/v1/systemone", json=body, timeout=float(c["JEV_TIMEOUT"]),
                          headers={"Authorization": f"Bearer {c['key']}", "Content-Type": "application/json"})
    except Exception as e:
        _log({"ok": False, "error": type(e).__name__}); raise JevError(type(e).__name__)
    if r.status_code != 200:
        _log({"ok": False, "status": r.status_code, "body": r.text[:200]}); raise JevError(f"HTTP {r.status_code}")
    d = r.json(); a = d.get("answers") or {}; u = d.get("usage") or {}
    pick = a.get("pick") or {}; ch, conf = pick.get("choice"), float(pick.get("confidence") or 0)
    nouls = {k: (a.get(k) or {}).get("noul") for k in a if k.startswith("cont_")}
    info = {"model": d.get("model"), "choice": ch, "confidence": conf, "probabilities": pick.get("probabilities"), "nouls": nouls,
            "input_tokens": u.get("input_tokens"), "cost_usd": round((u.get("input_tokens") or 0) / 1e6 * PRICE_PER_MTOK, 8),
            "latency_s": round(time.time() - t0, 2), "candidates": [x.get("name") for x in cands]}
    idx = None
    if ch and ch != "none" and ch.startswith("cand_"):
        n = int(ch.split("_")[1]); nv = nouls.get(f"cont_{n}")
        if conf >= float(c["JEV_MIN_CONF"]) and nv is not None and nv >= float(c["JEV_MIN_NOUL"]): idx = n - 1
        else: info["declined"] = f"conf {conf:.2f} / noul {nv} below thresholds {c['JEV_MIN_CONF']}/{c['JEV_MIN_NOUL']}"
    _log({"ok": True, **info, "picked": idx})
    return idx, info

if __name__ == "__main__":
    import sys
    print(json.dumps({"active": active(), "model": _conf()["JEV_MODEL"], "endpoint": _conf()["JEV_BASE_URL"] + "/v1/systemone"}, indent=1))
    if "--example" in sys.argv:
        ex = [{"name": "EXAMPLE / SOL", "venue": "pumpswap", "age_h": 3.2, "mcap_usd": 250000, "liquidity_usd": 40000, "vol_h6": 300000,
               "vol_h24": 300000, "pc_h1": 35.0, "tx_h1": {"buyers": 120, "buys": 400, "sells": 300}, "tx_m15": {"buys": 90, "sells": 60}, "buyers_h6": 300, "score": 0.4}]
        print(json.dumps(build_request(ex, _conf()["JEV_MODEL"]), indent=1)[:1500])
