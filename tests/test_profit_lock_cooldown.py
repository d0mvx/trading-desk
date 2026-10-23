"""USER ORDER 2026-10-23 17:43 (Dominic): (1) profit lock (REMOVED by USER ORDER 2026-10-24 01:24, see test_exit_regime.py);
(2) a rule 9 / rule 10 block puts mint + pool on a CHASE_COOLDOWN_MIN cooldown in meme_cooldown.json (state; main + new pairs)."""
import os, sys, json, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos
import scan

class ProfitLockRemoved(unittest.TestCase):
    """USER ORDER 2026-10-24 01:24: the 2026-10-23 profit lock (+15% -> stop +5%) is REMOVED (tests/test_exit_regime.py)."""
    def setUp(self): self.m, self.tmp = iso_meme()
    def test_lock_constants_gone(self):
        for k in ("LOCK_TRIGGER", "LOCK_FLOOR", "TRAIL_STOP", "TRAIL_ARM", "TAKE_PROFIT"): self.assertFalse(hasattr(self.m, k), k)
    def test_no_lock_exit_after_peak_17(self):
        m = self.m; o = pos("L")
        self.assertIsNone(m.exit_decision(o, 1.17)[0])
        frac, why = m.exit_decision(o, 1.049); self.assertIsNone(frac); self.assertNotIn("profit lock", why)
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
