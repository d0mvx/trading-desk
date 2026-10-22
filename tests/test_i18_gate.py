"""2026-10-21: I-18 twin-buy gate (approved by Dominic 19:24) + V-01 shadow fields. Gate: skip if share >= 0.50; fail-open on
timeout/error; with the gate off nothing is ever blocked; Popen/child failures never raise. Network is always mocked.
MEME_SRC / SHADOW_SRC env vars point the test at staged copies (default: live files)."""
import os, sys, time, json, types, tempfile, unittest, importlib, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); DESK = os.path.dirname(HERE)
MEME_SRC = os.environ.get("MEME_SRC") or os.path.join(DESK, "meme.py")
SHADOW_SRC = os.environ.get("SHADOW_SRC") or os.path.join(DESK, "pick_shadow.py")
sys.path.insert(0, DESK)
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
TOP = {"base_token": "MintXpump", "name": "X / SOL", "venue": "pumpswap"}
class Hook(unittest.TestCase):
    def setUp(self):
        self.m = load("meme_t18", MEME_SRC); self.lines = []; self.m.log = lambda l: self.lines.append(l)
        self.calls = []; self.m_sub = __import__("subprocess"); self._popen = self.m_sub.Popen
        self.m_sub.Popen = lambda *a, **k: self.calls.append((a, k))
        self.ps = load("pick_shadow", SHADOW_SRC); sys.modules["pick_shadow"] = self.ps
    def tearDown(self):
        self.m_sub.Popen = self._popen; sys.modules.pop("pick_shadow", None)
    def fake_share(self, v):
        self.ps.twin_share_sync = lambda mint, t, timeout: {"i18_twin_share": v, "i18_n_buys": 20, "top": []}
    def test_live_constant_is_on(self):
        self.assertTrue(self.m.I18_GATE_ENABLED); self.assertEqual(self.m.I18_BLOCK_SHARE, 0.50)
    def test_true_blocks_at_or_above_50(self):
        for v in (0.50, 0.9):
            self.fake_share(v); self.assertIsNotNone(self.m.pick_shadow_hook(TOP, gate_enabled=True), v)
        self.assertTrue(self.calls)   # shadow child still spawned
    def test_true_no_block_below_50(self):
        self.fake_share(0.49); self.assertIsNone(self.m.pick_shadow_hook(TOP, gate_enabled=True))
    def test_true_timeout_does_not_block(self):
        self.ps.fetch_tape = lambda mint, t, timeout=5: time.sleep(10)
        self.m.PICK_SHADOW_TIMEOUT_S = 1; t = time.time()
        r = self.m.pick_shadow_hook(TOP, gate_enabled=True)
        self.assertIsNone(r); self.assertLess(time.time() - t, 3)
        args = json.loads(self.calls[-1][0][0][-1]); self.assertIn("fail-open", args.get("note", ""))
    def test_true_error_does_not_block(self):
        def boom(*a, **k): raise RuntimeError("x")
        self.ps.twin_share_sync = boom; self.assertIsNone(self.m.pick_shadow_hook(TOP, gate_enabled=True))
    def test_true_too_few_buys_does_not_block(self):
        self.ps.twin_share_sync = lambda mint, t, timeout: {"i18_twin_share": 1.0, "i18_n_buys": 4, "top": []}
        self.assertIsNone(self.m.pick_shadow_hook(TOP, gate_enabled=True))
    def test_false_never_blocks(self):
        self.fake_share(0.99); self.assertIsNone(self.m.pick_shadow_hook(TOP, gate_enabled=False)); self.assertTrue(self.calls)
    def test_popen_failure_never_raises(self):
        def boom(*a, **k): raise OSError("no fork")
        self.m_sub.Popen = boom; self.fake_share(0.1); self.assertIsNone(self.m.pick_shadow_hook(TOP, gate_enabled=True))
    def test_judge_uses_hook_before_size(self):
        src = open(MEME_SRC).read(); i = src.index("blk_i18 = pick_shadow_hook(top)"); self.assertLess(i, src.index("# ---- SIZE ----"))
        self.assertIn("if blk_i18:", src[i:i + 300])
class Shadow(unittest.TestCase):
    def test_twin_features(self):
        ps = load("ps_t", SHADOW_SRC); t = 1_800_000_000
        iso = lambda s: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(s))
        tr = [{"type": "buy", "timestamp": iso(t - 10), "amountSol": "1.0", "userAddress": "A", "tx": "a"},
              {"type": "buy", "timestamp": iso(t - 10), "amountSol": "1.0", "userAddress": "B", "tx": "b"},
              {"type": "buy", "timestamp": iso(t - 5), "amountSol": "0.37", "userAddress": "C", "tx": "c"},
              {"type": "buy", "timestamp": iso(t - 2000), "amountSol": "1.0", "userAddress": "D", "tx": "d"},
              {"type": "sell", "timestamp": iso(t - 10), "amountSol": "1.0", "userAddress": "E", "tx": "e"}]
        f = ps.twin_features(tr, t); self.assertEqual(f["i18_n_buys"], 3); self.assertAlmostEqual(f["i18_twin_share"], 0.6667, places=3)
    def test_run_error_logs_nulls(self):
        ps = load("ps_t2", SHADOW_SRC); d = tempfile.mkdtemp(); ps.OUT = f"{d}/p.jsonl"
        def boom(*a, **k): raise TimeoutError()
        ps.fetch_tape = boom; ps.run({"token": "M", "name": "n", "pick_ts": time.time()})
        r = json.loads(open(ps.OUT).read().splitlines()[-1]); self.assertIsNone(r["i18_twin_share"]); self.assertTrue(r["errors"])
if __name__ == "__main__": unittest.main()
