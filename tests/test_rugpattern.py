"""USER ORDER 2026-10-21 rule 7 (first candle at launch) + rule 8 (bot-wash). No network: candles injected via fetch=."""
import os, sys, json, math, random, unittest
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
import rugpattern as rp
FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "kimchi_candles.json")))

def C(t, o, h, l, c, v=100.0): return {"timestamp": int(t * 1000), "open": str(o), "high": str(h), "low": str(l), "close": str(c), "volume": str(v)}

def organic(now, n1m=60, n1s=300, seed=1):
    """Normal coin: launch at 3e-6, first minute +40%, then a noisy uptrend; irregular 1s candles."""
    rnd = random.Random(seed); t0 = now - n1m * 60; p = 3e-6; m1 = []
    for i in range(n1m):
        o = p; c = o * (1.4 if i == 0 else math.exp(rnd.gauss(0.03, 0.08))); h = max(o, c) * (1 + abs(rnd.gauss(0, .03))); l = min(o, c) * (1 - abs(rnd.gauss(0, .03)))
        m1.append(C(t0 + 60 * i, o, h, l, c, rnd.uniform(50, 900))); p = c
    s1 = []; q = p
    for i in range(n1s):
        if rnd.random() < 0.5: continue
        o = q; c = o * math.exp(rnd.gauss(0.0005, 0.02)); s1.append(C(now - n1s + i, o, max(o, c) * 1.005, min(o, c) * 0.995, c, rnd.expovariate(1 / 80))); q = c
    return {"1h": [C(t0 - t0 % 3600, 3e-6, p * 2, 3e-6, p)], "1m": m1, "1s": s1}

def fetcher(d, now_shift=None):
    def f(mint, interval, limit):
        if interval not in d: raise rp.NoData("not in fixture")
        return d[interval]
    return f

class Rule7(unittest.TestCase):
    def test_kimchi_first_candle_blocked_main_and_newpairs(self):
        t, met = rp.rule7(FX["mint"], fetch=fetcher(FX))
        self.assertIsNotNone(t); self.assertTrue(t.startswith("rule 7 · first candle +44")); self.assertGreater(met["share"], 0.95)
        t2, _ = rp.rule7(FX["mint"], newpairs=True, fetch=fetcher(FX)); self.assertIsNotNone(t2)
    def test_organic_coin_passes(self):
        import time
        d = organic(time.time()); t, met = rp.rule7("X", fetch=fetcher(d))
        self.assertIsNone(t); self.assertAlmostEqual(met["f1_pct"], 0.4 * 1.0, delta=0.2)
        self.assertIsNone(rp.rule7("X", newpairs=True, fetch=fetcher(d))[0])
    def test_big_first_candle_but_organic_growth_after_passes_main(self):
        # +1500% launch candle, but the coin then rose 10x more -> share < 50% -> main sleeve allows (graduation-style pump)
        d = {"1h": [C(0, 3e-6, 1, 3e-6, 1)], "1m": [C(60, 3e-6, 4.8e-5, 3e-6, 4.5e-5)] + [C(120 + 60 * i, 4.5e-5 * 1.05 ** i, 4.5e-5 * 1.05 ** (i + 1), 4.4e-5 * 1.05 ** i, 4.5e-5 * 1.05 ** (i + 1)) for i in range(60)]}
        t, met = rp.rule7("Y", fetch=fetcher(d)); self.assertGreater(met["f1_pct"], 10); self.assertLess(met["share"], 0.5); self.assertIsNone(t)
        self.assertIsNotNone(rp.rule7("Y", newpairs=True, fetch=fetcher(d))[0])   # new pairs: any first candle >= +150% skips
    def test_launch_not_in_1m_history(self):
        d = {"1h": [C(0, 3e-6, 1, 3e-6, 1)], "1m": [C(60000, 1e-4, 1.1e-4, 9e-5, 1e-4)]}
        with self.assertRaises(rp.NoData): rp.rule7("Z", fetch=fetcher(d))
    def test_missing_data_policy(self):
        def down(m, i, l): raise rp.NoData("HTTP 503")
        f, notes = rp.check("Q", newpairs=True, fetch=down, save=False)
        self.assertTrue(any(x.startswith("rule 7 · no first-candle data") for x in f))      # brand-new pairs: skip
        f, notes = rp.check("Q", newpairs=False, fetch=down, save=False)
        self.assertEqual(f, []); self.assertTrue(any("rule 7 n/a" in n for n in notes))      # main: allow + log
    def test_call_budget_is_not_an_allow(self):
        old = rp._calls[0]; rp._calls[0] = rp.MAX_CALLS_PER_RUN
        try:
            f, _ = rp.check("B", newpairs=False, save=False)
            self.assertTrue(f and f[0].startswith("not judged"))
        finally: rp._calls[0] = old
    def test_thresholds(self):
        self.assertEqual((rp.R7_MIN_PCT, rp.R7_MIN_SHARE, rp.NP_R7_MIN_PCT), (10.0, 0.50, 1.50))

class Rule8(unittest.TestCase):
    def test_kimchi_sawtooth_flagged(self):
        now = FX["entry_ms"] / 1000
        v, f = rp.rule8(FX["mint"], fetch=fetcher(FX), now=now)
        self.assertIsNotNone(v); self.assertIn("sawtooth", v)
    def test_micro_wash_flagged(self):
        now = 10000.0; s1 = []; p = 1e-4
        for i in range(200):
            o = p; c = o * (1.002 if i % 2 == 0 else 1 / 1.002); s1.append(C(now - 2000 + 10 * i, o, max(o, c), min(o, c), c, 50)); p = c
        v, f = rp.rule8("W", fetch=fetcher({"1s": s1}), now=now)
        self.assertIsNotNone(v); self.assertIn("micro-wash", v)
    def test_organic_not_flagged(self):
        import time
        for seed in range(8):
            d = organic(time.time(), seed=seed); d["1s"] = d["1s"] + organic(time.time() + 300, seed=seed + 50)["1s"]
            v, f = rp.rule8("O%d" % seed, fetch=fetcher(d))
            self.assertIsNone(v, f)
    def test_too_few_candles_allows(self):
        v, f = rp.rule8("F", fetch=fetcher({"1s": [C(1e9, 1, 1, 1, 1)]}), now=1e9)
        self.assertIsNone(v); self.assertIsNone(f)

class Integration(unittest.TestCase):
    def test_meme_gate_key_and_judge_hook(self):
        sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme
        m, _ = iso_meme()
        self.assertEqual(m.gate_key("rule 7 · first candle +4459% = 94% of rise"), "rule 7 first candle")
        self.assertEqual(m.gate_key("rule 8 · bot-wash pattern (sawtooth: 22"), "rule 8 bot-wash pattern")
        import rugpattern
        orig = rugpattern.check
        try:
            rugpattern.check = lambda mint, newpairs=False: (["rule 7 · first candle +4459%"], [])
            self.assertEqual(m.rugpattern_fails({"base_token": "X"})[0], ["rule 7 · first candle +4459%"])
            def boom(mint, newpairs=False): raise ValueError("x")
            rugpattern.check = boom
            f, notes = m.rugpattern_fails({"base_token": "X"}); self.assertEqual(f, []); self.assertTrue(notes)
        finally: rugpattern.check = orig
    def test_newpairs_safety_skips_on_rule7(self):
        import newpairs, rugpattern
        orig = rugpattern.check
        try:
            rugpattern.check = lambda mint, newpairs=False: (["rule 7 · first candle +500% (rug pattern; newpairs max +150%)"] if newpairs else [], [])
            ts = {"buyers": 40, "buys": 50, "sells": 10, "dev_sold": False, "start_known": True, "sniper_pct": 1.0}
            called = []
            f, info = newpairs.safety({"mint": "M", "bonding_curve": "BC"}, {}, {"progress": 20.0, "complete": False}, {"n": 1, "n24": 1, "n7d": 1}, ts,
                                      lambda mint: called.append(mint) or ({}, True), lambda c, r: [])
            self.assertTrue(any(x.startswith("rule 7") for x in f)); self.assertEqual(called, [])   # skipped before RugCheck
            rugpattern.check = lambda mint, newpairs=False: ([], [])
            f, info = newpairs.safety({"mint": "M", "bonding_curve": "BC"}, {}, {"progress": 20.0, "complete": False}, {"n": 1, "n24": 1, "n7d": 1}, ts,
                                      lambda mint: ({"score_normalised": 1}, True), lambda c, r: [])
            self.assertEqual(f, [])
        finally: rugpattern.check = orig

if __name__ == "__main__":
    unittest.main()
