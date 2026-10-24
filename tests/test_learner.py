"""SELF-LEARN gate (USER ORDER 2026-10-22 17:58): tighten / loosen / min samples / holdout / step bounds / 24 h cooldown /
auto-revert / forbidden params / kill switch / apply() bounds. Synthetic journals, isolated files (no desk state touched)."""
import os, sys, json, tempfile, unittest, datetime as dt
from unittest import mock
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
import learner as L

T0 = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)
def tr(i, pnl, **feat):
    f = {"venue": "pumpswap", "liq": 30_000, "mcap": 100_000, "vol24": 200_000, "vol_liq": 6.0, "age_h": 5.0, "buys_h1": 500, "buyers_h1": 300,
         "buyers_per_buy": 0.6, "bs_m15": 1.5, "pc_h1": 40.0, "f1_pct": 1.0, "r7_share": 0.3}; f.update(feat)
    return {"sleeve": "main", "venue": f["venue"], "name": f"T{i}", "entry_time": (T0 + dt.timedelta(hours=i)).isoformat(), "pnl_pct": pnl, "feat": f}
def sh(i, pnl, cat, **feat):
    t = tr(i, pnl, **feat); t["cat"] = cat; return t
CUR = {n: v for n, v in {"scan.RULES.pumpswap.liq_min": 12_000, "scan.RULES.pumpswap.mcap_min": 40_000, "scan.RULES.pumpswap.mcap_max": 8_000_000,
       "scan.RULES.pumpswap.vol24_min": 40_000, "scan.RULES.pumpswap.max_vol24_to_liq": 40, "scan.RULES.pumpswap.age_max_h": 72,
       "scan.RULES.pumpswap.age_min_h": 0.25, "scan.RULES.min_buys_h1": 10, "scan.RULES.min_buys_m15": 2, "meme.J_MIN_BUYERS_H1": 50,
       "meme.J_MIN_BUYERS_PER_BUY": 0.25, "meme.J_MIN_BS_M15": 1.2, "meme.J_PC_H1.0": 10.0, "meme.J_PC_H1.1": 300.0,
       "rugpattern.R7_MIN_PCT": 10.0, "rugpattern.R7_MIN_SHARE": 0.5,
       "rugpattern.R9_MAX_RUN15": 1.0, "rugpattern.R10_MAX_RED1M": 0.20}.items()}

def bad_pocket(n_bad=20, recent=True, n=100):
    """n trades over time; n_bad with liq 12.0-14.0k and -20 %, spread evenly in time (recent=False: all in the oldest 50 %)."""
    out = []
    bad_idx = set(range(0, n, n // n_bad)) if recent else set(range(0, n // 2, max(1, (n // 2) // n_bad)))
    bad_idx = sorted(bad_idx)[:n_bad]
    for i in range(n):
        out.append(tr(i, -0.20, liq=12_000 + (i % 20) * 100) if i in bad_idx else tr(i, 0.02, liq=20_000 + i * 300))
    return out

class Gate(unittest.TestCase):
    def test_tighten_passes_gate(self):
        e = L.eval_tighten("scan.RULES.pumpswap.liq_min", 12_000, 15_000, bad_pocket(), CUR)
        self.assertTrue(e["ok"], e["why"]); self.assertEqual(e["pocket"]["n"], 20); self.assertLess(e["pocket"]["mean"], -0.05)
        self.assertGreaterEqual(e["holdout_pocket"]["n"], L.HOLDOUT_MIN_N)

    def test_tighten_min_samples(self):
        e = L.eval_tighten("scan.RULES.pumpswap.liq_min", 12_000, 15_000, bad_pocket(n_bad=10), CUR)
        self.assertFalse(e["ok"]); self.assertTrue(any("pocket n 10 < 15" in w for w in e["why"]))

    def test_tighten_needs_holdout(self):
        e = L.eval_tighten("scan.RULES.pumpswap.liq_min", 12_000, 15_000, bad_pocket(recent=False), CUR)
        self.assertFalse(e["ok"]); self.assertTrue(any("holdout" in w for w in e["why"]))

    def test_tighten_not_when_pocket_not_negative(self):
        ts = [tr(i, 0.01 if i % 2 else -0.02, liq=12_000 + i * 30) for i in range(40)] + [tr(100 + i, 0.0, liq=40_000) for i in range(40)]
        self.assertFalse(L.eval_tighten("scan.RULES.pumpswap.liq_min", 12_000, 15_000, ts, CUR)["ok"])

    def test_loosen_passes_on_positive_shadow(self):
        cat = "main:gate:judge: unique buyers h1"
        s = [sh(i, 0.20 + (i % 3) * 0.01, cat, buyers_h1=41 + i % 9) for i in range(25)]
        e = L.eval_loosen("meme.J_MIN_BUYERS_H1", 50, 40, s, CUR)
        self.assertTrue(e["ok"], e["why"]); self.assertEqual(e["would_be"]["n"], 25)

    def test_loosen_needs_20_and_positive_and_holdout(self):
        cat = "main:gate:judge: unique buyers h1"
        self.assertFalse(L.eval_loosen("meme.J_MIN_BUYERS_H1", 50, 40, [sh(i, 0.2, cat, buyers_h1=45) for i in range(19)], CUR)["ok"])
        self.assertFalse(L.eval_loosen("meme.J_MIN_BUYERS_H1", 50, 40, [sh(i, -0.1, cat, buyers_h1=45) for i in range(30)], CUR)["ok"])
        hold_bad = [sh(i, 0.3 if i < 21 else -0.4, cat, buyers_h1=45) for i in range(30)]   # recent 30 % negative
        e = L.eval_loosen("meme.J_MIN_BUYERS_H1", 50, 40, hold_bad, CUR); self.assertFalse(e["ok"]); self.assertTrue(any("holdout" in w for w in e["why"]))
        other = [sh(i, 0.3, "main:gate:judge: price h1", buyers_h1=45) for i in range(30)]   # other gate's shadows never count
        self.assertEqual(L.eval_loosen("meme.J_MIN_BUYERS_H1", 50, 40, other, CUR)["would_be"]["n"], 0)

    def test_step_bounds_and_floor_ceiling(self):
        for name, spec in L.PARAMS.items():
            v = CUR[name]; T, Lo = L.candidates(name, v)
            for x in T + Lo:
                self.assertLessEqual(abs(x - v), L.MAX_STEP * abs(v) + 1e-9, (name, v, x))
                self.assertTrue(spec["floor"] <= x <= spec["ceil"], (name, x))
        T, Lo = L.candidates("scan.RULES.pumpswap.mcap_max", 8_000_000); self.assertEqual(Lo, [])      # at ceiling: no loosening
        T, Lo = L.candidates("scan.RULES.pumpswap.liq_min", 8_100); self.assertTrue(all(x >= 8_000 for x in Lo))
        self.assertEqual(L.candidates("scan.RULES.min_buys_m15", 2), ([], []))                     # integer: +-1 would be 50 %

    def test_forbidden(self):
        for n in ("meme.FIXED_TICKET_USD", "meme.MAX_OPEN", "meme.TOTAL_MAX_OPEN", "newpairs.MAX_OPEN", "meme.STOP_LOSS.pumpswap",
                  "meme.MAIN_EXIT", "meme.DAILY_DD_ENABLED", "meme.RC_INSIDERS_MAX", "meme.I18_GATE_ENABLED", "ALPACA_PAPER", "meme.TICKET_PCT"):
            self.assertTrue(L.forbidden(n), n)
        self.assertFalse(L.forbidden("scan.RULES.pumpswap.liq_min"))
        self.assertFalse(any(L.forbidden(n) for n in L.PARAMS))

class Apply(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.p = os.path.join(self.d, "ov.json")
        self._lp = mock.patch.object(L, "LOG", os.path.join(self.d, "learner.log")); self._lp.start(); self.addCleanup(self._lp.stop)
    def g(self): return {"RULES": {"pumpswap": {"liq_min": 12_000, "mcap_min": 40_000}, "min_buys_h1": 10}, "J_PC_H1": (10.0, 300.0), "MAX_OPEN": 6}
    def write(self, params): json.dump({"params": params}, open(self.p, "w"))
    def test_apply_valid_ignores_invalid_and_forbidden(self):
        self.write({"scan.RULES.pumpswap.liq_min": {"value": 14_000}, "scan.RULES.pumpswap.mcap_min": {"value": 10}, "scan.MAX_OPEN": {"value": 99},
                    "meme.MAX_OPEN": {"value": 99}, "scan.RULES.min_buys_h1": {"value": "12"}})
        g = self.g(); done = L.apply("scan", g, self.p)
        self.assertEqual(done, {"scan.RULES.pumpswap.liq_min": 14_000}); self.assertEqual(g["RULES"]["pumpswap"]["mcap_min"], 40_000)
        self.assertEqual(g["MAX_OPEN"], 6); self.assertEqual(g["RULES"]["min_buys_h1"], 10)
    def test_apply_tuple_param(self):
        self.write({"meme.J_PC_H1.0": {"value": 12.5}}); g = self.g(); L.apply("meme", g, self.p); self.assertEqual(g["J_PC_H1"], (12.5, 300.0))
    def test_kill_switch(self):
        self.write({"scan.RULES.pumpswap.liq_min": {"value": 14_000}}); g = self.g()
        with mock.patch.dict(os.environ, {"LEARNER_ENABLED": "0"}):
            self.assertFalse(L.enabled()); self.assertEqual(L.apply("scan", g, self.p), {}); self.assertIsNone(L.run())
        self.assertEqual(g["RULES"]["pumpswap"]["liq_min"], 12_000)
        with mock.patch.object(L, "LEARNER_ENABLED", False): self.assertFalse(L.enabled())
        with mock.patch.object(L, "LEARNER_ENABLED", False), mock.patch.dict(os.environ, {"LEARNER_ENABLED": "1"}): self.assertTrue(L.enabled())

class Cycle(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(); self.d = d
        self.patches = [mock.patch.object(L, k, os.path.join(d, k.lower())) for k in ("OVR", "JOURNAL", "REPORT", "LOG", "CHANGES")]
        self.patches += [mock.patch.object(L, "_import_bases", lambda: None), mock.patch.object(L, "n_closed_sells", lambda: 0),
                         mock.patch.dict(L.BASE, CUR), mock.patch.dict(os.environ, {"LEARNER_ENABLED": "1"})]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in self.patches: p.stop()
    def journal(self, real, shadow=()):
        return mock.patch.object(L, "build_journal", lambda j=None: {"real": {str(i): t for i, t in enumerate(real)}, "shadow": {str(i): t for i, t in enumerate(shadow)}})
    def test_cycle_writes_one_bounded_change_and_cooldown(self):
        now = T0 + dt.timedelta(hours=200)
        with self.journal(bad_pocket()):
            r = L.run(now=now)
        self.assertEqual([p["param"] for p in r["proposals"]], ["scan.RULES.pumpswap.liq_min"])
        p = r["proposals"][0]; self.assertEqual(p["kind"], "tighten"); self.assertLessEqual(p["new"], 15_000); self.assertGreater(p["new"], 12_000)
        ov = json.load(open(L.OVR)); self.assertEqual(ov["params"]["scan.RULES.pumpswap.liq_min"]["value"], p["new"])
        self.assertEqual(len(open(L.CHANGES).read().splitlines()), 1)
        with self.journal(bad_pocket()):
            r2 = L.run(now=now + dt.timedelta(hours=2))          # 24 h cooldown
        self.assertEqual(r2["proposals"], []); self.assertIn("changed < 24 h ago", r2["rejected"]["scan.RULES.pumpswap.liq_min"][0])
    def test_dry_run_writes_nothing(self):
        with self.journal(bad_pocket()):
            r = L.run(dry=True, now=T0 + dt.timedelta(hours=200))
        self.assertEqual(len(r["proposals"]), 1); self.assertFalse(os.path.exists(L.OVR)); self.assertFalse(os.path.exists(L.CHANGES))
    def test_auto_revert(self):
        at = T0 + dt.timedelta(hours=100)
        json.dump({"params": {"scan.RULES.pumpswap.liq_min": {"value": 14_000}}, "changes": [{"id": "L1", "at": at.isoformat(), "param": "scan.RULES.pumpswap.liq_min",
                   "kind": "tighten", "old": 12_000, "new": 14_000, "status": "active"}]}, open(L.OVR, "w"))
        real = [tr(i, 0.00, liq=40_000) for i in range(52, 100)] + [tr(i, -0.10, liq=40_000) for i in range(101, 149)]
        with self.journal(real):
            r = L.run(now=T0 + dt.timedelta(hours=400))
        self.assertEqual(len(r["reverts"]), 1); ov = json.load(open(L.OVR))
        self.assertNotIn("scan.RULES.pumpswap.liq_min", ov["params"])                          # back to the code value
        self.assertEqual(ov["changes"][0]["status"], "reverted"); self.assertEqual(ov["changes"][-1]["kind"], "revert")
    def test_no_revert_before_48_or_when_better(self):
        at = T0 + dt.timedelta(hours=100)
        base = {"params": {"scan.RULES.pumpswap.liq_min": {"value": 14_000}}, "changes": [{"id": "L1", "at": at.isoformat(), "param": "scan.RULES.pumpswap.liq_min",
                "kind": "tighten", "old": 12_000, "new": 14_000, "status": "active"}]}
        for after in ([tr(i, -0.1, liq=40_000) for i in range(101, 140)], [tr(i, 0.05, liq=40_000) for i in range(101, 149)]):
            json.dump(base, open(L.OVR, "w"))
            with self.journal([tr(i, 0.0, liq=40_000) for i in range(52, 100)] + after):
                r = L.run(now=T0 + dt.timedelta(hours=400))
            self.assertEqual(r["reverts"], [])
    def test_max_changes_per_run(self):
        real = bad_pocket()
        for k, t in enumerate(real):   # second bad pocket on mcap 40-48k, third on vol24 -> 3 valid, only 2 applied
            if k % 5 == 1: t["pnl_pct"] = -0.25; t["feat"]["mcap"] = 41_000 + k * 50
            if k % 5 == 3: t["pnl_pct"] = -0.25; t["feat"]["vol24"] = 41_000 + k * 50
        with self.journal(real):
            r = L.run(dry=True, now=T0 + dt.timedelta(hours=200))
        self.assertEqual(len(r["proposals"]), L.MAX_CHANGES_PER_RUN)
        self.assertTrue(any("max 2 changes per run" in v[0] for v in r["rejected"].values()))

class Tick(unittest.TestCase):
    def test_tick_runs_under_the_cron_flock(self):
        """gh/crontab.gh wraps the tick in `flock -n .learner.lock`; the inner run lock must be a DIFFERENT file."""
        import subprocess
        d = tempfile.mkdtemp(); outer = os.path.join(d, ".learner.lock")
        self.assertNotEqual(os.path.basename(L.LOCK), ".learner.lock")
        with mock.patch.object(L, "LOCK", os.path.join(d, os.path.basename(L.LOCK))), mock.patch.object(L, "run", lambda: "ran"), \
             mock.patch.object(L, "load_overrides", lambda: {}), mock.patch.object(L, "n_closed_sells", lambda: 0), mock.patch.dict(os.environ, {"LEARNER_ENABLED": "1"}):
            p = subprocess.Popen(["flock", outer, "sleep", "3"]); import time as _t; _t.sleep(0.3)
            try: self.assertEqual(L.tick(), "ran")
            finally: p.kill(); p.wait()

class Bases(unittest.TestCase):
    def test_code_values_captured(self):
        import scan, meme, rugpattern   # noqa: F401  (import runs apply(), which records the code values)
        self.assertEqual(L.BASE.get("scan.RULES.pumpswap.liq_min"), 12_000); self.assertEqual(L.BASE.get("meme.J_MIN_BUYERS_H1"), 50)
        self.assertEqual(L.BASE.get("meme.J_PC_H1.1"), 300.0); self.assertEqual(L.BASE.get("rugpattern.R7_MIN_PCT"), 10.0)
        self.assertEqual(set(L.BASE) >= set(L.PARAMS), True)
        self.assertEqual((meme.MAX_OPEN, meme.TOTAL_MAX_OPEN), (8, 10))

if __name__ == "__main__": unittest.main()
