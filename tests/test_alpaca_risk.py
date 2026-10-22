"""Alpaca PAPER risk rules (2026-10-20 audit): kill switch cancels orders BEFORE closing positions, kill state persists + fails
closed, no sleeve submits while the kill is active, STOP_ALL blocks buys, STOCKS 10%-per-name cap incl. trims, no averaging down,
max 16 names. Fake TradingClient only: no network, no keys, all files in a temp dir. DESK_SRC env = alternative code dir (staging)."""
import os, sys, json, types, tempfile, importlib, unittest, datetime as dt
SRC = os.environ.get("DESK_SRC", os.path.expanduser("~/.desk")); sys.path.insert(0, SRC)
for k in ("ALPACA_KEY", "ALPACA_SECRET"): os.environ.setdefault(k, "test-not-a-key")
os.environ["ALPACA_PAPER"] = "1"

class E:  # enum-like
    def __init__(self, v): self.value = v
class Pos:
    def __init__(self, sym, qty, price, avg=None, cls="us_equity"):
        self.symbol, self.qty, self.qty_available = sym, str(qty), str(qty)
        self.current_price, self.avg_entry_price = str(price), str(avg if avg is not None else price)
        self.market_value = str(qty * price); self.asset_class = E(cls)
class Fake:
    def __init__(self, *a, **k):
        self.calls, self.orders, self.positions, self.open_orders = [], [], [], []
        self.equity, self.last_equity, self.is_open = 100000.0, 100000.0, True
    def get_clock(self): return types.SimpleNamespace(is_open=self.is_open, next_open=None)
    def get_account(self): return types.SimpleNamespace(equity=str(self.equity), last_equity=str(self.last_equity))
    def get_all_positions(self): return list(self.positions)
    def get_orders(self, *a, **k): self.calls.append("get_orders"); return list(self.open_orders)
    def submit_order(self, req):
        self.calls.append("submit"); self.orders.append(req)
        return types.SimpleNamespace(id="x", client_order_id=req.client_order_id, status=E("accepted"))
    def cancel_orders(self): self.calls.append("cancel_orders"); self.open_orders = []; return []
    def close_all_positions(self, cancel_orders=False): self.calls.append("close_all"); n = len(self.positions); self.positions = []; return [0] * n
    def get_asset(self, s): return types.SimpleNamespace(fractionable=True, tradable=True, status=E("active"), asset_class=E("us_equity"))

def _front():   # desk modules do sys.path.insert(0, ~/.desk) themselves; keep SRC first so reload() picks the code under test
    while SRC in sys.path: sys.path.remove(SRC)
    sys.path.insert(0, SRC)

def iso():
    _front(); import alp_common as ac; importlib.reload(ac)
    tmp = tempfile.mkdtemp(prefix="desk_alp_test_"); [os.makedirs(f"{tmp}/{d}") for d in ("logs", "dial", "lists")]
    ac.DESK, ac.KILL = tmp, f"{tmp}/alp_kill.json"; ac.KILL_JOURNAL = None; ac.STOP_FILE = None
    fake = Fake(); ac.trading = lambda: fake
    ac.stock_data = lambda: types.SimpleNamespace(get_stock_latest_trade=lambda req: {s: types.SimpleNamespace(price=fake.px.get(s, 50.0)) for s in req.symbol_or_symbols})
    fake.px = {}
    json.dump({"generated_at": dt.datetime.now(ac.BER).isoformat(), "dial": {"stocks": 1.0, "crypto": 1.0, "meme": 1.0},
               "crypto_targets": {"weights": {"BTC": 0.5, "ETH": 0.5}, "scores": {"BTC": 0.3, "ETH": 0.2}}}, open(f"{tmp}/dial/2026-01-01.json", "w"))
    return ac, fake, tmp

def lists(tmp, drift, ins):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    json.dump({"status": "ok", "generated_at": now, "names": [{"symbol": s} for s in drift]}, open(f"{tmp}/lists/drift.json", "w"))
    json.dump({"status": "ok", "generated_at": now, "names": [{"symbol": s} for s in ins]}, open(f"{tmp}/lists/insiders.json", "w"))

def load(name, ac, tmp):
    _front(); m = importlib.import_module(name); _front(); importlib.reload(m)
    m.ac = ac; m.DRY = False
    if hasattr(m, "STATE"): m.STATE = f"{tmp}/{name}_state.json"
    if hasattr(m, "BOOK"): m.BOOK = f"{tmp}/stocks_book.json"
    return m

def side(o): return str(o.side.value).lower()

class KillSwitch(unittest.TestCase):
    def setUp(self): self.ac, self.f, self.tmp = iso()
    def run_ks(self, argv=()):
        ks = load("killswitch", self.ac, self.tmp); ks.CANCEL_WAIT_S = 0
        old = sys.argv; sys.argv = ["killswitch.py", *argv]
        try: ks.main()
        finally: sys.argv = old
        return ks
    def test_fire_cancels_before_close_and_persists(self):
        f = self.f; f.equity, f.last_equity = 95000.0, 100000.0
        f.positions = [Pos("AAPL", 10, 100)]; f.open_orders = [object()]
        self.run_ks()
        self.assertIn("cancel_orders", f.calls); self.assertIn("close_all", f.calls)
        self.assertLess(f.calls.index("cancel_orders"), f.calls.index("close_all"))
        gi = [i for i, c in enumerate(f.calls) if c == "get_orders"]
        self.assertTrue(gi and gi[0] < f.calls.index("close_all"), "open orders verified empty before closing")
        self.assertTrue(os.path.exists(self.ac.KILL)); self.assertTrue(os.path.exists(f"{self.tmp}/logs/alp_kill.jsonl"))
        self.assertTrue(self.ac.kill_active())
    def test_no_fire_above_limit(self):
        f = self.f; f.equity, f.last_equity = 97000.0, 100000.0
        self.run_ks(); self.assertNotIn("close_all", f.calls); self.assertFalse(self.ac.kill_active())
    def test_dry_run_and_simulate_never_close(self):
        f = self.f; f.equity, f.last_equity = 90000.0, 100000.0
        self.run_ks(["--dry-run"]); self.run_ks(["--simulate-drop", "5"])
        self.assertNotIn("close_all", f.calls); self.assertNotIn("cancel_orders", f.calls); self.assertFalse(self.ac.kill_active())
    def test_state_fail_closed_and_journal_recovery(self):
        ac = self.ac
        ac.write_kill({"date": ac.ny_today(), "fired_at": "t"}); self.assertTrue(ac.kill_active())
        os.remove(ac.KILL); self.assertTrue(ac.kill_active(), "deleted state -> journal")
        open(ac.KILL, "w").write("{corrupt"); self.assertTrue(ac.kill_active(), "corrupt -> fail closed")
        os.remove(ac.KILL); os.remove(f"{self.tmp}/logs/alp_kill.jsonl"); self.assertFalse(ac.kill_active())
        ac.write_json(ac.KILL, {"date": "2000-01-01"}); self.assertFalse(ac.kill_active(), "old day does not block")
        open(ac.KILL, "w").write("[1,2]"); self.assertTrue(ac.kill_active())

class SleevesRespectKill(unittest.TestCase):
    def setUp(self):
        self.ac, self.f, self.tmp = iso(); lists(self.tmp, ["AAA", "BBB"], ["CCC"])
        self.ac.write_kill({"date": self.ac.ny_today(), "fired_at": "t"})
    def test_stocks_crypto_no_submit(self):
        load("stocks", self.ac, self.tmp).main(); load("crypto", self.ac, self.tmp).main()
        self.assertEqual(self.f.orders, [])
    def test_submit_block_reason(self):
        self.assertTrue(self.ac.submit_block_reason("buy")); self.assertTrue(self.ac.submit_block_reason("sell"))
    def test_strategy_no_submit(self):
        import alpaca.trading.client as tcm, alpaca.data.historical as dh
        o1, o2 = tcm.TradingClient, dh.StockHistoricalDataClient
        tcm.TradingClient = lambda *a, **k: self.f; dh.StockHistoricalDataClient = lambda *a, **k: None
        try:
            _front(); st = importlib.import_module("strategy"); _front(); importlib.reload(st)
        finally: tcm.TradingClient, dh.StockHistoricalDataClient = o1, o2
        import alp_common; st.ac = self.ac; st.trade = self.f; st.DRY = False; st.want = lambda have: "TQQQ"
        st.run(); self.assertEqual(self.f.orders, [])
        # kill fires between the start check and the submit -> still blocked
        os.remove(self.ac.KILL); os.remove(f"{self.tmp}/logs/alp_kill.jsonl"); calls = iter([False] + [True] * 50)
        real = self.ac.kill_active; self.ac.kill_active = lambda: next(calls)
        try: st.run()
        finally: self.ac.kill_active = real
        self.assertEqual(self.f.orders, [])

class StopAll(unittest.TestCase):
    def setUp(self): self.ac, self.f, self.tmp = iso()
    def test_blocks_buys_not_sells(self):
        lists(self.tmp, ["AAA"], ["BBB"]); self.f.positions = [Pos("ZZZ", 10, 100)]     # ZZZ off both lists -> sell
        open(f"{self.tmp}/STOP_ALL", "w").close()
        load("stocks", self.ac, self.tmp).main()
        self.assertTrue(self.f.orders and all(side(o) == "sell" for o in self.f.orders))
        self.assertIsNone(self.ac.submit_block_reason("sell")); self.assertTrue(self.ac.submit_block_reason("buy"))
        self.f.orders = []; load("crypto", self.ac, self.tmp).main(); self.assertEqual(self.f.orders, [])

class StocksCaps(unittest.TestCase):
    def setUp(self): self.ac, self.f, self.tmp = iso()
    def test_name_cap_trims_inside_tolerance(self):
        # 6 names, budget 50k -> per = min(8.33k, 10k). Held AAA at 10.4k: inside the 25% tolerance (|diff| 2.07k < 2.08k) but > 10% cap -> trim
        lists(self.tmp, ["AAA", "BBB", "CCC"], ["DDD", "EEE", "FFF"]); self.f.positions = [Pos("AAA", 104, 100)]; self.f.px = {"AAA": 100}
        load("stocks", self.ac, self.tmp).main()
        sells = [o for o in self.f.orders if o.symbol == "AAA" and side(o) == "sell"]
        self.assertEqual(len(sells), 1); self.assertGreater(float(sells[0].qty), 0)
    def test_no_trim_when_under_cap_inside_tolerance(self):
        lists(self.tmp, ["AAA", "BBB", "CCC"], ["DDD", "EEE", "FFF"]); self.f.positions = [Pos("AAA", 95, 100)]; self.f.px = {"AAA": 100}
        load("stocks", self.ac, self.tmp).main()
        self.assertEqual([o for o in self.f.orders if o.symbol == "AAA"], [])
    def test_new_buys_capped_10pct_and_16_names(self):
        lists(self.tmp, [f"D{i:02d}" for i in range(20)], [f"I{i:02d}" for i in range(20)])
        load("stocks", self.ac, self.tmp).main()
        buys = [o for o in self.f.orders if side(o) == "buy"]
        self.assertEqual(len(buys), 16); self.assertTrue(all(float(o.notional) <= 0.10 * self.f.equity + 1e-6 for o in buys))
        lists(self.tmp, ["AAA"], []); self.f.orders = []
        load("stocks", self.ac, self.tmp).main()
        self.assertTrue(all(float(o.notional) <= 0.10 * self.f.equity + 1e-6 for o in self.f.orders if side(o) == "buy"))
    def test_no_averaging_down(self):
        lists(self.tmp, ["AAA", "BBB"], []); self.f.positions = [Pos("AAA", 50, 80, avg=100)]; self.f.px = {"AAA": 80, "BBB": 50}
        load("stocks", self.ac, self.tmp).main()
        self.assertEqual([o for o in self.f.orders if o.symbol == "AAA" and side(o) == "buy"], [])
        self.assertTrue([o for o in self.f.orders if o.symbol == "BBB" and side(o) == "buy"], "new names still bought")
    def test_top_up_allowed_when_in_profit(self):
        lists(self.tmp, ["AAA", "BBB"], []); self.f.positions = [Pos("AAA", 50, 120, avg=100)]; self.f.px = {"AAA": 120, "BBB": 50}
        load("stocks", self.ac, self.tmp).main()
        self.assertTrue([o for o in self.f.orders if o.symbol == "AAA" and side(o) == "buy"])

if __name__ == "__main__":
    unittest.main()
