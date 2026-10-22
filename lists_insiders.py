#!/usr/bin/env python3
"""INSIDERS list from SEC EDGAR Form 4 (free, keyless; SEC fair-access: <=10 req/s, declared User-Agent).
Rule (article): 3+ DISTINCT insiders with open-market BUYS (transaction code P, acquired) within the last 30 days,
> $500k total, NOT under a Rule 10b5-1 plan (aff10b5One checkbox or a 10b5-1 footnote on the transaction).
Crawl: EDGAR daily form index -> every Form 4 full-submission .txt (1 request per filing) -> purchase rows cached per
filing day in lists/form4/YYYYMMDD.json (each day crawled once; days missing => list status null = hold).
Symbols come only from <issuerTradingSymbol> in the filings and must be active+tradable on Alpaca (never invented).
Usage: lists_insiders.py [--crawl-only] [--max-days N]"""
import os, re, sys, json, time, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
import requests
sys.path.insert(0, os.path.expanduser("~/.desk")); import alp_common as ac
OUT = f"{ac.DESK}/lists"; CACHE = f"{OUT}/form4"; os.makedirs(CACHE, exist_ok=True)
WINDOW_D, MIN_INSIDERS, MIN_TOTAL = 30, 3, 500_000
LOOKBACK_FILING_D = 34              # filings are due 2 business days after the trade -> crawl a few extra days
RATE = 5.0                          # requests/s (SEC limit 10)
# SEC fair access requires a declared User-Agent WITH a real contact e-mail ("Name email@domain"); without one sec.gov answers
# 403 "Undeclared Automated Tool". Set SEC_USER_AGENT in ~/.desk/sec.env (run_alp.sh loads it). No contact -> list null (hold).
for _l in (open(os.path.expanduser("~/.desk/sec.env")) if os.path.exists(os.path.expanduser("~/.desk/sec.env")) else []):
    if _l.strip().startswith("SEC_USER_AGENT="): os.environ.setdefault("SEC_USER_AGENT", _l.split("=", 1)[1].strip().strip('"\''))
UA = os.environ.get("SEC_USER_AGENT", "").strip()
class Undeclared(RuntimeError): pass
S = requests.Session(); S.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
_lock, _last = threading.Lock(), [0.0]

def get(url, tries=4):
    for a in range(tries):
        with _lock:
            w = _last[0] + 1.0 / RATE - time.time()
            if w > 0: time.sleep(w)
            _last[0] = time.time()
        try:
            r = S.get(url, timeout=20)
            if r.status_code == 404: return None
            # sec.gov Archives is S3-backed: a file that does not exist (e.g. daily index of a federal holiday) answers 403 AccessDenied, not 404
            if r.status_code == 403 and "<Code>AccessDenied</Code>" in r.text: return None
            if r.status_code == 403 and "Undeclared" in r.text: raise Undeclared("sec.gov 403 Undeclared Automated Tool (SEC_USER_AGENT needs a real contact e-mail)")
            if r.status_code in (403, 429, 503): time.sleep(5 * (a + 1)); continue
            r.raise_for_status(); return r.text
        except requests.RequestException:
            time.sleep(2 * (a + 1))
    raise RuntimeError(f"SEC fetch failed: {url}")

def _t(el, path):
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else ""

def parse(txt, acc):
    m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", txt, re.S)
    if not m: return []
    try: root = ET.fromstring(m.group(0))
    except ET.ParseError: return []
    sym = _t(root, "issuer/issuerTradingSymbol").upper(); icik = _t(root, "issuer/issuerCik")
    plan = _t(root, "aff10b5One").lower() in ("1", "true")
    foot = {f.get("id"): (f.text or "") for f in root.iter("footnote")}
    owners = [(_t(o, "reportingOwnerId/rptOwnerCik"), _t(o, "reportingOwnerId/rptOwnerName"),
               {k: _t(o, f"reportingOwnerRelationship/{k}").lower() in ("1", "true") for k in ("isDirector", "isOfficer", "isTenPercentOwner")},
               _t(o, "reportingOwnerRelationship/officerTitle")) for o in root.findall("reportingOwner")]
    rows = []
    for i, tx in enumerate(root.findall("nonDerivativeTable/nonDerivativeTransaction")):
        if _t(tx, "transactionCoding/transactionCode") != "P": continue
        if _t(tx, "transactionAmounts/transactionAcquiredDisposedCode/value") != "A": continue
        try: sh = float(_t(tx, "transactionAmounts/transactionShares/value") or 0); px = float(_t(tx, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError: continue
        refs = [f.get("id") for f in tx.iter("footnoteId")]
        tx_plan = plan or any(re.search(r"10b5-?1", foot.get(r, ""), re.I) for r in refs)
        for cik, name, rel, title in owners:
            rows.append({"acc": acc, "i": i, "symbol": sym, "issuer_cik": icik, "owner_cik": cik, "owner": name, "rel": rel, "title": title,
                         "date": _t(tx, "transactionDate/value")[:10], "shares": sh, "price": px, "value": round(sh * px, 2),
                         "plan_10b5_1": tx_plan, "n_owners_on_filing": len(owners)})
    return rows

def crawl_day(d):
    path = f"{CACHE}/{d:%Y%m%d}.json"
    if os.path.exists(path): return json.load(open(path))
    q = (d.month - 1) // 3 + 1
    idx = get(f"https://www.sec.gov/Archives/edgar/daily-index/{d.year}/QTR{q}/form.{d:%Y%m%d}.idx")
    if idx is None:   # weekend/holiday or not published yet
        if d < dt.date.today() - dt.timedelta(days=1) and d.weekday() >= 5:
            out = {"date": d.isoformat(), "done": True, "no_index": True, "filings": 0, "purchases": []}
            ac.write_json(path, out); return out
        print(f"[INSIDERS] {d} no EDGAR daily index (404/403 AccessDenied: federal holiday or not published yet) -> skipped", flush=True)
        return {"date": d.isoformat(), "done": False, "no_index": True}
    files = sorted({l.split()[-1] for l in idx.splitlines() if l.startswith("4 ") and l.split()[-1].endswith(".txt")})
    t0 = time.time(); rows = []; errs = 0
    def one(f):
        acc = f.rsplit("/", 1)[-1][:-4]
        try: return parse(get("https://www.sec.gov/Archives/" + f) or "", acc)
        except Exception: return None
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(one, files):
            if r is None: errs += 1
            else: rows += r
    out = {"date": d.isoformat(), "done": errs <= max(3, len(files) // 200), "filings": len(files), "errors": errs,
           "purchases": rows, "crawled_at": dt.datetime.now(ac.UTC).isoformat(timespec="seconds"), "secs": round(time.time() - t0)}
    if out["done"]: ac.write_json(path, out)
    print(f"[INSIDERS] {d} {len(files)} Form 4 filings, {len(rows)} purchase rows, {errs} errors, {out['secs']}s{'' if out['done'] else ' (incomplete, retry next run)'}", flush=True)
    return out

def tradable(symbols):
    tc = ac.trading(); ok = {}
    for s in symbols:
        try:
            a = tc.get_asset(s.replace("-", "."))
            ok[s] = bool(a.tradable and str(a.status.value) == "active" and str(a.asset_class.value) == "us_equity")
        except Exception: ok[s] = False
    return ok

# ---------------- v3 (2026-10-20, approved by Dominic): related reporting owners = ONE buyer; exclude offering-type buys ----------------
DETAIL = f"{CACHE}/detail"; os.makedirs(DETAIL, exist_ok=True)
OFFER_RE = re.compile(r"private\s+placement|initial\s+public\s+offering|\bIPO\b|\bunits?\b|\bPIPE\b|underwrit|public\s+offering|registered\s+direct"
                      r"|subscription\s+agreement|securities\s+purchase\s+agreement|concurrent(ly)?\s+(private|with)|directly\s+from\s+the\s+(issuer|company)", re.I)
ENT_RE = re.compile(r"\b(L\.?L\.?C|L\.?P|INC|LTD|LIMITED|CORP|CORPORATION|CO|COMPANY|FUND|FUNDS|TRUST|PARTNERS|PARTNERSHIP|CAPITAL|MANAGEMENT|HOLDINGS?"
                    r"|ADVISORS?|ADVISERS?|VENTURES?|INVESTMENTS?|GROUP|S\.?A|SE|AG|N\.?V|B\.?V|PLC|GMBH|SICAV|SICAF|GP|SPONSOR|ACQUISITION|FOUNDATION|ASSOCIATES)\b\.?", re.I)
STOP = {"the", "a", "an", "of", "and", "capital", "global", "first", "new", "american", "national", "united", "general", "international", "partners",
        "fund", "funds", "investment", "investments", "holdings", "holding", "group", "trust", "family", "revocable", "living", "management", "advisors",
        "ventures", "venture", "life", "sciences", "equity", "asset", "assets", "private", "public", "opportunities", "master", "offshore", "sv", "ii", "iii", "iv"}

def _addr_key(street, zipc):
    s = re.sub(r"[^a-z0-9]", "", (street or "").lower().replace("c/o", ""))
    return f"{s[:24]}|{(zipc or '')[:5]}" if s else None

def detail(acc, issuer_cik):
    """Re-read one cached Form 4 for the facts the day cache lacks: owner addresses, per-transaction footnotes/security title, issuer SIC/address."""
    path = f"{DETAIL}/{acc}.json"
    if os.path.exists(path): return json.load(open(path))
    txt = get(f"https://www.sec.gov/Archives/edgar/data/{int(issuer_cik)}/{acc}.txt")
    if txt is None: return None
    m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", txt, re.S)
    if not m: return None
    root = ET.fromstring(m.group(0))
    hdr = txt[:m.start()]
    iss = re.search(r"\nISSUER:(.*?)(\n[A-Z -]+:\s*\n|\Z)", hdr, re.S); iss = iss.group(1) if iss else ""
    sic = re.search(r"STANDARD INDUSTRIAL CLASSIFICATION:\s*(.*)", iss)
    ist = re.search(r"BUSINESS ADDRESS:.*?STREET 1:\s*(.*?)\n.*?ZIP:\s*(\S+)", iss, re.S)
    foot = {f.get("id"): (f.text or "") for f in root.iter("footnote")}
    owners = [{"cik": _t(o, "reportingOwnerId/rptOwnerCik"), "name": _t(o, "reportingOwnerId/rptOwnerName"),
               "addr": _addr_key(_t(o, "reportingOwnerAddress/rptOwnerStreet1"), _t(o, "reportingOwnerAddress/rptOwnerZipCode"))}
              for o in root.findall("reportingOwner")]
    txs = {}
    for i, tx in enumerate(root.findall("nonDerivativeTable/nonDerivativeTransaction")):
        txs[str(i)] = {"title": _t(tx, "securityTitle/value"), "foot": " | ".join(foot.get(f.get("id"), "") for f in tx.iter("footnoteId"))}
    out = {"acc": acc, "issuer_name": _t(root, "issuer/issuerName"), "issuer_sic": sic.group(1).strip() if sic else "",
           "issuer_addr": _addr_key(ist.group(1), ist.group(2)) if ist else None, "owners": owners, "txs": txs, "remarks": _t(root, "remarks")}
    ac.write_json(path, out); return out

def _root(name):
    """Group key from a reporting-owner name: entity -> first distinctive word (fund family); person -> surname (Form 4 names are 'LAST FIRST')."""
    toks = [t for t in re.split(r"[^a-z0-9]+", ENT_RE.sub(" ", name).lower()) if t]
    if not ENT_RE.search(name): return toks[0] if toks and len(toks[0]) >= 3 else None
    toks = [t for t in toks if t not in STOP and not t.isdigit() and len(t) >= 3]
    return toks[0] if toks else None

def first_bars(symbols, start):
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    out = {}
    try:
        bs = ac.stock_data().get_stock_bars(StockBarsRequest(symbol_or_symbols=list(symbols), timeframe=TimeFrame.Day, start=dt.datetime.combine(start, dt.time())))
        for s, bars in bs.data.items(): out[s] = min(b.timestamp for b in bars).date().isoformat() if bars else None
    except Exception as e: print(f"[INSIDERS] first-trading-day lookup failed: {type(e).__name__}", flush=True)
    return out

def refine(cands, rows):
    """cands: symbols passing the raw rule (superset). Returns (agg by symbol with groups, dropped {symbol: reason})."""
    by = {}
    for p in rows:
        if p["symbol"] in cands: by.setdefault(p["symbol"], []).append(p)
    det, dropped = {}, {}
    for s, ps in by.items():
        for acc in {p["acc"] for p in ps}:
            try: det[acc] = detail(acc, ps[0]["issuer_cik"])
            except Undeclared: raise
            except Exception: det[acc] = None
    since_bars = dt.date.today() - dt.timedelta(days=120)
    fb = first_bars({s.replace("-", ".") for s in by}, since_bars)
    agg = {}
    for s, ps in by.items():
        if any(det.get(p["acc"]) is None for p in ps): dropped[s] = "could not re-read every filing (unverified)"; continue
        d0 = det[ps[0]["acc"]]
        if "6770" in d0["issuer_sic"] or "BLANK CHECK" in d0["issuer_sic"].upper(): dropped[s] = f"SPAC / blank-check issuer ({d0['issuer_name']}, SIC {d0['issuer_sic']})"; continue
        first = fb.get(s.replace("-", "."))
        newly = first and first > (since_bars + dt.timedelta(days=5)).isoformat()
        keep, excl = [], {"offering": 0.0, "pre_listing": 0.0}
        for p in ps:
            dd = det[p["acc"]]; tx = dd["txs"].get(str(p.get("i")), {})
            v = p["value"] / max(1, p["n_owners_on_filing"])
            if OFFER_RE.search(tx.get("foot", "")) or OFFER_RE.search(dd.get("remarks", "")) or re.search(r"\bunits?\b|warrant", tx.get("title", ""), re.I):
                excl["offering"] += v; continue
            if newly and p["date"] <= (dt.date.fromisoformat(first) + dt.timedelta(days=3)).isoformat():
                excl["pre_listing"] += v; continue
            keep.append(p)
        # union-find over reporting-owner CIKs of this issuer
        par = {}
        def f(x):
            par.setdefault(x, x)
            while par[x] != x: par[x] = par[par[x]]; x = par[x]
            return x
        def u(a, b): par[f(a)] = f(b)
        names, reasons = {}, {}
        for acc in {p["acc"] for p in ps}:                       # joint filing -> one group (use all filings, incl. excluded rows)
            os_ = det[acc]["owners"]
            for o in os_: names[o["cik"]] = o["name"]; f(o["cik"])
            for o in os_[1:]: u(o["cik"], os_[0]["cik"])
        iaddr = d0.get("issuer_addr")
        byaddr, byroot = {}, {}
        def _ak(a):   # fuzzy street key: house number + first street word ("1200willowlakeblvd" == "1200willowlakeboulevard"); zip ignored
            m_ = re.match(r"(\d+)([a-z]{1,6})", (a or "").split("|")[0]); return (m_.group(1), m_.group(2)[:5]) if m_ else None
        ik = _ak(iaddr); ent_at = {}
        for acc in {p["acc"] for p in ps}:
            for o in det[acc]["owners"]:
                k = _ak(o["addr"])
                # shared NON-issuer address, and only if an ENTITY (fund/vehicle) files from it: officers at the company HQ are NOT merged
                if k and k != ik:
                    byaddr.setdefault(k, set()).add(o["cik"])
                    if ENT_RE.search(o["name"]): ent_at[k] = True
                r = _root(o["name"]) or ""
                if re.search(r"sponsor|acquisition", o["name"], re.I): r = "__spac_sponsor"
                if r: byroot.setdefault(r, set()).add(o["cik"])                                          # fund family / family surname
        byaddr = {k: v for k, v in byaddr.items() if ent_at.get(k)}
        for grp in list(byaddr.values()) + list(byroot.values()):
            g = sorted(grp)
            for x in g[1:]: u(x, g[0])
        gk = {}
        for p in keep: gk.setdefault(f(p["owner_cik"]), set()).add(p["owner_cik"])
        groups = [sorted(names.get(c, c) for c in members) for members in gk.values()]
        agg[s] = {"symbol": s, "n_groups": len(groups), "n_owners": len({p["owner_cik"] for p in keep}),
                  "total_usd": sum(p["value"] / max(1, p["n_owners_on_filing"]) for p in keep),
                  "last_txn": max((p["date"] for p in keep), default=""), "groups": sorted(groups, key=lambda g: g[0]),
                  "excluded_usd": {k: round(v) for k, v in excl.items() if v}, "first_bar": first if newly else None}
        if agg[s]["n_groups"] < MIN_INSIDERS or agg[s]["total_usd"] <= MIN_TOTAL:
            dropped[s] = (f"{agg[s]['n_groups']} distinct buyer group(s), ${agg[s]['total_usd']:,.0f} counted"
                          + (f"; excluded offering-type ${excl['offering']:,.0f}" if excl['offering'] else "")
                          + (f"; excluded pre/at-listing ${excl['pre_listing']:,.0f} (first bar {first})" if excl['pre_listing'] else ""))
    return agg, dropped

def null_out(reason):
    out = {"list": "INSIDERS", "status": "null", "names": None, "generated_at": dt.datetime.now(ac.BER).isoformat(timespec="seconds"),
           "reason": reason + " -> null = hold", "source": "SEC EDGAR Form 4"}
    ac.write_json(f"{OUT}/insiders.json", out); ac.log("LISTS", f"INSIDERS null (hold): {reason}"); return out

def build(max_days=None):
    if not re.search(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", UA, re.I):
        return null_out("SEC_USER_AGENT with a contact e-mail is not set in ~/.desk/sec.env (SEC requires it)")
    try: return _build(max_days)
    except Undeclared as e: return null_out(str(e))

def _build(max_days=None):
    today = dt.date.today()
    days = [today - dt.timedelta(days=i) for i in range(1, LOOKBACK_FILING_D + 1)]
    days = [d for d in days if d.weekday() < 5]
    if max_days: days = days[:max_days]
    res = [crawl_day(d) for d in days]
    missing = [r["date"] for r in res if not r.get("done") and not (r.get("no_index") and r["date"] >= (today - dt.timedelta(days=1)).isoformat())]
    # a weekday with no index (federal holiday) is fine once it is > 1 day old
    missing = [m for m in missing if not next((r for r in res if r["date"] == m), {}).get("no_index")]
    since = (today - dt.timedelta(days=WINDOW_D)).isoformat()
    seen, rows = set(), []
    for r in res:
        for p in r.get("purchases") or []:
            k = (p["acc"], p.get("i"), p["owner_cik"], p["date"], p["shares"], p["price"])
            if k in seen or p["date"] < since or p["plan_10b5_1"] or not p["symbol"] or p["symbol"] in ("NONE", "N/A", "NA"): continue
            seen.add(k); rows.append(p)
    agg = {}
    for p in rows:
        a = agg.setdefault(p["symbol"], {"symbol": p["symbol"], "issuer_cik": p["issuer_cik"], "insiders": {}, "total_usd": 0.0, "last_txn": ""})
        # joint filings (several owners on one filing) report the same shares once -> split value evenly, count each owner
        a["insiders"].setdefault(p["owner_cik"], p["owner"]); a["total_usd"] += p["value"] / max(1, p["n_owners_on_filing"])
        a["last_txn"] = max(a["last_txn"], p["date"])
    raw = [a for a in agg.values() if len(a["insiders"]) >= MIN_INSIDERS and a["total_usd"] > MIN_TOTAL]   # superset (merging only shrinks)
    tr = tradable([a["symbol"] for a in raw]) if raw else {}
    ref, dropped = refine({a["symbol"] for a in raw if tr.get(a["symbol"])}, rows) if raw else ({}, {})
    qual = [r for s, r in ref.items() if s not in dropped]
    names = sorted([{"symbol": a["symbol"].replace("-", "."), "n_insiders": a["n_groups"], "n_groups": a["n_groups"], "n_reporting_owners": a["n_owners"],
                     "total_usd": round(a["total_usd"]), "last_txn": a["last_txn"], "groups": a["groups"][:8],
                     "insiders": [g[0] + (f" (+{len(g)-1} related)" if len(g) > 1 else "") for g in a["groups"]][:8],
                     "excluded_usd": a["excluded_usd"]} for a in qual], key=lambda x: -x["total_usd"])
    status = "ok" if not missing and not max_days else "null"
    if max_days: missing = missing or [f"partial test run (--max-days {max_days})"]
    out = {"list": "INSIDERS", "status": status, "generated_at": dt.datetime.now(ac.BER).isoformat(timespec="seconds"),
           "rule": f">= {MIN_INSIDERS} distinct insider GROUPS, open-market buys (code P), trade date >= {since}, total > ${MIN_TOTAL:,}, excl. 10b5-1",
           "source": "SEC EDGAR Form 4 (daily form index + full submission)", "filing_days_checked": len(res),
           "filing_days_missing": missing, "purchase_rows_in_window": len(rows),
           "qualifying_not_tradable": [a["symbol"] for a in raw if not tr.get(a["symbol"])],
           "dropped_after_grouping": dropped,
           "grouping": "related reporting owners = 1 buyer (joint filing, shared non-issuer address, fund-family/surname root, SPAC sponsors); offering-type buys excluded (footnotes: private placement/IPO/units/PIPE/underwritten/registered direct..., unit/warrant securities, blank-check issuers, buys on/before first trading day+3d)",
           "names": names if status == "ok" else None,
           "reason": None if status == "ok" else f"Form 4 crawl incomplete for {len(missing)} filing day(s) -> null = hold"}
    ac.write_json(f"{OUT}/insiders.json", out)
    if not max_days:
        ac.log("LISTS", f"INSIDERS {'null (hold): ' + out['reason'] if status != 'ok' else str(len(names)) + ' names ' + ', '.join(n['symbol'] for n in names[:8])}")
    return out

if __name__ == "__main__":
    md = int(sys.argv[sys.argv.index("--max-days") + 1]) if "--max-days" in sys.argv else None
    o = build(md)
    print(json.dumps({k: v for k, v in o.items() if k != "names"} | {"names": [n["symbol"] for n in (o["names"] or [])]}, indent=1))
