"""USER ORDER 2026-10-24 13:34 (+13:37/13:38): the six entry rules, position limits 8/2/10, safe sizing. Paper only; no network."""
import os, sys, json, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos, rules_only
import rugpattern

def cand(**kw):
    c = {"venue": "pumpswap", "liquidity_usd": 90_000, "vol_h1": 80_000, "tx_m15": {"buys": 60, "sells": 40}, "tx_m5": {"buys": 20, "sells": 15}, "name": "T", "base_token": "MINT"}
    c.update(kw); return c

class Rule1Liquidity(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); rules_only(self); import entry_rules; self.er = entry_rules
    def test_pumpswap_40k_boundary(self):
        self.assertIsNotNone(self.er.liq_gate("pumpswap", 39_999)); self.assertIsNone(self.er.liq_gate("pumpswap", 40_000))
    def test_curve_derived_liquidity_cannot_reach_40k(self):
        self.assertIn("curve", self.er.liq_gate("bonding_curve", 12_000)); self.assertEqual(self.er.MIN_POOL_LIQ_USD["bonding_curve"], 40_000)
    def test_missing_liquidity_fails(self): self.assertIsNotNone(self.er.liq_gate("pumpswap", None))
    def test_main_gates_pass_and_fail(self):
        self.assertEqual(self.er.main_gates(cand())[0], [])
        f, _ = self.er.main_gates(cand(liquidity_usd=20_000)); self.assertTrue(f[0].startswith("order rule 1"))

class Rule2Volume(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); rules_only(self); import entry_rules; self.er = entry_rules
    def test_50k_boundary(self):
        self.assertIsNotNone(self.er.vol_gate(49_999)); self.assertIsNone(self.er.vol_gate(50_000))
    def test_missing_volume_allowed_with_note(self):
        f, n = self.er.main_gates(cand(vol_h1=None)); self.assertEqual(f, []); self.assertTrue(n)
    def test_newpairs_candle_volume(self):
        now = 10_000.0; m1 = [(now - 60 * i, 1.0, 1.01, 0.99, 1.0, 100.0) for i in range(20, 0, -1)]
        v = rugpattern.chase_verdict(rugpattern.chase_metrics(m1, now), newpairs=True); self.assertTrue(v.startswith("order rule 2"))
        self.assertIsNone(rugpattern.chase_verdict(rugpattern.chase_metrics(m1, now), newpairs=False))

class Rule3MidRocket(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); rules_only(self)
    def candles(self, greens, step):
        now = 100_000.0; px = 1.0; out = []
        for i in range(10 - greens):   # flat red/neutral candles first
            out.append((now - 60 * (10 - i), px, px * 1.001, px * 0.999, px * 0.999, 9_000.0))
        for j in range(greens):
            o = px; px = px * (1 + step); out.append((now - 60 * (greens - j), o, px, o, px, 9_000.0))
        return out, now
    def verdict(self, greens, step):
        m1, now = self.candles(greens, step); return rugpattern.chase_verdict(rugpattern.chase_metrics(m1, now))
    def test_six_green_and_20pct_blocked(self): self.assertTrue(self.verdict(6, 0.035).startswith("order rule 3"))
    def test_five_green_not_blocked(self): self.assertIsNone(self.verdict(5, 0.05))
    def test_six_green_small_run_not_blocked(self): self.assertIsNone(self.verdict(6, 0.01))
    def test_rule9_still_active(self):   # legacy mode only (13:57: rule 9 is off by default)
        from _iso import legacy_filters; legacy_filters(self)
        now = 100_000.0; m1 = [(now - 1000, 1.0, 1.0, 1.0, 1.0, 9000.0), (now - 700, 1.0, 1.0, 0.95, 0.99, 9000.0), (now - 60, 0.99, 2.2, 0.99, 2.2, 9000.0)]
        self.assertTrue(rugpattern.chase_verdict(rugpattern.chase_metrics(m1, now)).startswith("rule 9"))
    def test_cooldown_prefix(self):
        m, tmp = iso_meme(); self.assertIsNotNone(m.chase_cooldown(["order rule 3 · mid-rocket"], ["K"], "K"))

class Rule4SellsVsBuys(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); rules_only(self); rules_only(self); import entry_rules; self.er = entry_rules
    def test_exactly_2_to_1_blocked_m15_and_m5(self):
        self.assertIsNotNone(self.er.bs_gate({"m15": {"buys": 10, "sells": 20}})); self.assertIsNotNone(self.er.bs_gate({"m5": {"buys": 5, "sells": 10}}))
    def test_just_under_2_to_1_ok(self): self.assertIsNone(self.er.bs_gate({"m15": {"buys": 10, "sells": 19}}))
    def test_zero_buys_with_sells_blocked(self): self.assertIsNotNone(self.er.bs_gate({"m15": {"buys": 0, "sells": 3}}))
    def test_no_data_passes_here(self): self.assertIsNone(self.er.bs_gate({}))
    def test_learner_cannot_loosen(self):
        import learner
        self.assertTrue(learner.forbidden("entry_rules.MAX_SELLS_PER_BUY")); self.assertGreaterEqual(learner.PARAMS["meme.J_MIN_BS_M15"]["floor"], 1.0)   # sells <= buys at the loosest: always stricter than 2:1
    def test_all_entry_constants_forbidden_for_learner(self):
        import learner
        for k in ("MIN_POOL_LIQ_USD", "MIN_VOL_H1_USD", "STREAK_LOSSES", "PAUSE_MIN", "X_SCORE_ENABLED"): self.assertTrue(learner.forbidden("entry_rules." + k))
        self.assertTrue(learner.forbidden("rugpattern.R3_GREEN_RUN"))

class Rule5LossStreak(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); import entry_rules; self.er = entry_rules; self.t0 = dt.datetime.now(dt.timezone.utc)
    def test_two_losses_pause_60_min_then_resume(self):   # 21:27: pause back to 60 min (13:34 value; 13:57 had 10)
        er = self.er; er.record_close(-0.5, "A", self.t0); self.assertIsNone(er.paused(self.t0))
        s = er.record_close(-0.2, "B", self.t0 + dt.timedelta(minutes=1)); self.assertEqual(s["streak"], 2)
        self.assertIsNotNone(er.paused(self.t0 + dt.timedelta(minutes=2)))
        self.assertEqual(er.PAUSE_MIN, 60)
        self.assertIsNotNone(er.paused(self.t0 + dt.timedelta(minutes=60)))   # lock starts at the 2nd loss (t0+1): runs until t0+61
        self.assertIsNone(er.paused(self.t0 + dt.timedelta(minutes=62)))
        self.assertEqual(er._load()["streak"], 0)
    def test_pause_switch_off(self):
        er = self.er; er.LOSS_PAUSE_ENABLED = False; er.record_close(-0.5, "A", self.t0); er.record_close(-0.2, "B", self.t0)
        self.assertIsNone(er.paused(self.t0 + dt.timedelta(minutes=2)))
    def test_non_order_fail_not_logged(self): self.assertFalse(self.er.log_fails(["rule 9 · chase"], "X", "M", "main"))

class Limits(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme(); json.dump({"start_capital": 104.64, "start_eur": 93.3, "eurusd": 1.1215, "epoch": 3}, open(f"{self.tmp}/bank.json", "w"))
    def test_limits_restored_6_3_8(self):   # 21:27: back to main 6 / new pairs 3 / total 8
        import newpairs; self.assertEqual((self.m.MAX_OPEN, self.m.TOTAL_MAX_OPEN, newpairs.NP_MAX_OPEN, newpairs.TOTAL_MAX_OPEN), (6, 8, 3, 8))
    def test_defaults_restored(self):
        import entry_rules as er
        self.assertFalse(er.ENTRY_RULES_ONLY); self.assertTrue(er.KEEP_DIAL_GATE); self.assertFalse(er.ORDER_RULES_ENABLED); self.assertFalse(er.X_SCORE_ENABLED)
        self.assertEqual(er.liq_gate("pumpswap", 1), None); self.assertEqual(er.vol_gate(1), None); self.assertIsNone(er.bs_gate({"m15": {"buys": 1, "sells": 9}}))
        self.assertEqual(er.main_gates(cand(liquidity_usd=1)), ([], []))
        self.assertIsNone(rugpattern.chase_verdict(rugpattern.chase_metrics([(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)], 100.0)))
    def test_book_add_main_6_np_3_total_8(self):
        m = self.m
        for i in range(6): self.assertIsNone(m.book_add(pos(f"M{i}", cost=1.0), m.MAX_OPEN, m.TICKET_PCT))
        self.assertIn("max 6", m.book_add(pos("M9", cost=1.0), m.MAX_OPEN, m.TICKET_PCT))
        for i in range(2): self.assertIsNone(m.book_add(pos(f"N{i}", sleeve="newpairs", cost=1.0, venue="bonding_curve"), 3, m.TICKET_PCT, m.TOTAL_MAX_OPEN))
        self.assertIn("overall max 8", m.book_add(pos("N9", sleeve="newpairs", cost=1.0, venue="bonding_curve"), 3, m.TICKET_PCT, m.TOTAL_MAX_OPEN))
        self.assertEqual(len(m.load_pos()["open"]), 8)
    def test_sizing_cash_short(self):
        m = self.m
        self.assertEqual(m.size_ticket(500_000, 500.0), m.FIXED_TICKET_USD)       # cash plenty: fixed 10 EUR
        self.assertEqual(m.size_ticket(500_000, 3.7), 3.7)                         # cash short: scaled to cash left
        self.assertEqual(m.size_ticket(500_000, -2.0), 0.0); self.assertLess(m.size_ticket(500_000, 0.5), m.MIN_TICKET)   # never negative; below MIN_TICKET -> caller skips
        self.assertEqual(m.size_ticket(10_000, 500.0), 200.0 if m.FIXED_TICKET_USD > 200 else m.FIXED_TICKET_USD)
    def test_bank_holds_9_full_tickets(self):
        m = self.m; self.assertEqual(int(104.64 // m.FIXED_TICKET_USD), 9)   # epoch-3 bank 104.64 USD / 11.215 USD ticket
        p = m.load_pos(); st = m.meme_state(p); self.assertAlmostEqual(st["cash"], 104.64, 2)
        for i in range(6): self.assertIsNone(m.book_add(pos(f"B{i}", cost=m.FIXED_TICKET_USD), m.MAX_OPEN, m.TICKET_PCT))
        for i in range(2): self.assertIsNone(m.book_add(pos(f"B{i+6}", sleeve="newpairs", cost=m.FIXED_TICKET_USD, venue="bonding_curve"), 3, m.TICKET_PCT, m.TOTAL_MAX_OPEN))
        cash = m.meme_state()["cash"]; self.assertGreater(cash, 0)
        self.assertEqual(m.size_ticket(900_000, cash), round(m.FIXED_TICKET_USD, 2) if cash >= m.FIXED_TICKET_USD else round(cash, 2))

if __name__ == "__main__": unittest.main()
