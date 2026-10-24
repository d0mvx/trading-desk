"""USER ORDER 2026-10-24 13:34 (+13:37/13:38): the six entry rules, position limits 8/2/10, safe sizing. Paper only; no network."""
import os, sys, json, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos
import rugpattern

def cand(**kw):
    c = {"venue": "pumpswap", "liquidity_usd": 90_000, "vol_h1": 80_000, "tx_m15": {"buys": 60, "sells": 40}, "tx_m5": {"buys": 20, "sells": 15}, "name": "T", "base_token": "MINT"}
    c.update(kw); return c

class Rule1Liquidity(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); import entry_rules; self.er = entry_rules
    def test_pumpswap_40k_boundary(self):
        self.assertIsNotNone(self.er.liq_gate("pumpswap", 39_999)); self.assertIsNone(self.er.liq_gate("pumpswap", 40_000))
    def test_curve_derived_liquidity_cannot_reach_40k(self):
        self.assertIn("curve", self.er.liq_gate("bonding_curve", 12_000)); self.assertEqual(self.er.MIN_POOL_LIQ_USD["bonding_curve"], 40_000)
    def test_missing_liquidity_fails(self): self.assertIsNotNone(self.er.liq_gate("pumpswap", None))
    def test_main_gates_pass_and_fail(self):
        self.assertEqual(self.er.main_gates(cand())[0], [])
        f, _ = self.er.main_gates(cand(liquidity_usd=20_000)); self.assertTrue(f[0].startswith("order rule 1"))

class Rule2Volume(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); import entry_rules; self.er = entry_rules
    def test_50k_boundary(self):
        self.assertIsNotNone(self.er.vol_gate(49_999)); self.assertIsNone(self.er.vol_gate(50_000))
    def test_missing_volume_allowed_with_note(self):
        f, n = self.er.main_gates(cand(vol_h1=None)); self.assertEqual(f, []); self.assertTrue(n)
    def test_newpairs_candle_volume(self):
        now = 10_000.0; m1 = [(now - 60 * i, 1.0, 1.01, 0.99, 1.0, 100.0) for i in range(20, 0, -1)]
        v = rugpattern.chase_verdict(rugpattern.chase_metrics(m1, now), newpairs=True); self.assertTrue(v.startswith("order rule 2"))
        self.assertIsNone(rugpattern.chase_verdict(rugpattern.chase_metrics(m1, now), newpairs=False))

class Rule3MidRocket(unittest.TestCase):
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
    def test_rule9_still_active(self):
        now = 100_000.0; m1 = [(now - 1000, 1.0, 1.0, 1.0, 1.0, 9000.0), (now - 700, 1.0, 1.0, 0.95, 0.99, 9000.0), (now - 60, 0.99, 2.2, 0.99, 2.2, 9000.0)]
        self.assertTrue(rugpattern.chase_verdict(rugpattern.chase_metrics(m1, now)).startswith("rule 9"))
    def test_cooldown_prefix(self):
        m, tmp = iso_meme(); self.assertIsNotNone(m.chase_cooldown(["order rule 3 · mid-rocket"], ["K"], "K"))

class Rule4SellsVsBuys(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); import entry_rules; self.er = entry_rules
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
    def test_two_losses_pause_60_min_then_resume(self):
        er = self.er; er.record_close(-0.5, "A", self.t0); self.assertIsNone(er.paused(self.t0))
        s = er.record_close(-0.2, "B", self.t0 + dt.timedelta(minutes=1)); self.assertEqual(s["streak"], 2)
        self.assertIsNotNone(er.paused(self.t0 + dt.timedelta(minutes=2)))
        self.assertIsNotNone(er.paused(self.t0 + dt.timedelta(minutes=60)))
        self.assertIsNone(er.paused(self.t0 + dt.timedelta(minutes=62)))
        self.assertEqual(er._load()["streak"], 0)
    def test_win_resets_streak(self):
        er = self.er; er.record_close(-1, "A", self.t0); er.record_close(0.3, "W", self.t0); s = er.record_close(-1, "B", self.t0)
        self.assertEqual(s["streak"], 1); self.assertIsNone(er.paused(self.t0))
    def test_state_persisted_in_file(self):
        er = self.er; er.record_close(-1, "A", self.t0); er.record_close(-1, "B", self.t0)
        d = json.load(open(er.STREAK_FILE)); self.assertTrue(d["paused_until"]); self.assertEqual(d["streak"], 2)
    def test_closes_during_pause_not_counted(self):
        er = self.er; er.record_close(-1, "A", self.t0); er.record_close(-1, "B", self.t0)
        until = er._load()["paused_until"]; er.record_close(-1, "C", self.t0 + dt.timedelta(minutes=5)); self.assertEqual(er._load()["paused_until"], until)
    def test_close_position_hook_tp_partial_is_not_a_loss(self):
        m = self.m; p = m.load_pos(); o = pos("TP", cost=10.0); p["open"] = [o]
        a = {"base_token_price_usd": 1.6, "reserve_in_usd": 200_000, "quote_token_price_usd": 150.0}
        m.close_position(o, a, "take profit 1", p, frac=1/3)                 # partial at +60%: a winner, never a loss
        self.assertEqual(self.er._load()["streak"], 0)
        a2 = {"base_token_price_usd": 0.97, "reserve_in_usd": 200_000, "quote_token_price_usd": 150.0}
        m.close_position(o, a2, "stop-loss", p)                               # remainder stopped at a small loss, position total still > 0 -> win
        tot = sum(x["pnl"] for x in p["closed"]); self.assertGreater(tot, 0); self.assertEqual(self.er._load()["streak"], 0)
    def test_close_position_two_real_losses_pause(self):
        m = self.m; p = m.load_pos(); p["open"] = [pos("L1"), pos("L2")]
        a = {"base_token_price_usd": 0.7, "reserve_in_usd": 200_000, "quote_token_price_usd": 150.0}
        for o in list(p["open"]): m.close_position(o, a, "stop-loss", p)
        self.assertIsNotNone(self.er.paused()); self.assertIsNotNone(m._er_pause())
    def test_bank_reset_closes_ignored(self):
        m = self.m; p = m.load_pos(); o = pos("R1"); p["open"] = [o]
        m.close_position(o, {"base_token_price_usd": 0.5, "reserve_in_usd": 200_000, "quote_token_price_usd": 150.0}, "reset: bank reset", p)
        self.assertEqual(self.er._load()["streak"], 0)
    def test_shadow_does_not_touch_streak(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "shadow.py")).read(); self.assertNotIn("entry_rules", src); self.assertNotIn("close_position", src)

class Rule6XIsResearch(unittest.TestCase):
    def setUp(self):
        import newpairs, entry_rules; self.n = newpairs; self.er = entry_rules
        self.static = {"impersonation": {}, "launchpad_website_hosts": []}
        self.c = {"mint": "M1", "name": "Kimchi", "symbol": "KIMCHI", "description": "", "twitter": "https://x.com/someone/status/123", "website": "", "telegram": "", "image_uri": "x"}
    def test_x_cannot_trigger(self):
        terms = [(self.n.norm("Kimchi"), self.n.squash("Kimchi"), "Kimchi", 10, "trending:x_news")]
        self.assertFalse(self.er.X_SCORE_ENABLED)
        sc, mt, rs = self.n.narrative(self.c, terms, self.static, {})
        self.assertLess(sc, self.n.THRESHOLD); self.assertTrue(any("X tag" in r for r in rs)); self.assertTrue(any("tag only" in r for r in rs))
    def test_x_would_trigger_if_enabled(self):
        terms = [(self.n.norm("Kimchi"), self.n.squash("Kimchi"), "Kimchi", 10, "trending:x_news")]
        self.er.X_SCORE_ENABLED = True
        try: sc, _, _ = self.n.narrative(self.c, terms, self.static, {}); self.assertGreaterEqual(sc, self.n.THRESHOLD)
        finally: self.er.X_SCORE_ENABLED = False
    def test_non_x_narrative_unchanged(self):
        terms = [(self.n.norm("Kimchi"), self.n.squash("Kimchi"), "Kimchi", 10, "famous_people")]
        sc, _, _ = self.n.narrative(self.c, terms, self.static, {}); self.assertGreaterEqual(sc, self.n.THRESHOLD)
    def test_no_x_api_in_trading_code(self):
        d = os.path.join(os.path.dirname(__file__), "..")
        for f in ("meme.py", "newpairs.py", "scan.py", "rugpattern.py", "shadow.py", "entry_rules.py"):
            s = open(os.path.join(d, f)).read().lower(); self.assertNotIn("api.twitter.com", s); self.assertNotIn("api.x.com", s); self.assertNotIn("fomo", s.replace("fomo or", ""))

class DashFeed(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); import entry_rules; self.er = entry_rules
    def test_drop_log_counts_and_feed(self):
        er = self.er
        self.assertTrue(er.log_fails(["order rule 1 · pool liquidity $12.0k < $40.0k"], "ZED", "M1", "main", "pumpswap"))
        er.log_fails(["order rule 1 · pool liquidity $12.0k < $40.0k"], "ZED", "M1", "main", "pumpswap")   # duplicate within 60 min -> one row
        er.log_fails(["order rule 3 · mid-rocket"], "STO", "M2", "main"); er.log_event("pass", 0, "OKK", "M3", "main", "passed")
        s = er.dash_summary(); self.assertEqual((s["evaluated"], s["dropped"]), (3, 2)); self.assertEqual((s["by_rule"][1], s["by_rule"][3]), (1, 1))
        self.assertEqual(len(open(er.DROP_LOG).readlines()), 3); self.assertEqual(s["feed"][0]["name"], "OKK")
    def test_non_order_fail_not_logged(self): self.assertFalse(self.er.log_fails(["rule 9 · chase"], "X", "M", "main"))

class Limits(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme(); json.dump({"start_capital": 104.64, "start_eur": 93.3, "eurusd": 1.1215, "epoch": 3}, open(f"{self.tmp}/bank.json", "w"))
    def test_limits_8_2_10(self):
        import newpairs; self.assertEqual((self.m.MAX_OPEN, self.m.TOTAL_MAX_OPEN, newpairs.NP_MAX_OPEN, newpairs.TOTAL_MAX_OPEN), (8, 10, 2, 10))
    def test_book_add_total_10(self):
        m = self.m
        for i in range(8): self.assertIsNone(m.book_add(pos(f"M{i}", cost=1.0), m.MAX_OPEN, m.TICKET_PCT))
        self.assertIn("max 8", m.book_add(pos("M9", cost=1.0), m.MAX_OPEN, m.TICKET_PCT))
        for i in range(2): self.assertIsNone(m.book_add(pos(f"N{i}", sleeve="newpairs", cost=1.0, venue="bonding_curve"), 2, m.TICKET_PCT, m.TOTAL_MAX_OPEN))
        self.assertIn("max 2", m.book_add(pos("N9", sleeve="newpairs", cost=1.0, venue="bonding_curve"), 2, m.TICKET_PCT, m.TOTAL_MAX_OPEN))
        self.assertEqual(len(m.load_pos()["open"]), 10)
    def test_sizing_cash_short(self):
        m = self.m
        self.assertEqual(m.size_ticket(500_000, 500.0), m.FIXED_TICKET_USD)       # cash plenty: fixed 10 EUR
        self.assertEqual(m.size_ticket(500_000, 3.7), 3.7)                         # cash short: scaled to cash left
        self.assertEqual(m.size_ticket(500_000, -2.0), 0.0); self.assertLess(m.size_ticket(500_000, 0.5), m.MIN_TICKET)   # never negative; below MIN_TICKET -> caller skips
        self.assertEqual(m.size_ticket(10_000, 500.0), 200.0 if m.FIXED_TICKET_USD > 200 else m.FIXED_TICKET_USD)
    def test_bank_holds_9_full_tickets(self):
        m = self.m; self.assertEqual(int(104.64 // m.FIXED_TICKET_USD), 9)   # epoch-3 bank 104.64 USD / 11.215 USD ticket
        p = m.load_pos(); st = m.meme_state(p); self.assertAlmostEqual(st["cash"], 104.64, 2)
        for i in range(8): self.assertIsNone(m.book_add(pos(f"B{i}", cost=m.FIXED_TICKET_USD), m.MAX_OPEN, m.TICKET_PCT))
        self.assertIsNone(m.book_add(pos("B8", sleeve="newpairs", cost=m.FIXED_TICKET_USD, venue="bonding_curve"), 2, m.TICKET_PCT, m.TOTAL_MAX_OPEN))
        cash = m.meme_state()["cash"]; self.assertGreater(cash, 0)
        self.assertEqual(m.size_ticket(900_000, cash), round(cash, 2))                # 10th ticket = the cash left, scaled down, never negative

if __name__ == "__main__": unittest.main()
