#!/usr/bin/env python3
"""REJECT TRACKING (2026-10-20 research upgrade, paper/read-only). Every coin the main desk saw in a scan/judge run is
registered once per day with the gate that stopped it (scan filter, judge metric, RugCheck, dip, capacity, PICK, ...),
then its price is sampled from DexScreener (keyless, 30 pairs/call, 0 GeckoTerminal calls) at registration (t0) and at
+1h / +6h / +24h. Outcome = price/price_t0 - 1 (plus DexScreener h1/h6/h24 change and liquidity at each sample, so
liquidity pulls / rugs are visible). Feeds the per-gate false-negative report (reject_report.py / weekly review).
Files: reject_tracker.json (state), logs/reject_outcomes.jsonl (one line per finished coin). Cron: every 5 min."""
import os, sys, json, time, glob, re, datetime as dt
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
from leads import lead_id
ST = f"{DESK}/reject_tracker.json"; OUT = f"{DESK}/logs/reject_outcomes.jsonl"
HORIZONS = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600}
MAX_REG_PER_RUN, MAX_AGE_REG_S = 400, 15 * 60   # only register decisions <= 15 min old (t0 price must be ~decision time)

def gate_of(reason):
    r = (reason or "").lower()
    if not r: return "pass"
    if r.startswith("passes all") or r.startswith("passed gates"): return "pass:not_picked"
    m = re.match(r"(judge(?: \(watchlist\))?|rugcheck|watchlist|scan): *([a-z/ _0-9]+?)(?:[ 0-9+\-.$%x<>=(]|$)", r)
    if m: return f"{m.group(1).split()[0]}:{m.group(2).strip()}"
    for k in ("max ", "overall max", "already held", "cooldown", "bonding curve", "not judged", "daily drawdown", "dial", "rugcheck unavailable"):
        if k in r: return "block:" + k.strip()
    return "other:" + r[:30]

def load():
    try: return json.load(open(ST))
    except (FileNotFoundError, ValueError): return {"coins": {}, "seen_runs": {}}

def ds_pairs(pools):
    import requests
    out = {}
    for i in range(0, len(pools), 30):
        try:
            r = requests.get("https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(pools[i:i + 30]), timeout=10)
            for p in (r.json().get("pairs") or []): out[p["pairAddress"]] = p
        except Exception: pass
        time.sleep(0.3)
    return out

def snap(p):
    if not p: return {"price": None}
    return {"price": float(p.get("priceUsd") or 0) or None, "liq": (p.get("liquidity") or {}).get("usd"), "mcap": p.get("marketCap"),
            "pc": {k: (p.get("priceChange") or {}).get(k) for k in ("h1", "h6", "h24")}}

NFS = f"{DESK}/scan/narrative_first_seen.json"
def narrative_first_seen():
    """(e) narrative timing: first time each trend term appeared in scan/narratives_trending.json (file is overwritten hourly)."""
    try: d = json.load(open(f"{DESK}/scan/narratives_trending.json"))
    except Exception: return
    try: fs = json.load(open(NFS))
    except (FileNotFoundError, ValueError): fs = {}
    for t in d.get("topics") or []:
        k = str(t.get("term", "")).strip().lower()
        if k and k not in fs: fs[k] = {"first_seen": d.get("updated_at"), "source": t.get("source"), "weight": t.get("weight")}
    tmp = NFS + ".tmp"; json.dump(fs, open(tmp, "w"), indent=0); os.replace(tmp, NFS)

def main():
    narrative_first_seen()
    st = load(); now = time.time(); coins = st["coins"]; seen = st["seen_runs"]; new = []
    for f in sorted(glob.glob(f"{DESK}/scan/rejects-*.jsonl"))[-2:]:
        for l in open(f):
            try: r = json.loads(l)
            except ValueError: continue
            rid = f"{r.get('type')}|{r.get('run_id')}"
            if rid in seen: continue
            seen[rid] = now
            at = r.get("at") or r.get("scanned_at")
            try: ts = dt.datetime.fromisoformat(at).timestamp()
            except Exception: continue
            if now - ts > MAX_AGE_REG_S: continue
            rows = []
            if r["type"] == "scan":
                rows = [(x, "scan:" + gate_of("judge: " + (x.get("fails") or ["?"])[0]).split(":", 1)[1]) for x in r.get("rejects") or []]
                rows += [(x, "scan:pass") for x in r.get("passed_candidates") or []]
            elif r["type"] == "judge":
                rows = [(x, "PICK" if x.get("decision") == "PICK" else gate_of(x.get("reason"))) for x in r.get("decisions") or [] if x.get("pool")]
            for x, g in rows:
                key = f"{x['pool']}|{time.strftime('%Y%m%d', time.localtime(ts))}"
                c = coins.get(key)
                if c is None:
                    if len(new) >= MAX_REG_PER_RUN: continue
                    c = coins[key] = {"lead": x.get("lead"), "pool": x["pool"], "name": x.get("name"), "venue": x.get("venue"), "t0": ts,
                                      "gates": [], "samples": {}}
                    new.append(key)
                if g not in c["gates"] and not (g == "scan:pass" and c["gates"]): c["gates"].append(g)
                if g != "scan:pass" and "scan:pass" in c["gates"]: c["gates"].remove("scan:pass")
                if x.get("reason") and not c.get("reason"): c["reason"] = x["reason"][:200]
    due = [k for k, c in coins.items() if "t0" not in c["samples"]] + \
          [k for k, c in coins.items() for h, s in HORIZONS.items() if h not in c["samples"] and now - c["t0"] >= s]
    pools = sorted({coins[k]["pool"] for k in due})
    px = ds_pairs(pools) if pools else {}
    for k in set(due):
        c = coins[k]; s = snap(px.get(c["pool"])); s["at"] = round(now)
        if "t0" not in c["samples"]: c["samples"]["t0"] = s; continue
        for h, sec in HORIZONS.items():
            if h not in c["samples"] and now - c["t0"] >= sec: c["samples"][h] = s
    done = [k for k, c in coins.items() if all(h in c["samples"] for h in HORIZONS)]
    with open(OUT, "a") as f:
        for k in done:
            c = coins.pop(k); p0 = (c["samples"].get("t0") or {}).get("price")
            c["ret"] = {h: (round(c["samples"][h]["price"] / p0 - 1, 4) if p0 and c["samples"][h].get("price") else None) for h in HORIZONS}
            f.write(json.dumps(c, separators=(",", ":")) + "\n")
    st["seen_runs"] = {k: v for k, v in seen.items() if now - v < 3 * 86400}
    tmp = ST + ".tmp"; json.dump(st, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, ST)
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} reject_tracker: +{len(new)} registered, {len(pools)} priced, {len(done)} finished, {len(coins)} tracking")

if __name__ == "__main__":
    main()
