"""Rule 3 (meme 4% daily drawdown persisted across restarts / crashes / re-runs / a deleted or corrupt state file) and
rule 4b (the meme halt blocks the main pipeline incl. dip-watchlist buys and the new-pairs buy path)."""
import os, sys, json, unittest, importlib, datetime as dt
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme as _iso_meme, pos, DESK
def iso_meme():   # 2026-10-21: halt switched OFF by user order; tests exercise the mechanism with it ON
    m, t = _iso_meme(); m.DAILY_DD_ENABLED = True; return m, t

class DailyDD(unittest.TestCase):
    def setUp(self): self.m, self.tmp = iso_meme()
    def restart(self):
        """simulate a process restart: fresh module, same files"""
        keep = {k: getattr(self.m, k) for k in ("DESK", "POS", "POS_LOCK", "TRADES", "RISKST", "RISK_JOURNAL")}
        m, _ = iso_meme()   # importlib.reload: same module object, fresh globals
        for k, v in keep.items(): setattr(m, k, v)
        self.m = m; return m
    def test_halt_persists(self):
        m = self.m
        self.assertFalse(m.check_daily_dd(100.0))
        self.assertFalse(m.check_daily_dd(80.5))
        self.assertTrue(m.check_daily_dd(79.9))
        m = self.restart(); self.assertTrue(m.check_daily_dd(120.0))           # recovery does not lift it, re-run keeps it
        self.assertEqual(json.load(open(m.RISKST))["day_open_equity"], 100.0)
        os.remove(m.RISKST); m = self.restart()
        self.assertTrue(m.daily_halt_active()); self.assertTrue(m.check_daily_dd(120.0))   # deleted state -> journal
        open(m.RISKST, "w").write("{corrupt"); m = self.restart()
        self.assertTrue(m.daily_halt_active())                                  # corrupt -> journal / fail closed
    def test_day_open_not_rebased_by_rerun(self):
        m = self.m; m.check_daily_dd(100.0); m.check_daily_dd(75.0)
        os.remove(m.RISKST); m = self.restart(); m.check_daily_dd(85.0)
        self.assertEqual(json.load(open(m.RISKST))["day_open_equity"], 100.0)
        self.assertTrue(m.check_daily_dd(79.5))
    def test_corrupt_without_journal_fails_closed(self):
        m = self.m; open(m.RISKST, "w").write("{bad")
        self.assertTrue(m.daily_halt_active())
    def test_epoch_reset_record_replaces_sticky_halt(self):
        """2026-10-21 bank reset (USER ORDER 20:19): an explicit epoch_reset journal record lifts the day's halt and rebases day-open"""
        m = self.m; m.check_daily_dd(100.0); self.assertTrue(m.check_daily_dd(70.0))
        today = m.now().astimezone(m.BER).date().isoformat()
        rec = {"date": today, "day_open_equity": 112.15, "halted": False, "epoch_reset": "x"}
        json.dump(rec, open(m.RISKST, "w")); open(m.RISK_JOURNAL, "a").write(json.dumps(rec) + "\n")
        os.remove(m.RISKST); m = self.restart()
        self.assertFalse(m.daily_halt_active()); self.assertFalse(m.check_daily_dd(110.0))
        self.assertEqual(json.load(open(m.RISKST))["day_open_equity"], 112.15)
        self.assertFalse(m.check_daily_dd(90.0)); self.assertTrue(m.check_daily_dd(89.0))   # iso DAILY_DD; halt can trip again in the new epoch
    def test_new_berlin_day_resets(self):
        m = self.m; m.check_daily_dd(100.0); m.check_daily_dd(75.0)
        real = m.now; m.now = lambda: real() + dt.timedelta(days=1)
        self.assertFalse(m.check_daily_dd(75.0)); self.assertFalse(m.daily_halt_active())

class HaltBlocksBuys(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme(); m = self.m
        m.meme_state = lambda p=None: {"equity": 100.0, "cash": 100.0}
        m.check_daily_dd(100.0); m.check_daily_dd(75.0); assert m.daily_halt_active()
    def test_book_add_blocked(self):
        m = self.m
        self.assertIn("halt", m.book_add(pos("X"), m.MAX_OPEN, m.TICKET_PCT))
        self.assertIn("halt", m.book_add(pos("Y", sleeve="newpairs"), 2, 0.015))
        self.assertEqual(json.load(open(m.POS))["open"], [])
    def test_newpairs_enter_blocked(self):
        import newpairs; importlib.reload(newpairs)
        r = newpairs.enter((90, {"mint": "M", "bonding_curve": "BC", "symbol": "X", "creator": "C"}, {}, {}, {}), False, self.m)
        self.assertEqual(r, (None, "daily drawdown halt active"))
    def test_pipeline_blocked_incl_watchlist(self):
        m = self.m; import scan
        cand = {"pool": "PW", "base_token": "W", "name": "W / SOL", "venue": "pumpswap", "price_usd": 1, "sol_usd": 150, "liquidity_usd": 50000,
                "mcap_usd": 200000, "tx_h1": {"buyers": 500}, "pc_h1": 50, "url": "", "score": 1.0}
        m.desk_equity = lambda: (75.0, {"equity": 75.0, "cash": 75.0})
        m.latest_dial = lambda: ({"dial": {"meme": 1.0}, "degraded": []}, 1.0)
        m.judge_metrics = lambda c, watch=False: []
        m.rugcheck_report = lambda t: ({}, True); m.rugcheck_gates = lambda c, r: []
        m.dip_check = lambda *a, **k: (True, "dip ok", [], False)
        sv = {k: getattr(scan, k) for k in ("scan", "watchlist_active", "cooldown_active", "save_json", "record_judge")}
        try:
            scan.scan = lambda dry=False: {"candidates": [cand], "run_id": "t"}
            scan.watchlist_active = lambda: {"PW": {"added_at": "x", "venue": "pumpswap"}}   # coin is on the dip watchlist
            scan.cooldown_active = lambda: {}; scan.save_json = lambda *a: None; scan.record_judge = lambda *a: None
            sys.modules["shadow"] = type(sys)("shadow"); sys.modules["shadow"].open_entries = lambda e: None
            called = []; m.book_add = lambda *a, **k: called.append(a)
            r = m.pipeline()
        finally:
            for k, v in sv.items(): setattr(scan, k, v)
        self.assertEqual(called, []); self.assertEqual(r["reason"], "daily drawdown halt active")

if __name__ == "__main__": unittest.main()
