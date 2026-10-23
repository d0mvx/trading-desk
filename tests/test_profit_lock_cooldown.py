"""USER ORDER 2026-10-23 17:43 (Dominic): (1) profit lock: once peak >= +LOCK_TRIGGER the stop is max(trailing, entry x (1+LOCK_FLOOR));
(2) a rule 9 / rule 10 block puts mint + pool on a CHASE_COOLDOWN_MIN cooldown in meme_cooldown.json (state; main + new pairs)."""
import os, sys, json, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos
import scan

class ProfitLock(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme()
    def test_defaults(self):
        self.assertEqual(self.m.LOCK_TRIGGER, 0.15); self.assertEqual(self.m.LOCK_FLOOR, 0.05)
    def test_lock_fires_after_peak_15(self):
        m = self.m; o = pos("L")
        self.assertIsNone(m.exit_decision(o, 1.17)[0])          # peak +17%, trail -25% would only fire at ~0.8775
        frac, why = m.exit_decision(o, 1.049)
        self.assertEqual(frac, 1.0); self.assertIn("profit lock", why)
    def test_no_lock_below_trigger(self):
        m = self.m; o = pos("N")
        self.assertIsNone(m.exit_decision(o, 1.14)[0]); self.assertIsNone(m.exit_decision(o, 1.01)[0])
    def test_trailing_still_wins_when_higher(self):
        m = self.m; o = pos("T")
        m.exit_decision(o, 2.0)                                   # peak +100% -> tightened trail -20% => 1.6 > 1.05
        frac, why = m.exit_decision(o, 1.59); self.assertEqual(frac, 1.0); self.assertIn("trailing stop", why)
    def test_existing_open_position_with_old_peak(self):
        m = self.m; o = pos("E", peak_price=1.30); o.pop("tp_hits"); o.pop("qty_initial")   # legacy-ish record, peak already +30%
        self.assertIsNone(m.exit_decision(o, 1.10)[0])
        frac, why = m.exit_decision(o, 1.04); self.assertEqual(frac, 1.0); self.assertIn("profit lock", why)
    def test_newpairs_plan_gets_lock(self):
        import newpairs
        m = self.m; o = pos("NP", sleeve="newpairs", venue="bonding_curve", exit=dict(newpairs.EXIT_TIERS["normal"]), tier="normal")
        m.exit_decision(o, 1.20)
        frac, why = m.exit_decision(o, 1.03); self.assertEqual(frac, 1.0); self.assertIn("profit lock", why)
    def test_hard_stop_unchanged(self):
        m = self.m; o = pos("H"); frac, why = m.exit_decision(o, 0.79); self.assertIn("stop-loss", why)

class ChaseCooldown(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme()
    def test_rule9_and_10_set_60min_cooldown(self):
        m = self.m; import rugpattern
        self.assertEqual(rugpattern.CHASE_COOLDOWN_MIN, 60)
        for fail in ("rule 9 · chase: +114% in 15 min", "rule 10 · dump candle: -38% in one 1m candle"):
            k = "M" + fail[5:7]
            until = m.chase_cooldown([fail], [k, "POOL" + k], "X")
            self.assertIsNotNone(until)
            cool = scan.cooldown_active()
            self.assertIn(k, cool); self.assertIn("POOL" + k, cool)
            left = (dt.datetime.fromisoformat(cool[k]["until"]) - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
            self.assertTrue(58 <= left <= 61, left)
        self.assertTrue(os.path.exists(f"{self.tmp}/meme_cooldown.json"))   # persisted file = state branch
    def test_other_rules_no_cooldown(self):
        m = self.m
        self.assertIsNone(m.chase_cooldown(["rule 7 · first candle +900%"], ["A"], "A")); self.assertIsNone(m.chase_cooldown([], ["A"], "A"))
        self.assertNotIn("A", scan.cooldown_active())
    def test_expires_after_60_min(self):
        m = self.m; t0 = dt.datetime.now(dt.timezone.utc)
        scan.cooldown_add(["Z"], "Z", "rule 9/10", at=t0, minutes=60)
        self.assertIn("Z", scan.cooldown_active(t0 + dt.timedelta(minutes=59)))
        self.assertNotIn("Z", scan.cooldown_active(t0 + dt.timedelta(minutes=61)))
    def test_short_cooldown_never_shortens_24h(self):
        m = self.m; t0 = dt.datetime.now(dt.timezone.utc)
        scan.cooldown_add(["S"], "S", "stop-out", at=t0)                 # 24 h
        scan.cooldown_add(["S"], "S", "rule 9/10", at=t0, minutes=60)
        self.assertIn("S", scan.cooldown_active(t0 + dt.timedelta(hours=23)))
        self.assertEqual(scan.cooldown_active(t0)["S"]["reason"], "stop-out")

if __name__ == "__main__": unittest.main()
