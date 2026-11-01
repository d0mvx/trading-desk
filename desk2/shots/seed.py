"""demo DB for screenshots only (never the production desk.db)."""
import sys, datetime as dt, random
sys.path.insert(0, "/workspace/desk2")
from desk import db, util
db.use(sys.argv[1]); db.conn()
now = util.now(); I = lambda m: util.iso(now - dt.timedelta(minutes=m))
A = "6m7frLtvpHUNRfBHQHjtZZs812kVwKsY16gxPj6vpump"; B = "8gZMwbqtKyhbfZg8yYVGBbD43RjwH7HXXCVPBZDwpump"; C = "7ZB8kBdXqCc4aGpW3fW1k2YwZf9xkq3QG7hTn4pPpump"
for m, n, s in ((A, "Donald Pump", "DONALD"), (B, "Ansem Cat", "ANSEM"), (C, "Moo Deng", "MOO")):
    db.upsert_coin(m, name=n, symbol=s, pool="P" + m[:40], migrated_at=I(300), creator="Cr" + m[:40], holders=812)
v = 200.0
for i in range(300, -1, -5):
    v += random.uniform(-0.8, 1.2); db.insert("balance", ts=I(i), value=round(v, 2))
p = 0.00002
for i in range(240, -1, -1):
    p *= 1 + random.uniform(-0.02, 0.025); db.insert("prices", mint=A, ts=I(i), price=p, volume_m5=random.uniform(200, 4000))
db.x("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode) VALUES(?,?,?,?,?,?,?,?,?)",
     (A, I(200), 0.000019, 16, p * 1.1, 0.000019 * 0.94, 1, 0.21, "PAPER"))
db.x("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode,closed_at,exit_price,exit_reason,pnl_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
     (B, I(280), 0.0001, 16, 0.00015, 0.000094, 1, 0.41, "PAPER", I(150), 0.000132, "trail", 4.71))
db.x("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode,closed_at,exit_price,exit_reason,pnl_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
     (C, I(120), 0.00005, 16, 0.00005, 0.000047, 0, 0.40, "PAPER", I(90), 0.000047, "stop", -1.36))
L = [(1, "Mint authority", "Revoked"), (2, "Freeze authority", "Revoked"), (3, "Dev wallet", "1.2% · sold 0"), (4, "Top 10 holders", "18%"),
     (5, "Liquidity lock", "LP 100% burned/locked"), (6, "Pool age", "14 min"), (7, "Bundled wallets", "None"), (8, "Delegations", "None")]
for n, nm, val in L:
    db.insert("audits", mint=A, ts=I(201), layer=n, name=nm, value_text=val, pass_=None) if False else \
    db.x("INSERT INTO audits(mint,ts,layer,name,value_text,pass,source) VALUES(?,?,?,?,?,?,?)", (A, I(201), n, nm, val, 1, "rpc"))
db.x("INSERT INTO verdicts(mint,ts,alive_6h,organic,flush,chase,score,pass,reason,input_tokens) VALUES(?,?,?,?,?,?,?,?,?,?)", (A, I(200), .82, .77, .6, .2, 75, 1, None, 410))
for i, (k, m, ag, t, sub, val) in enumerate([("bought", A, "Executor", "Bought DONALD", "Executor · 19:40", "$16.00 · 8% of stack"),
        ("sold", B, "Risk", "Sold ANSEM", "Risk · trailing stop", "+$4.71 · +29.4%"), ("stopped", C, "Risk", "Stopped MOO", "Risk · -6% stop", "-$1.36"),
        ("rejected", C, "Auditor", "Rejected PEPE2", "Auditor · top10 41%", "Skipped"), ("rejected", B, "Scanner", "Killed WIF3", "Scanner · liq $12K", "Killed")]):
    db.x("INSERT INTO activity(ts,kind,mint,agent,title,subtitle,value) VALUES(?,?,?,?,?,?,?)", (I(200 - i * 20), k, m, ag, t, sub, val))
for a in ("scanner", "auditor", "analyst", "executor", "risk", "main"): db.heartbeat(a)
for i in range(12):
    db.x("INSERT INTO scans(mint,ts,liquidity_usd,top10_pct,h1_change_pct,age_min,verdict,reason) VALUES(?,?,?,?,?,?,?,?)", (B, I(i * 10), 12000, None, None, 3, "kill", "liq $12K"))
db.decide("scanner", B, "WIF3", "kill: liq $12K", False); db.decide("auditor", A, "DONALD", "8/8 cleared", True)
print("seeded")
