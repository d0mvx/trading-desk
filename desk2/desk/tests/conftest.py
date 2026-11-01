import os, sys, asyncio, json, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from desk import db, webpush

@pytest.fixture
def tdb(tmp_path):
    p = str(tmp_path / "t.db"); old = db.DB_PATH
    db.use(p); db.conn(); yield p
    db.use(old)

@pytest.fixture
def sent(monkeypatch):
    """captures web pushes instead of delivering them; one fake subscription."""
    out = []
    monkeypatch.setattr(webpush, "_send_one", lambda sub, payload: (out.append(json.loads(payload)), "ok")[1])
    db.insert("push_subs", endpoint="https://fake.push/1", p256dh="x", auth="y", created_at="t")
    return out

def arun(c):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)
