"""USER ORDER 2026-10-23 19:15/19:23 (Dominic), standing rule: every meme bank reset starts at the live price of 1 SOL in EUR
(bank stays EUR, SOL/EUR price recorded; no quote -> abort). New epoch (archive old epoch, keep history/learner/shadow),
run once on the GitHub runner (--once / reset_order). Ticket 10 EUR and caps unchanged; sizing caps the ticket at free cash."""
import os, sys, json, unittest, importlib
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos
import scan

BANK2 = {"start_capital": 112.15, "currency": "USD", "started": "2026-10-21", "started_at": "2026-10-21T20:21:21+02:00",
         "sleeves": {"meme": {"weight": 1.0}}, "epochs": [{"epoch": 1, "start_usd": 100.0}], "start_eur": 100.0, "eurusd": 1.1215, "epoch": 2}

class BankReset1SolEur(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme()
        import bank_reset; importlib.reload(bank_reset); bank_reset.meme = self.m; bank_reset.DESK = self.tmp; self.br = bank_reset
        json.dump(BANK2, open(f"{self.tmp}/bank.json", "w"))
        open(f"{self.tmp}/history.csv", "w").write("timestamp_berlin,desk_equity,desk_cash,realized,unrealized\nx,57.26,57.26,-54.9,0\n")
        c = {**pos("C"), "pnl": -54.89, "exit_reason": "stop-loss"}
        json.dump({"open": [], "closed": [c]}, open(self.m.POS, "w"))

    def run_reset(self, **kw):
        return self.br.main(order="2026-10-23 19:23", once=True, price_fn=lambda: (93.26, "coingecko+kraken"), **kw)

    def test_new_epoch_3_one_sol(self):
        prev = self.run_reset()
        b = json.load(open(f"{self.tmp}/bank.json"))
        self.assertEqual(b["epoch"], 3); self.assertNotIn("bank_unit", b); self.assertEqual(b["sol_eur_start"], 93.26)
        self.assertEqual(b["start_eur"], 93.26); self.assertEqual(b["start_capital"], 104.59)          # 93.26 EUR x 1.1215
        self.assertEqual(b["reset_order"], "2026-10-23 19:23")
        self.assertEqual(len(b["epochs"]), 2); self.assertEqual(b["epochs"][1]["epoch"], 2); self.assertEqual(b["epochs"][1]["closed_trades"], 1)
        arch = json.load(open(f"{self.tmp}/{prev['archive']}")); self.assertEqual(len(arch["closed"]), 1)   # old book archived, not deleted
        self.assertTrue(os.path.exists(f"{self.tmp}/{prev['history']}"))
        self.assertIn("104.5900", open(f"{self.tmp}/history.csv").read())
        ms = self.m.meme_state(); self.assertEqual(ms["equity"], 104.59); self.assertEqual(ms["cash"], 104.59)
        rs = json.load(open(self.m.RISKST)); self.assertEqual(rs["day_open_equity"], 104.59); self.assertTrue(rs["epoch_reset"])

    def test_once_is_idempotent(self):
        self.run_reset(); self.assertIsNone(self.run_reset())
        self.assertEqual(json.load(open(f"{self.tmp}/bank.json"))["epoch"], 3)

    def test_open_position_closed_and_reset_cooldown_dropped(self):
        o = pos("O", cost=11.21, price=1.0, sol_usd=104.6)
        p = json.load(open(self.m.POS)); p["open"].append(o); json.dump(p, open(self.m.POS, "w"))
        self.m.ds_prices = lambda ps, timeout=10: {"PO": {"base_token_price_usd": 0.9, "quote_token_price_usd": 104.6, "liquidity_usd": 50000}}
        self.run_reset()
        p = json.load(open(self.m.POS)); self.assertEqual(p["open"], []); self.assertEqual(p["closed"], [])
        b = json.load(open(f"{self.tmp}/bank.json")); self.assertEqual(b["epochs"][1]["closed_trades"], 2)
        cd = json.load(open(scan.COOLDOWN_FILE)) if os.path.exists(scan.COOLDOWN_FILE) else {}
        self.assertFalse([k for k, v in cd.items() if v["reason"].startswith("reset:")])

    def test_no_quote_aborts_without_change(self):
        def boom(): raise RuntimeError("no quote")
        with self.assertRaises(RuntimeError): self.br.main(order="x", once=True, price_fn=boom)
        self.assertEqual(json.load(open(f"{self.tmp}/bank.json"))["epoch"], 2)

    def test_sol_eur_median_sanity_and_abort(self):
        def f(url):
            if "coingecko" in url: return {"solana": {"eur": 93.3}}
            return {"error": [], "result": {"SOLEUR": {"c": ["93.2", "1"]}}}
        self.assertEqual(self.br.sol_eur(f), (93.25, "coingecko+kraken"))
        def bad(url):
            if "coingecko" in url: return {"solana": {"eur": 99999}}
            raise OSError("down")
        with self.assertRaises(RuntimeError): self.br.sol_eur(bad)

    def test_ticket_and_caps_unchanged_and_bank_funds(self):
        m = self.m
        self.assertEqual(m.FIXED_TICKET_EUR, 10.0); self.assertEqual(m.MAX_OPEN, 10); self.assertEqual(m.TOTAL_MAX_OPEN, 10)   # USER ORDER 2026-10-24 13:57: one shared pool of 10
        self.run_reset()
        per = m.FIXED_TICKET_USD + m.ATA_RENT_SOL * 104.6          # cash locked per full position (ticket incl. fees + refundable rent)
        self.assertEqual(int(104.59 // per), 9)  # 1 SOL (93.26 EUR) funds 9 full 10-EUR tickets; the 10th slot gets the cash left (size_ticket) or is skipped (< MIN_TICKET)
        # cash-limited sizing: book_add never lets cost exceed max(fixed ticket, pct x equity); pipeline caps ticket at free cash
        p = json.load(open(m.POS)); p["open"] = [pos(f"F{i}", cost=12.0, rent_usd=0.0) for i in range(8)]; json.dump(p, open(m.POS, "w"))
        self.assertLess(m.meme_state()["cash"], m.FIXED_TICKET_USD)
