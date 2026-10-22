"""USER ORDER 2026-10-22 21:44: rule 9 (anti-chase / vertical run-up) + rule 10 (dump candle). No network: candles injected via fetch=."""
import os, sys, time, unittest
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK); sys.path.insert(0, os.path.dirname(__file__))
import rugpattern as rp
from test_rugpattern import C, fetcher

def series(now, closes, launch=None):
    """1m candles ending at `now`: one candle per minute with the given closes (open = previous close)."""
    t0 = now - 60 * len(closes); out = []; p = launch or closes[0]
    for i, c in enumerate(closes):
        out.append(C(t0 + 60 * i, p, max(p, c) * 1.01, min(p, c) * 0.99, c)); p = c
    return out

def m(now, closes): return [(x["timestamp"] / 1000, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), 1.0) for x in series(now, closes)]

class Rule9(unittest.TestCase):
    def test_thresholds_shipped(self):
        self.assertEqual((rp.R9_MAX_RUN15, rp.R9_YOUNG_N60, rp.R9_YOUNG_MAX_RUN30, rp.R10_MAX_RED1M, rp.R10_WIN_S, rp.NP_R9_MAX_RUN15, rp.NP_R10_MAX_RED1M),
                         (1.0, 25, 1.0, 0.20, 600, 1.0, 0.20))
    def test_vertical_runup_blocked(self):
        now = time.time(); closes = [1.0] * 60 + [1.0 * 1.06 ** i for i in range(1, 16)]   # +139% in 15 min, old pool
        met = rp.chase_metrics(m(now, closes), now)
        self.assertGreaterEqual(met["run15"], 1.0)
        self.assertTrue(rp.chase_verdict(met).startswith("rule 9 · chase: +"))
        self.assertTrue(rp.chase_verdict(met, newpairs=True).startswith("rule 9"))
    def test_slow_trend_passes(self):
        now = time.time(); closes = [1.0 * 1.02 ** i for i in range(90)]   # +35% per 15 min, 90 active minutes
        met = rp.chase_metrics(m(now, closes), now); self.assertLess(met["run15"], 1.0); self.assertIsNone(rp.chase_verdict(met))
    def test_young_pool_run30(self):
        now = time.time(); closes = [1.0] * 3 + [2.0] + [2.1] * 15   # 19 active min: +110% since launch 16 min ago, flat last 15 min
        met = rp.chase_metrics(m(now, closes), now)
        self.assertLess(met["run15"], 1.0); self.assertLess(met["n60"], 25); self.assertGreaterEqual(met["run30"], 1.0)
        self.assertIn("young pool", rp.chase_verdict(met))
        self.assertIsNone(rp.chase_verdict(met, newpairs=True))   # newpairs: no "young" rule (every new pair is young)
        older = rp.chase_metrics(m(now, [1.0] * 40 + closes), now)   # same move, but an established pool -> run30 alone allowed
        self.assertIsNone(rp.chase_verdict(older))
    def test_dump_candle_blocked(self):
        now = time.time(); closes = [1.0 * 1.01 ** i for i in range(60)]; closes[-4] = closes[-5] * 0.75   # -25% candle 4 min ago
        met = rp.chase_metrics(m(now, closes), now); self.assertGreaterEqual(met["red10"], 0.2)
        self.assertTrue(rp.chase_verdict(met).startswith("rule 10 · dump candle: -25%"))
        closes2 = [1.0 * 1.01 ** i for i in range(60)]; closes2[-15] = closes2[-16] * 0.75    # dump 15 min ago: outside window
        self.assertIsNone(rp.chase_verdict(rp.chase_metrics(m(now, closes2), now)))
    def test_check_integration_and_cache(self):
        now = time.time(); slow = series(now, [1e-5 * 1.01 ** i for i in range(90)])
        d = {"1h": [C(0, 1e-5, 1, 1e-5, 1)], "1m": slow}
        self.assertEqual(rp.check("ORG", fetch=fetcher(d), save=False)[0], [])
        d2 = dict(d); last = d["1m"][-1]; p = float(last["close"])
        d2["1m"] = d["1m"] + [C(now - 30, p, p * 1.02, p * 0.7, p * 0.72)]   # -28% candle at the end
        f, _ = rp.check("ORG", fetch=fetcher(d2), save=False)
        self.assertTrue(any(x.startswith("rule 10") for x in f), f)
        upd = {}; t, met = rp.rule9("ORG", fetch=fetcher(d2), upd=upd, now=now)
        self.assertIn("r9", upd["ORG"]); self.assertAlmostEqual(upd["ORG"]["r9"]["red10"], met["red10"])
        # fresh cache entry is reused without fetching
        def no(*a): raise AssertionError("must not fetch")
        t2, met2 = rp.rule9("ORG", fetch=no, cache={"ORG": upd["ORG"]}, now=now); self.assertEqual(t2, t)
    def test_missing_data_allows_main_and_rule7_still_skips_newpairs(self):
        def down(mint, i, l): raise rp.NoData("HTTP 503")
        f, notes = rp.check("Q9", newpairs=False, fetch=down, save=False)
        self.assertEqual(f, []); self.assertTrue(any("rule 9/10 n/a" in n for n in notes))
    def test_gate_keys_match_learner(self):
        from _iso import iso_meme
        mm, _ = iso_meme(); import learner as L
        self.assertEqual("judge: " + mm.gate_key("rule 9 · chase: +140% in 15 min (vertical run-up; max +100%)"), "judge: " + L.PARAMS["rugpattern.R9_MAX_RUN15"]["gate"].split("judge: ")[1])
        self.assertEqual(mm.gate_key("rule 10 · dump candle: -25% in one 1m candle"), "rule 10 dump candle")
        self.assertEqual(mm.gate_key("rule 9 · chase: young pool (18 active min/1h < 25)"), "rule 9 chase")
    def test_learner_can_only_tighten(self):
        import learner as L
        for k, cur in (("rugpattern.R9_MAX_RUN15", rp.R9_MAX_RUN15), ("rugpattern.R10_MAX_RED1M", rp.R10_MAX_RED1M)):
            s = L.PARAMS[k]; self.assertEqual(s["kind"], "max"); self.assertEqual(s["ceil"], cur); self.assertLess(s["floor"], cur)
            self.assertFalse(L.forbidden(k))
    def test_learner_features_read_r9(self):
        import learner as L
        old = L._RC[0]; L._RC[0] = {"MINT": {"r9": {"run15": 1.3, "red10": 0.05}}}
        try:
            f = L.features({"base_token": "MINT"}); self.assertEqual((f["run15"], f["red10"]), (1.3, 0.05))
        finally: L._RC[0] = old

if __name__ == "__main__":
    unittest.main()
