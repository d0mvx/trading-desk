"""Encrypted desk state for the public `state` branch.

state.enc = AES-256-GCM( tar.gz{ desk.db (consistent copy via the SQLite backup API), logs/* (tails) } )
key = DESK_STATE_KEY (base64, 32 bytes; GitHub secret + box .secrets/state_key). The branch never holds plaintext:
push subscriptions, positions and logs are unreadable without the key.

The branch is a single orphan commit, force-pushed (with lease) on every checkpoint -> no history bloat.
meta.json (plaintext, harmless): saved_at, run, owner, released_for, stopped_at, sha256 of state.enc.

  python gh/state.py export ROOT OUT.enc        # snapshot ROOT/desk.db + ROOT/logs -> OUT.enc
  python gh/state.py import IN.enc ROOT         # restore
"""
from __future__ import annotations
import base64, io, os, sqlite3, sys, tarfile, tempfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC, AAD = b"D2S1", b"desk2-state-v1"
LOG_CAP = 2 * 1024 * 1024          # keep the last 2 MB of each log file
SKIP = ("raw", ".pid")

def key() -> bytes:
    k = os.environ.get("DESK_STATE_KEY", "").strip()
    if not k:
        sys.exit("DESK_STATE_KEY missing")
    b = base64.b64decode(k)
    assert len(b) == 32, "DESK_STATE_KEY must be 32 bytes base64"
    return b

def snapshot_db(src: str, dst: str):
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
    d = sqlite3.connect(dst)
    s.backup(d)                     # consistent even while the desk writes (WAL)
    d.close(); s.close()

def export(root: str, out: str):
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as td, tarfile.open(fileobj=buf, mode="w:gz") as tar:
        dbp = os.path.join(root, "desk.db")
        if os.path.exists(dbp):
            c = os.path.join(td, "desk.db"); snapshot_db(dbp, c); tar.add(c, "desk.db")
        logs = os.path.join(root, "logs")
        for dp, dns, fns in os.walk(logs):
            dns[:] = [d for d in dns if d not in SKIP]
            for fn in fns:
                if fn.endswith(SKIP): continue
                p = os.path.join(dp, fn); rel = os.path.relpath(p, root)
                data = open(p, "rb").read()[-LOG_CAP:]
                ti = tarfile.TarInfo(rel); ti.size = len(data); ti.mtime = int(os.path.getmtime(p))
                tar.addfile(ti, io.BytesIO(data))
    n = os.urandom(12)
    blob = MAGIC + n + AESGCM(key()).encrypt(n, buf.getvalue(), AAD)
    tmp = out + ".tmp"; open(tmp, "wb").write(blob); os.replace(tmp, out)
    print(f"exported {len(blob)} bytes")

def import_(inp: str, root: str):
    blob = open(inp, "rb").read()
    assert blob[:4] == MAGIC, "not a desk2 state file"
    raw = AESGCM(key()).decrypt(blob[4:16], blob[16:], AAD)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        tar.extractall(root, filter="data")
    for f in ("desk.db-wal", "desk.db-shm"):      # the snapshot is self-contained
        p = os.path.join(root, f)
        if os.path.exists(p): os.remove(p)
    print("imported", len(raw), "bytes")

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "export": export(sys.argv[2], sys.argv[3])
    elif cmd == "import": import_(sys.argv[2], sys.argv[3])
    elif cmd == "newkey": print(base64.b64encode(os.urandom(32)).decode())   # only ever piped into a file
    else: sys.exit(__doc__)
