"""STEP 13: one PAPER push through the notifier (Web Push); URL = coin_url(mint)."""
from desk import webpush, links, db
from .conftest import arun
M = "6m7frLtvpHUNRfBHQHjtZZs812kVwKsY16gxPj6vpump"

def test_paper_push(tdb, sent):
    db.upsert_coin(M, symbol="DON", image="https://cdn.example/don.png")
    r = arun(webpush.push("Buy DON · $16.00 · 8% of stack", "Auditor 8/8 · Analyst 74 · stop -6% · trail 12%", M, "buy"))
    assert r["subs"] == 1 and r["ok"] == 1
    p = sent[0]
    assert p["url"] == links.coin_url(M) and p["title"].startswith("PAPER · Buy DON") and p["icon"]
    assert db.one("SELECT url FROM pushes")["url"] == links.coin_url(M)
