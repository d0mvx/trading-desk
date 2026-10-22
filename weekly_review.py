#!/usr/bin/env python3
"""WEEKLY REVIEW (2026-10-20 research upgrade). Cron: Sundays 20:00 Berlin (or `weekly_review.py [days]` any time).
Read-only over the desk's own logs; writes reviews/weekly_<date>.md + reviews/weekly_latest.html (shown on the dashboard).
Sections: real + shadow + control trades -> win rate and avg R by Berlin entry hour, curve phase, narrative age;
per-gate cost (shadow P&L of single-gate blocks) and reject outcomes (+1h/+6h/+24h, false-negative rate);
the rule that cost the most; 1 rule to add / 1 to cut (only with n >= MIN_N, else 'none - insufficient data');
turnover, filter health, overrides; monthly routine audit (first Sunday of a month: risk-rule tests)."""
import os, sys, json, glob, html, subprocess, statistics as stt, datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo
DESK = os.path.expanduser("~/.desk"); BER = ZoneInfo("Europe/Berlin")
MIN_N, FN_HIT = 10, 0.50          # a gate verdict needs >= 10 trades; false negative = rejected coin up >= +50% at +6h
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
NOW = dt.datetime.now(BER); T0 = NOW - dt.timedelta(days=DAYS)

def ts(x):
    try: d = dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")); return d if d.tzinfo else d.replace(tzinfo=BER)
    except Exception: return None
def js(p, d=None):
    try: return json.load(open(p))
    except Exception: return d

# ---- trades: real (grouped from per-sell closes), shadow, control ----
real = defaultdict(lambda: {"pnl": 0.0})
for c in (js(f"{DESK}/meme_positions.json", {}) or {}).get("closed", []):
    k = (c["pool"] if not c.get("pool_original") else c["pool_original"], c["entry_time"]); r = real[k]
    r.update({"src": "real", "sleeve": c.get("sleeve", "main"), "venue": c.get("venue"), "entry": ts(c["entry_time"]), "name": c["name"],
              "cost": c.get("cost_usd_initial") or r.get("cost") or 0, "sl": c.get("stop_loss") or 0.2, "narr": c.get("narrative"), "lead": c.get("lead")})
    r["pnl"] += c.get("pnl") or 0; r.setdefault("costs", []).append(c.get("cost_usd") or 0); r["reason"] = c.get("exit_reason")
trades = []
for r in real.values():
    r["cost"] = sum(r.pop("costs", [])) or r["cost"]; trades.append(r)
sh = js(f"{DESK}/shadow_positions.json", {}) or {}
for c in sh.get("closed", []):
    trades.append({"src": "control" if c["cat"].startswith("control:") else "shadow", "cat": c["cat"], "sleeve": c.get("sleeve", "main"),
                   "venue": c.get("venue"), "entry": ts(c["entry_time"]), "name": c["name"], "cost": c.get("cost_usd") or 0,
                   "sl": 0.30 if c.get("venue") == "bonding_curve" else 0.20, "pnl": c.get("pnl") or 0, "reason": c.get("reason")})
trades = [t for t in trades if t["entry"] and t["entry"] >= T0]
for t in trades: t["R"] = t["pnl"] / max(t["cost"] * t["sl"], 1e-9)

nfs = js(f"{DESK}/scan/narrative_first_seen.json", {}) or {}
def narr_age(t):
    ages = [(t["entry"] - ts(nfs[m.lower()]["first_seen"])).total_seconds() / 60 for m in (t.get("narr") or []) if m and m.lower() in nfs and ts(nfs[m.lower()]["first_seen"])]
    if not ages: return "n/a (static term / not logged)"
    a = min(ages); return "<20m" if a < 20 else "20-40m" if a < 40 else "40-120m" if a < 120 else ">2h"
def phase(t): return "bonding curve" if t.get("venue") == "bonding_curve" else "PumpSwap (graduated)"

def table(rows, key, title):
    g = defaultdict(list)
    for t in rows: g[key(t)].append(t)
    out = [f"| {title} | n | win | avg R | P&L $ |", "|---|---|---|---|---|"]
    for k in sorted(g, key=str):
        v = g[k]; w = sum(t["pnl"] > 0 for t in v) / len(v)
        out.append(f"| {k} | {len(v)} | {w:.0%} | {stt.mean(t['R'] for t in v):+.2f} | {sum(t['pnl'] for t in v):+.2f} |")
    return "\n".join(out) if g else f"_no {title.lower()} data in window_"

md = [f"# Weekly review — {NOW:%Y-%m-%d %H:%M} Berlin (last {DAYS} days, since {T0:%a %d %b %H:%M})", "",
      "Paper only. R = P&L / (ticket x hard-stop %). Shadow = virtual trades the desk did not take; control = baseline bots (top / random scan passer, no judge gates)."]
for src in ("real", "shadow", "control"):
    v = [t for t in trades if t["src"] == src]
    if v: md.append(f"- **{src}**: {len(v)} trades, win {sum(t['pnl'] > 0 for t in v)/len(v):.0%}, avg R {stt.mean(t['R'] for t in v):+.2f}, P&L {sum(t['pnl'] for t in v):+.2f}")
    else: md.append(f"- **{src}**: no closed trades in window")
R = [t for t in trades if t["src"] == "real"]
md += ["", "## Real trades by Berlin entry hour", table(R, lambda t: f"{t['entry'].astimezone(BER).hour:02d}h", "Hour"),
       "", "## Real trades by curve phase", table(R, phase, "Phase"),
       "", "## Real + shadow new pairs by narrative age at entry", table([t for t in trades if t["sleeve"] == "newpairs" and t["src"] != "control"], narr_age, "Narrative age"),
       "", "## Shadow + control by category", table([t for t in trades if t["src"] != "real"], lambda t: t["cat"], "Category")]

# ---- per-gate cost: shadow single-gate blocks; reject outcomes ----
gate = defaultdict(list)
for t in trades:
    if t["src"] == "shadow" and ":gate:" in t.get("cat", ""): gate[t["cat"].split(":gate:", 1)[1]].append(t)
ro = []
for l in open(f"{DESK}/logs/reject_outcomes.jsonl") if os.path.exists(f"{DESK}/logs/reject_outcomes.jsonl") else []:
    try: r = json.loads(l)
    except ValueError: continue
    if dt.datetime.fromtimestamp(r["t0"], BER) >= T0: ro.append(r)
rg = defaultdict(list)
for r in ro:
    for g in r["gates"]: rg[g].append(r)
md += ["", "## Gates: shadow cost (single-gate blocks) and reject outcomes",
       "| Gate | shadow n | shadow P&L $ | rejects n | median +1h | median +6h | median +24h | FN rate (+6h >= +50%) |", "|---|---|---|---|---|---|---|---|"]
def med(v): v = [x for x in v if x is not None]; return f"{stt.median(v):+.0%}" if v else "—"
for g in sorted(set(gate) | set(rg), key=lambda g: -sum(t["pnl"] for t in gate.get(g, []))):
    s = gate.get(g, []); r = rg.get(g, []); r6 = [x["ret"]["6h"] for x in r if x["ret"].get("6h") is not None]
    md.append(f"| {g} | {len(s)} | {sum(t['pnl'] for t in s):+.2f} | {len(r)} | {med([x['ret']['1h'] for x in r])} | {med(r6)} | {med([x['ret']['24h'] for x in r])} | "
              + (f"{sum(x >= FN_HIT for x in r6)/len(r6):.0%}" if r6 else "—") + " |")
elig = {g: v for g, v in gate.items() if len(v) >= MIN_N}
cost = max(elig.items(), key=lambda kv: sum(t["pnl"] for t in kv[1]), default=None)
md += ["", "## Verdicts"]
if cost and sum(t["pnl"] for t in cost[1]) > 0:
    v = cost[1]; md.append(f"- **Rule that cost the most:** `{cost[0]}` — its {len(v)} blocked coins made {sum(t['pnl'] for t in v):+.2f} $ in the shadow book (win {sum(t['pnl']>0 for t in v)/len(v):.0%}, avg R {stt.mean(t['R'] for t in v):+.2f}).")
    md.append(f"- **1 rule to cut (candidate, needs holdout confirmation before any change):** `{cost[0]}` (same numbers).")
else:
    md.append(f"- **Rule that cost the most / rule to cut:** none — no gate has >= {MIN_N} shadow trades with positive P&L this window (gates paid for themselves or n too small).")
cand = js(f"{DESK}/reviews/research_candidates.json", []) or []
best = max([c for c in cand if c.get("holdout_pass")], key=lambda c: c.get("holdout_gain", 0), default=None)
md.append(f"- **1 rule to add:** " + (f"`{best['rule']}` — holdout {best.get('holdout_metric')}: {best.get('holdout_gain'):+.2f} vs baseline (train {best.get('train_gain', 0):+.2f}, {best.get('params', '?')} params)." if best
                                     else "none — no researched candidate has passed the walk-forward holdout yet (see CHANGELOG_research.md)."))
ctl = [t for t in trades if t["src"] == "control"]
if ctl and R:
    md.append(f"- **Gates vs control bot:** real avg R {stt.mean(t['R'] for t in R):+.2f} (n={len(R)}) vs control avg R {stt.mean(t['R'] for t in ctl):+.2f} (n={len(ctl)})"
              + (" -> gates beat the baseline." if stt.mean(t['R'] for t in R) > stt.mean(t['R'] for t in ctl) else " -> gates do NOT beat the baseline yet."))

# ---- ops ----
rej = defaultdict(int); runs = 0
for f in glob.glob(f"{DESK}/scan/rejects-*.jsonl"):
    for l in open(f):
        try: r = json.loads(l)
        except ValueError: continue
        d = ts(r.get("scanned_at") or r.get("at"))
        if r.get("type") == "scan" and d and d >= T0: rej[d.date().isoformat()] += r.get("rejected_total") or 0; runs += 1
low = [d for d, n in rej.items() if n < 10]
md += ["", "## Ops", f"- Turnover: {len(R)} real round trips ({sum(t['cost'] for t in R):.2f} $ bought), {len([t for t in trades if t['src']=='shadow'])} shadow, {len(ctl)} control.",
       f"- Filter health: {runs} scan runs; rejects/day " + ", ".join(f"{d} {n}" for d, n in sorted(rej.items())) + (f" — **ALARM: < 10 rejects on {low} (filters may be broken)**" if low else " — ok"),
       f"- Overrides (manual edits of risk files / STOP flag): " + ("STOP_ALL flag present" if os.path.exists(f"{DESK}/STOP_ALL") else "none flagged")]
if NOW.day <= 7 or "--audit" in sys.argv:
    try: r = subprocess.run([f"{DESK}/tests/run_all.sh"], capture_output=True, text=True, timeout=300); last = (r.stderr.strip().splitlines() or ["?"])[-1]
    except Exception as e: last = f"could not run: {e}"
    md += ["", "## Monthly routine audit", f"- Risk-rule enforcement tests (tests/run_all.sh): **{last}**",
           "- Checklist: backups present for every CHANGELOG entry; crontab matches the last backup; no live-money keys; kill switch state file readable."]
txt = "\n".join(md) + "\n"
os.makedirs(f"{DESK}/reviews", exist_ok=True)
open(f"{DESK}/reviews/weekly_{NOW:%Y-%m-%d}.md", "w").write(txt)
h = "<pre class='review'>" + html.escape(txt) + "</pre>"
tmp = f"{DESK}/reviews/.weekly_latest.html.tmp"; open(tmp, "w").write(h); os.replace(tmp, f"{DESK}/reviews/weekly_latest.html")
print(f"wrote reviews/weekly_{NOW:%Y-%m-%d}.md ({len(trades)} trades in window)")
