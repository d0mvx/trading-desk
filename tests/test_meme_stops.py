"""Rule 2: stops fire within ONE 12 s check, and missing price data never silently disables them."""
import os, sys, json, re, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos, DESK

class Stops(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme(); self.closed = []
        m = self.m
        def fake_close(o, a, reason, p, frac=1.0):
            self.closed.append((o["token"], reason, frac))
            if frac >= 1.0: p["open"] = [x for x in p["open"] if x["pool"] != o["pool"]]
        m.close_position = fake_close
        m.pools_multi = lambda addrs, deadline=None: {}
    def book(self, *os_):
        json.dump({"open": list(os_), "closed": []}, open(self.m.POS, "w"))
    def test_exit_decision_hard_stops(self):
        m = self.m
        for venue, sl in (("pumpswap", 0.20), ("bonding_curve", 0.30)):
            o = pos("S", venue=venue)
            self.assertIsNone(m.exit_decision(o, 1 - sl + 0.01)[0])
            frac, why = m.exit_decision(o, 1 - sl - 0.0001); self.assertEqual(frac, 1.0); self.assertIn("stop-loss", why)
        o = pos("S2", venue="pumpswap"); o.pop("stop_loss")      # missing stop field -> venue default, never 'no stop'
        self.assertEqual(m.exit_decision(o, 0.79)[0], 1.0)
    def test_cadence(self):
        m = self.m
        self.assertLessEqual(m.RISK_STEP_S, 12); self.assertGreaterEqual(m.RISK_CHECKS * m.RISK_STEP_S, 60 - m.RISK_STEP_S)
        self.assertLessEqual(m.RISK_LAST_START_S + m.RISK_STEP_S, 62)
        cron = os.popen("crontab -l").read()
        self.assertTrue(re.search(r"^\* \* \* \* \* .*run_meme\.sh risk", cron, re.M), "risk loop must run every minute")
    def test_stop_fires_in_the_same_check(self):
        m = self.m; self.book(pos("A"))
        m.fast_prices = lambda ps, errs=None: {"PA": {"base_token_price_usd": "0.75", "volume_usd": {}}}
        m.risk_check(3, [])
        self.assertEqual(self.closed[0][0], "A"); self.assertIn("stop-loss", self.closed[0][1]); self.assertIn("check 4/", self.closed[0][1])
    def test_missing_price_is_loud_and_stop_fires_when_price_returns(self):
        m = self.m; self.book(pos("B"))
        m.fast_prices = lambda ps, errs=None: {}
        m.risk_check(1, [])
        o = json.load(open(m.POS))["open"][0]
        self.assertIn("price_missing_since", o)
        # 70 s without price -> every check logs [STALE], and the GT fallback is tried
        p = json.load(open(m.POS)); p["open"][0]["price_missing_since"] = (m.now() - dt.timedelta(seconds=70)).isoformat(); json.dump(p, open(m.POS, "w"))
        asked = []; m.pools_multi = lambda addrs, deadline=None: asked.append(addrs) or {}
        m.LOGLINES.clear(); m.risk_check(2, [])
        self.assertTrue(any("NO PRICE" in l and "STALE" in l for l in m.LOGLINES)); self.assertEqual(asked, [["PB"]])
        # fallback returns a price below the stop -> closes in that same check
        m.pools_multi = lambda addrs, deadline=None: {"PB": {"base_token_price_usd": "0.70", "volume_usd": {}}}
        m.risk_check(2, [])
        self.assertEqual(self.closed[-1][0], "B"); self.assertIn("stop-loss", self.closed[-1][1])
    def test_price_error_does_not_crash_loop(self):
        m = self.m; self.book(pos("C"))
        def boom(ps, errs=None): raise RuntimeError("feed down")
        m.fast_prices = boom
        m.RISK_CHECKS = 1; m.RISK_HARD_S = 30
        m.dd_check = lambda errs: None
        sys.modules["shadow"] = type(sys)("shadow"); sys.modules["shadow"].check = lambda i, deadline=None: None
        m.risk()      # must not raise; error is collected and logged
        self.assertTrue(any("fast-exit errors" in l for l in m.LOGLINES))

if __name__ == "__main__": unittest.main()
