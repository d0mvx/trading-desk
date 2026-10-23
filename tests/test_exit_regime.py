"""USER ORDER 2026-10-24 01:24 (Dominic): exit regime tp30_60_fix20 - TP1 +30% 1/3, TP2 +60% 1/3 of the INITIAL qty, last 1/3 runs;
after any TP a FIXED stop at entry -20%, no trailing, no profit lock; initial stops unchanged; open positions migrate without
double selling. USER ORDER 2026-10-24 01:48: + TP3 at 2x sells half of the REMAINING qty; only after TP3 a trailing stop
max(entry x 0.80, peak x 0.50); volume collapse off after TP3. USER ORDER 2026-10-24 01:25: fast exits (14 checks/min), volume collapse, liquidity pull, no-data emergency exit."""
import os, sys, json, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos

def ago(m, minutes): return (m.now() - dt.timedelta(minutes=minutes)).isoformat()

class Ladder(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme()
    def sell(self, o, frac):   # apply a partial sell like close_position does
        o["qty"] -= o["qty"] * frac
    def test_constants(self):
        m = self.m
        self.assertEqual(m.EXIT_TP_LADDER, [[0.30, 1 / 3], [0.60, 1 / 3], [1.00, 0.50, "rem"]]); self.assertEqual(m.EXIT_POST_TP_STOP, 0.20)
        self.assertEqual((m.EXIT_RUNNER_TRAIL, m.EXIT_RUNNER_TRAIL_AFTER, m.EXIT_VC_AFTER_TP3), (0.50, 1.00, False))
        self.assertEqual((m.MAIN_EXIT["runner_trail"], m.MAIN_EXIT["runner_trail_after"]), (0.50, 1.00))
        self.assertEqual(m.STOP_LOSS, {"bonding_curve": 0.30, "pumpswap": 0.20})
        for k in ("trail", "trail_arm", "trail_tight", "trail_after_time_stop", "lock_trigger"): self.assertNotIn(k, m.MAIN_EXIT)
        self.assertEqual(m.MAIN_EXIT["regime"], m.EXIT_REGIME)
    def test_tp1_tp2_runner(self):
        m = self.m; o = pos("A")
        self.assertIsNone(m.exit_decision(o, 1.29)[0])
        f, why = m.exit_decision(o, 1.30); self.assertAlmostEqual(f, 1 / 3); self.assertIn("take-profit 1/3", why); self.sell(o, f)
        self.assertIsNone(m.exit_decision(o, 1.45)[0])
        f, why = m.exit_decision(o, 1.61); self.assertAlmostEqual(f, 0.5); self.assertIn("take-profit 2/3", why); self.sell(o, f)
        self.assertAlmostEqual(o["qty"], o["qty_initial"] / 3)
        for px in (1.99, 1.0, 0.81): self.assertIsNone(m.exit_decision(o, px)[0], px)   # no trailing before 2x: 1.99 -> 0.81 stays
        self.assertEqual(m.stop_level(o)[2], "fixed after TP")
        f, why = m.exit_decision(o, 0.80); self.assertEqual(f, 1.0); self.assertIn("fixed after TP", why)
    def test_tp3_half_of_rest_then_trail50(self):
        m = self.m; o = pos("R")
        for px in (1.30, 1.60):
            f, _ = m.exit_decision(o, px); self.sell(o, f)
        f, why = m.exit_decision(o, 2.0); self.assertAlmostEqual(f, 0.5); self.assertIn("take-profit 3/3", why); self.sell(o, f)
        self.assertAlmostEqual(o["qty"], o["qty_initial"] / 6); self.assertEqual(o["tp_hits"], [0.3, 0.6, 1.0])
        self.assertAlmostEqual(m.stop_level(o)[0], 1.0); self.assertEqual(m.stop_level(o)[2], "trail after TP3")   # max(0.8, 2.0 x 0.5)
        self.assertIsNone(m.exit_decision(o, 4.0)[0]); self.assertAlmostEqual(m.stop_level(o)[0], 2.0)      # trail follows the peak
        self.assertIsNone(m.exit_decision(o, 2.01)[0])
        f, why = m.exit_decision(o, 2.0); self.assertEqual(f, 1.0); self.assertIn("trailing -50% from peak after TP3", why)
    def test_trail_floor_is_fixed_stop(self):
        m = self.m; o = pos("FL"); o["tp_hits"] = [0.3, 0.6, 1.0]; o["tp_passed"] = True; o["exit_regime"] = m.EXIT_REGIME; o["peak_price"] = 1.5
        self.assertEqual(m.stop_level(o)[:3:2], (0.8, "fixed after TP"))    # peak x 0.5 = 0.75 < entry x 0.8
    def test_gap_through_all_three_levels(self):
        m = self.m; o = pos("G3")
        f, why = m.exit_decision(o, 2.2); self.assertAlmostEqual(f, 5 / 6); self.assertEqual(o["tp_hits"], [0.3, 0.6, 1.0])
    def test_vc_lenient_after_tp3(self):
        m = self.m; flow = {"m5": 50, "h1": 12000, "liq": 50000}
        o = pos("VT", entry_time=ago(m, 15)); o["tp_hits"] = [0.3, 0.6, 1.0]; o["tp_passed"] = True; o["exit_regime"] = m.EXIT_REGIME
        self.assertIsNone(m.fast_exit(o, 1.05, flow, 15))
        m.EXIT_VC_AFTER_TP3 = True; self.assertIn("volume collapse", m.fast_exit(o, 1.05, flow, 15))
        m.EXIT_VC_AFTER_TP3 = False; self.assertIn("liquidity pull", m.fast_exit(o, 1.05, {"m5": 50, "h1": 12000, "liq": 10000}, 15))
    def test_gap_through_both_levels_sells_two_thirds_once(self):
        m = self.m; o = pos("G")
        f, why = m.exit_decision(o, 1.70); self.assertAlmostEqual(f, 2 / 3); self.assertEqual(o["tp_hits"], [0.3, 0.6]); self.sell(o, f)
        self.assertIsNone(m.exit_decision(o, 1.80)[0])
    def test_fixed_stop_after_tp1_on_curve_coin(self):
        m = self.m; o = pos("C", venue="bonding_curve")
        self.assertIsNone(m.exit_decision(o, 0.71)[0])                 # initial curve stop -30%
        f, _ = m.exit_decision(o, 1.31); self.sell(o, f)
        f, why = m.exit_decision(o, 0.79); self.assertEqual(f, 1.0); self.assertIn("-20% (fixed after TP)", why)
    def test_initial_stops(self):
        m = self.m
        self.assertEqual(m.exit_decision(pos("P"), 0.80)[0], 1.0); self.assertIsNone(m.exit_decision(pos("P2"), 0.81)[0])
        self.assertEqual(m.exit_decision(pos("B", venue="bonding_curve"), 0.70)[0], 1.0)
    def test_newpairs_plan(self):
        import newpairs
        m = self.m
        for tier, ts in (("normal", 30), ("strong", 180)):
            ex = m.regime_plan(newpairs.EXIT_TIERS[tier])
            self.assertEqual(ex["tp"], m.EXIT_TP_LADDER); self.assertEqual(ex["time_stop_min"], ts); self.assertTrue(ex["time_stop_only_if_not_profit"])
            self.assertEqual(ex["max_hold_min"], 720); self.assertNotIn("trail", ex)
        o = pos("N", sleeve="newpairs", venue="bonding_curve", stop_loss=0.30, tier="normal", exit=m.regime_plan(newpairs.EXIT_TIERS["normal"]),
                entry_time=ago(m, 45))
        self.assertIsNone(m.exit_decision(o, 1.10)[0])                 # 45 min, in profit -> time stop does not fire
        f, why = m.exit_decision(o, 0.99); self.assertEqual(f, 1.0); self.assertIn("time stop", why)
    def test_main_time_stop_still_cuts_after_60(self):
        m = self.m; o = pos("T", entry_time=ago(m, 61))
        f, why = m.exit_decision(o, 1.25); self.assertEqual(f, 1.0); self.assertIn("time stop", why)

class Migration(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme()
    OLD_MAIN = {"tier": "main", "tp": [[0.50, 0.50], [1.00, 0.25]], "trail_arm": 0.15, "trail": 0.25, "trail_tight": [1.00, 0.20],
                "time_stop_min": 60, "time_stop_only_if_not_profit": False, "max_hold_min": None}
    def old(self, tok, sold, peak, **kw):
        m = self.m; o = pos(tok, entry_time=ago(m, 20), peak_price=peak, **kw)
        o["qty"] = o["qty_initial"] * (1 - sold); o["tp_hits"] = [0.5] if sold >= 0.5 else []; o["tp_hits"] += [1.0] if sold >= 0.75 else []
        o["tp_done"] = sold > 0; return o
    def test_half_sold_gets_tp1_and_only_a_sixth_at_tp2(self):
        m = self.m; o = self.old("H", 0.5, 1.55)
        self.assertIsNone(m.exit_decision(o, 1.40)[0]); self.assertEqual(o["tp_hits"], [0.3]); self.assertTrue(o["tp_passed"])
        f, _ = m.exit_decision(o, 1.62); self.assertAlmostEqual(f * o["qty"], o["qty_initial"] / 6)   # 2/3 - 1/2
        self.assertTrue(any("[REGIME]" in l and "migrated" in l for l in m.LOGLINES))
    def test_three_quarters_sold_no_more_tp_sales(self):
        m = self.m; o = self.old("Q", 0.75, 2.1)
        self.assertIsNone(m.exit_decision(o, 1.9)[0]); self.assertEqual(o["tp_hits"], [0.3, 0.6, 1.0])   # old +100% TP = TP3, no re-sell
        self.assertIsNone(m.exit_decision(o, 2.5)[0])                                               # no TP3 sale again
        f, why = m.exit_decision(o, 1.25); self.assertEqual(f, 1.0); self.assertIn("trailing -50%", why)  # peak 2.5 x 0.5
    def test_previous_regime_position_at_tp2_migrates(self):
        m = self.m; o = pos("PR", entry_time=ago(m, 20), peak_price=1.8); o["qty"] = o["qty_initial"] / 3; o["tp_hits"] = [0.3, 0.6]
        o["tp_passed"] = True; o["exit_regime"] = "2026-10-24_0124_tp30_60_fix20"
        self.assertIsNone(m.exit_decision(o, 1.7)[0]); self.assertEqual(o["tp_hits"], [0.3, 0.6]); self.assertEqual(o["exit_regime"], m.EXIT_REGIME)
        f, _ = m.exit_decision(o, 2.05); self.assertAlmostEqual(f * o["qty"], o["qty_initial"] / 6)
    def test_passed_30_but_nothing_sold(self):
        m = self.m; o = self.old("P", 0.0, 1.40, venue="bonding_curve")
        self.assertIsNone(m.exit_decision(o, 1.10)[0]); self.assertTrue(o["tp_passed"]); self.assertEqual(o["tp_hits"], [])
        f, why = m.exit_decision(o, 0.80); self.assertIn("fixed after TP", why)
        o2 = self.old("P2", 0.0, 1.40); m.exit_decision(o2, 1.10)
        f, _ = m.exit_decision(o2, 1.31); self.assertAlmostEqual(f, 1 / 3)
    def test_frozen_old_plan_is_replaced_keeping_time_rules(self):
        m = self.m; o = self.old("S", 0.0, 1.0, exit=dict(self.OLD_MAIN, time_stop_min=45), shadow=True)
        m.exit_decision(o, 1.0)
        self.assertEqual(o["exit"]["regime"], m.EXIT_REGIME); self.assertEqual(o["exit"]["time_stop_min"], 45); self.assertNotIn("trail", o["exit"])
        self.assertEqual(o["exit_regime"], m.EXIT_REGIME)
    def test_idempotent(self):
        m = self.m; o = self.old("I", 0.5, 1.55); m.exit_decision(o, 1.4); hits = list(o["tp_hits"]); m.LOGLINES.clear()
        m.exit_decision(o, 1.4); self.assertEqual(o["tp_hits"], hits); self.assertFalse(m.LOGLINES)
    def test_new_position_not_logged_as_migration(self):
        m = self.m; o = pos("F"); m.exit_decision(o, 1.0); self.assertFalse(m.LOGLINES); self.assertEqual(o["exit_regime"], m.EXIT_REGIME)

class FastExits(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme()
    def test_cadence_14_per_min(self):
        m = self.m; self.assertEqual((m.RISK_CHECKS, m.RISK_STEP_S), (14, 4)); self.assertLess(m.RISK_HARD_S, 58)
    def test_volume_collapse(self):
        m = self.m; self.assertEqual((m.EXIT_VC_RATIO, m.EXIT_VC_MAX_CHG, m.EXIT_VC_MIN_HOLD_MIN, m.EXIT_VC_MIN_H1_USD), (0.10, 0.10, 10, 5000.0)); flow = {"m5": 50, "h1": 12000, "liq": 50000}
        f, why = m.exit_decision(pos("V", entry_time=ago(m, 15)), 0.95, flow=flow); self.assertEqual(f, 1.0); self.assertIn("volume collapse", why)
        self.assertIsNone(m.exit_decision(pos("V2", entry_time=ago(m, 15)), 1.15, flow=flow)[0])      # above entry -> runner kept
        self.assertIsNone(m.exit_decision(pos("V3", entry_time=ago(m, 8)), 0.95, flow=flow)[0])       # too early
        self.assertIsNone(m.exit_decision(pos("V4", entry_time=ago(m, 15)), 0.95, flow={"m5": 10, "h1": 4000})[0])   # thin hour
        self.assertIsNone(m.exit_decision(pos("V5", entry_time=ago(m, 15)), 0.95, flow={"m5": 900, "h1": 12000})[0])
        m.EXIT_VC_ENABLED = False; self.assertIsNone(m.exit_decision(pos("V6", entry_time=ago(m, 15)), 0.95, flow=flow)[0])
    def test_liquidity_pull(self):
        m = self.m; o = pos("L")
        self.assertIsNone(m.exit_decision(o, 1.0, flow={"liq": 100000})[0])
        f, why = m.exit_decision(o, 0.95, flow={"liq": 30000}); self.assertEqual(f, 1.0); self.assertIn("liquidity pull", why)
    def test_nodata_emergency_exit(self):
        m = self.m; o = pos("D", last_price=0.9); o["price_missing_since"] = (m.now() - dt.timedelta(seconds=m.EXIT_NODATA_S + 5)).isoformat()
        json.dump({"open": [o], "closed": []}, open(m.POS, "w"))
        m.fast_prices = lambda ps, errs=None: {}; m.pools_multi = lambda addrs, deadline=None: {}
        m.cooldown_on_close = lambda *a, **k: None
        m.risk_check(1, [])
        p = json.load(open(m.POS)); self.assertFalse(p["open"]); c = p["closed"][0]
        self.assertIn("no-data emergency exit", c["exit_reason"]); self.assertTrue(c["nodata_fill_assumed"])
        self.assertAlmostEqual(c["exit_mid"], 0.9 * (1 - m.EXIT_NODATA_HAIRCUT)); self.assertEqual(c["exit_regime"], m.EXIT_REGIME)
    def test_risk_check_passes_flow(self):
        m = self.m; json.dump({"open": [pos("R", entry_time=ago(m, 15))], "closed": []}, open(m.POS, "w"))
        m.cooldown_on_close = lambda *a, **k: None
        m.fast_prices = lambda ps, errs=None: {"PR": {"base_token_price_usd": "0.95", "volume_usd": {"m5": 50, "h1": 20000}, "reserve_in_usd": 40000, "_src": "dexscreener"}}
        m.risk_check(0, [])
        c = json.load(open(m.POS))["closed"][0]; self.assertIn("volume collapse", c["exit_reason"])

class RegimeMarkerAndLearner(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme(); self.m.REGIME_LOG = os.path.join(self.tmp, "logs", "exit_regime.jsonl")
    def test_marker_once(self):
        m = self.m; self.assertTrue(m.regime_marker()); self.assertFalse(m.regime_marker())
        recs = [json.loads(l) for l in open(m.REGIME_LOG)]; self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["regime"], m.EXIT_REGIME); self.assertIn("logged_at", recs[0]); self.assertEqual(recs[0]["trailing"]["from_peak"], 0.50); self.assertEqual(recs[0]["trailing"]["only_after_tp_level"], 1.00)
    def test_learner_cannot_touch_exits(self):
        import learner as L
        for n in ("meme.EXIT_TP_LADDER", "meme.EXIT_POST_TP_STOP", "meme.EXIT_VC_RATIO", "meme.EXIT_NODATA_S", "meme.EXIT_LIQ_PULL",
                  "meme.TRAIL_ARM", "meme.TRAIL_STOP", "meme.LOCK_TRIGGER", "meme.RISK_STEP_S", "meme.MAIN_EXIT", "newpairs.EXIT_TIERS", "meme.STOP_LOSS"):
            self.assertTrue(L.forbidden(n), n)
        for n in L.PARAMS: self.assertFalse(any(k in n.upper() for k in ("TRAIL", "LOCK", "EXIT", "STOP", "TP_", "RISK_")), n)
    def test_learner_reverts_never_mix_regimes(self):
        import learner as L
        t = lambda h, pp, r: {"entry_time": f"2026-10-24T{h:02d}:00:00+02:00", "pnl_pct": pp, "exit_regime": r}
        trades = [t(1, 0.5, "legacy")] * 3 + [t(h, -0.1, "legacy") for h in range(2, 4)] + [t(h, -0.3, "R2") for h in range(4, 20)]
        ov = {"changes": [{"status": "active", "kind": "tighten", "at": "2026-10-24T03:30:00+02:00", "param": "x"}]}
        L.check_reverts(ov, trades, 0)
        self.assertNotIn("revert_check", ov["changes"][0])   # no R2 trades before the change -> no cross-regime comparison

if __name__ == "__main__": unittest.main()

class ShadowSameLogic(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme()
        import importlib, shadow; importlib.reload(shadow); self.s = shadow; self.m = shadow.meme
        self.m.log = lambda l: None
        shadow.SPOS = f"{self.tmp}/shadow_positions.json"; shadow.STRADES = f"{self.tmp}/logs/shadow_trades.jsonl"
        shadow.SLOG = f"{self.tmp}/logs/shadow.log"; shadow.LOCK = f"{self.tmp}/.shadow.lock"
    def put(self, *os_):
        json.dump({"open": list(os_), "closed": [], "recent": {}}, open(self.s.SPOS, "w"))
    def spos(self, tok, **kw):
        o = pos(tok, shadow=True, **kw); o.update(id="S" + tok, cat="c", sleeve="main", realized=0.0, cost_initial=1.0); return o
    def test_old_shadow_half_sold_tp2_sells_a_sixth(self):
        o = self.spos("A", entry_time=ago(self.m, 20), peak_price=1.55, exit=dict(Migration.OLD_MAIN))
        o["qty"] = o["qty_initial"] / 2; o["tp_hits"] = [0.5]; o["tp_done"] = True; self.put(o)
        self.m.fast_prices = lambda ps, errs=None: {"PA": {"base_token_price_usd": "1.62", "quote_token_price_usd": "150", "volume_usd": {}, "reserve_in_usd": 50000}}
        self.s.check(1)
        d = json.load(open(self.s.SPOS)); o2 = d["open"][0]
        self.assertAlmostEqual(o2["qty"], o["qty_initial"] / 3, places=6); self.assertEqual(o2["exit_regime"], self.m.EXIT_REGIME)
        sells = [json.loads(l) for l in open(self.s.STRADES)]; self.assertEqual(sells[-1]["exit_regime"], self.m.EXIT_REGIME)
    def test_shadow_nodata_exit(self):
        o = self.spos("N", last_price=0.9); o["price_missing_since"] = (self.m.now() - dt.timedelta(seconds=200)).isoformat(); self.put(o)
        self.m.fast_prices = lambda ps, errs=None: {}
        self.s.check(1)
        d = json.load(open(self.s.SPOS)); self.assertFalse(d["open"]); self.assertIn("no-data", d["closed"][0]["reason"])
        self.assertEqual(d["closed"][0]["exit_regime"], self.m.EXIT_REGIME)
