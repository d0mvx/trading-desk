"""USER ORDER 2026-10-24 13:57 (paper only): ONLY the six order rules decide an entry (main + new pairs = ONE pipeline, one pool of 10,
one shared loss-streak pause of 10 min). Old entry filters are OFF; hard safety (data errors / unbuyable) + cooldown stay.
No network; live state files are redirected by iso_meme."""
import os, sys, json, copy, unittest, datetime as dt
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK); sys.path.insert(0, os.path.dirname(__file__))
from _iso import iso_meme, pos, legacy_filters
import scan, rugpattern

def cand(**kw):
    c = {"pool": "PW", "base_token": "W", "name": "W / SOL", "venue": "pumpswap", "price_usd": 1.0, "sol_usd": 150.0, "liquidity_usd": 60_000,
         "mcap_usd": 200_000, "vol_h1": 80_000, "tx_m5": {"buys": 10, "sells": 10}, "tx_m15": {"buys": 30, "sells": 28}, "tx_h1": {"buyers": 3, "buys": 100, "sells": 90},
         "pc_h1": 900.0, "url": "", "score": 1.0, "src": ["t"]}
    c.update(kw); return c

class ScanLevel(unittest.TestCase):
    def test_only_hard_checks_remain_at_scan(self):
        sys.path.insert(0, os.path.dirname(__file__)); from test_ds_scan_mapping import FX, ev
        keys = set()
        for x in FX["pairs"]:
            c, why = ev(copy.deepcopy(x["gt"]))
            if c: keys |= set(c["fail_keys"])
        self.assertTrue(keys <= {"curve complete", "mcap missing", "quote not SOL", "price n/a", "stale data", "cooldown"}, keys)
    def test_legacy_flag_restores_old_scan_rules(self):
        legacy_filters(self); from test_ds_scan_mapping import FX, ev
        keys = set()
        for x in FX["pairs"]:
            c, why = ev(copy.deepcopy(x["gt"])); keys |= set(c["fail_keys"]) if c else set()
        self.assertTrue(any(k.startswith(("liquidity", "buys", "mcap", "age")) for k in keys))

class JudgeAndFilters(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme()
    def test_judge_thresholds_off(self):
        self.assertEqual(self.m.judge_metrics(cand(pc_h1=None, tx_h1={"buyers": None, "buys": 5}, tx_m15={"buys": 1, "sells": 1})), [])
    def test_judge_thresholds_back_in_legacy(self):
        legacy_filters(self); self.assertTrue(self.m.judge_metrics(cand()))
    def test_dip_filter_off(self):
        self.assertTrue(self.m.dip_check(cand(), None, 0, 0)[0])
    def test_rule9_10_young_off_rule3_on(self):
        now = 100_000.0
        m1 = [(now - 1000, 1.0, 1.0, 1.0, 1.0, 9000.0), (now - 700, 1.0, 1.0, 0.95, 0.99, 9000.0), (now - 60, 0.99, 2.2, 0.99, 2.2, 9000.0)]   # +120% last candle, -5% earlier
        self.assertIsNone(rugpattern.chase_verdict(rugpattern.chase_metrics(m1, now)))
        px = 1.0; g = []
        for j in range(10): o = px; px *= 1.035; g.append((now - 60 * (10 - j), o, px, o, px, 9000.0))
        self.assertTrue(rugpattern.chase_verdict(rugpattern.chase_metrics(g, now)).startswith("order rule 3"))
    def test_rugcheck_hard_subset(self):
        m = self.m
        rep = {"token": {"supply": 1000}, "creatorBalance": 900, "graphInsidersDetected": 20, "markets": [], "topHolders": [{"owner": "x", "pct": 60}],
               "risks": [{"name": "Low Liquidity", "level": "danger"}, {"name": "Top 10 holders high ownership", "level": "danger"}]}
        self.assertEqual(m.rugcheck_gates(cand(), rep), [])                                   # LP lock / creator % / holder % / insiders / soft danger flags: OFF
        self.assertTrue(m.rugcheck_gates(cand(), {**rep, "mintAuthority": "A"}))               # mint authority stays
        self.assertTrue(m.rugcheck_gates(cand(), {**rep, "freezeAuthority": "A"}))
        self.assertTrue(m.rugcheck_gates(cand(), {**rep, "rugged": True}))
        self.assertTrue(m.rugcheck_gates(cand(), {**rep, "transferFee": {"pct": 5}}))
        self.assertTrue(m.rugcheck_gates(cand(), {**rep, "risks": [{"name": "Honeypot sell blocked", "level": "danger"}]}))
    def test_gate_key_keeps_order_rule_number(self):
        self.assertEqual(self.m.gate_key("order rule 2 · dead volume: 1h volume $1k < $50k"), "order rule 2 dead volume")

class PipelineOnlySixRules(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme(); self.sv = {k: getattr(scan, k) for k in ("scan", "watchlist_active", "cooldown_active", "save_json", "record_judge")}
        m = self.m
        m.desk_equity = lambda: (104.64, {"equity": 104.64, "cash": 104.64})
        m.latest_dial = lambda: (None, None)                                              # no dial at all: must NOT block (not one of the six rules)
        m.rugcheck_report = lambda t: ({}, True); m.pick_shadow_hook = lambda t: None; m.rugpattern_fails = lambda c: ([], [])
        m.ds_prices = lambda items: {items[0]["pool"]: {"base_token_price_usd": "1.0", "quote_token_price_usd": "150", "reserve_in_usd": "60000", "market_cap_usd": "200000"}}
        scan.watchlist_active = lambda: {}; scan.cooldown_active = lambda: {}; scan.save_json = lambda *a: None; scan.record_judge = lambda *a: None
        sys.modules["shadow"] = type(sys)("shadow"); sys.modules["shadow"].open_entries = lambda e: None
        self.called = []; m.book_add = lambda *a, **k: self.called.append(a)
    def tearDown(self):
        for k, v in self.sv.items(): setattr(scan, k, v)
    def run_p(self, *cands):
        scan.scan = lambda dry=False: {"candidates": list(cands), "run_id": "t"}; return self.m.pipeline()
    def test_bad_old_metrics_but_six_rules_ok_is_bought(self):
        self.run_p(cand()); self.assertEqual(len(self.called), 1)                            # price h1 +900%, 3 buyers, no dial: old judge would have blocked all
        o = self.called[0][0]; self.assertEqual(o["token"], "W")
        self.assertEqual(self.called[0][1], 10)                                              # shared pool cap 10 handed to book_add
    def test_rule1_blocks_cheap_pool(self):
        r = self.run_p(cand(liquidity_usd=39_000)); self.assertEqual(self.called, []); self.assertIn("order rule 1", json.dumps(r["reason"]))
    def test_rule2_blocks_dead_volume(self):
        self.run_p(cand(vol_h1=49_000)); self.assertEqual(self.called, [])
    def test_rule4_blocks_sell_pressure(self):
        self.run_p(cand(tx_m15={"buys": 10, "sells": 25})); self.assertEqual(self.called, [])
    def test_curve_token_blocked_by_rule1(self):
        r = self.run_p(cand(venue="bonding_curve", liquidity_usd=7_000)); self.assertEqual(self.called, [])
    def test_pause_10_min_blocks_then_resumes(self):
        import entry_rules as er
        t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2); er.record_close(-1, "A", t); er.record_close(-1, "B", t)
        self.run_p(cand()); self.assertEqual(self.called, [])                                # 2 min after the 2nd loss: still locked
        t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=11)
        er.STREAK_FILE and json.dump({"streak": 2, "paused_until": (t + dt.timedelta(minutes=10)).isoformat(timespec="seconds")}, open(er.STREAK_FILE, "w"))
        self.run_p(cand()); self.assertEqual(len(self.called), 1)                            # lock over
    def test_cooldown_still_blocks(self):
        scan.cooldown_active = lambda: {"W": {"reason": "stop-loss", "until": "2999-01-01T00:00:00+00:00"}}
        self.run_p(cand()); self.assertEqual(self.called, [])
    def test_halt_still_blocks(self):
        self.m.check_daily_dd = lambda eq: True; self.run_p(cand()); self.assertEqual(self.called, [])

class NewPairsSafety(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); import newpairs; self.np = newpairs
    TS = {"buyers": 3, "buys": 10, "sells": 15, "dev_sold": True, "start_known": False, "sniper_pct": 90.0}
    def call(self, fresh=None, cs=None, ts=None, dev=None):
        import entry_rules; entry_rules.MIN_POOL_LIQ_USD["bonding_curve"] = 0.0     # let rule 1 pass to see the other gates (restored by cleanup)
        self.addCleanup(lambda: entry_rules.MIN_POOL_LIQ_USD.__setitem__("bonding_curve", 40_000.0))
        rugpattern_check = rugpattern.check; rugpattern.check = lambda mint, newpairs=False: ([], []); self.addCleanup(lambda: setattr(rugpattern, "check", rugpattern_check))
        return self.np.safety({"mint": "M", "bonding_curve": "BC"}, fresh or {"usd_market_cap": 1500.0, "market_cap_quote": 10.0},
                              cs or {"progress": 3.0, "complete": False, "real_sol": 5.0}, dev, ts or self.TS, lambda mint: ({}, True), lambda c, r: [])
    def test_soft_heuristics_off(self):
        f, info = self.call(); self.assertEqual(f, [], f)    # progress 3%, 3 buyers, dev sold, snipers 90%, no dev history: all OFF; 15 sells vs 10 buys < 2:1
    def test_hard_checks_stay(self):
        self.assertTrue(self.call(fresh={"complete": True, "usd_market_cap": 1, "market_cap_quote": 1})[0])
        self.assertTrue(self.call(fresh={"is_banned": True, "usd_market_cap": 1, "market_cap_quote": 1})[0])
        self.assertTrue(self.call(fresh={"transfer_fee_bps": 100, "usd_market_cap": 1, "market_cap_quote": 1})[0])
        self.assertTrue(self.call(cs={"progress": 3.0, "complete": True, "real_sol": 5.0})[0])
    def test_rule4_stays(self):
        f, _ = self.call(ts={**self.TS, "buys": 5, "sells": 20}); self.assertTrue(any("order rule 4" in x for x in f))
    def test_rule1_blocks_all_curves(self):
        import entry_rules; self.assertEqual(entry_rules.MIN_POOL_LIQ_USD["bonding_curve"], 40_000.0)
        f, _ = self.np.safety({"mint": "M", "bonding_curve": "BC"}, {"usd_market_cap": 1500.0, "market_cap_quote": 10.0}, {"progress": 90.0, "complete": False, "real_sol": 84.0},
                              None, self.TS, lambda mint: ({}, True), lambda c, r: [])
        self.assertTrue(any("order rule 1" in x for x in f))

class SharedStreakAcrossSleeves(unittest.TestCase):
    def test_np_enter_blocked_by_streak_from_main_losses(self):
        m, tmp = iso_meme(); import entry_rules as er, newpairs
        m.daily_halt_active = lambda: False
        t = dt.datetime.now(dt.timezone.utc); er.record_close(-1, "main A", t); er.record_close(-0.5, "np B", t)
        r = newpairs.enter((90, {"mint": "M", "bonding_curve": "BC", "symbol": "X", "creator": "C"}, {}, {}, {}), False, m)
        self.assertIsNone(r[0]); self.assertIn("pause", r[1])
    def test_pause_minutes_configurable_and_text_accurate(self):
        m, tmp = iso_meme(); import entry_rules as er
        er.PAUSE_MIN = 3; t = dt.datetime.now(dt.timezone.utc); er.record_close(-1, "A", t); er.record_close(-1, "B", t)
        pz = er.paused(t + dt.timedelta(minutes=1)); self.assertIsNotNone(pz)
        self.assertIsNone(er.paused(t + dt.timedelta(minutes=4)))
        er.PAUSE_MIN = 10

if __name__ == "__main__": unittest.main()
