"""Rule 1 (position cap on TOTAL exposure per token, no re-buys / averaging) and rule 5 (max open: main 3, new pairs 2,
overall 4) - tested on meme.book_add, the single locked path through which the main pipeline (incl. dip-watchlist buys)
and newpairs add positions, including under truly concurrent processes."""
import os, sys, json, re, unittest, multiprocessing as mp
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos, DESK

class Caps(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme()
        self.m.meme_state = lambda p=None: {"equity": 100.0, "cash": 100.0}
    def test_no_rebuy_same_token_or_pool_any_sleeve(self):
        m = self.m
        self.assertIsNone(m.book_add(pos("AAA"), m.MAX_OPEN, m.TICKET_PCT))
        self.assertIn("already held", m.book_add(pos("AAA"), m.MAX_OPEN, m.TICKET_PCT))                       # re-buy
        self.assertIn("already held", m.book_add(pos("AAA", sleeve="newpairs"), 2, 0.015))                     # other sleeve
        self.assertIn("already held", m.book_add(pos("ZZZ", pool="PAAA"), m.MAX_OPEN, m.TICKET_PCT))           # same pool
        p = json.load(open(m.POS)); p["open"][0]["qty"] /= 2; p["open"][0]["tp_hits"] = [0.5]; json.dump(p, open(m.POS, "w"))
        self.assertIn("already held", m.book_add(pos("AAA"), m.MAX_OPEN, m.TICKET_PCT))                       # after partial TP
        self.assertEqual(len(json.load(open(m.POS))["open"]), 1)
    def test_graduated_pool_original_counts(self):
        m = self.m; m.book_add(pos("BBB", pool="NEWPOOL", pool_original="CURVE1"), m.MAX_OPEN, m.TICKET_PCT)
        self.assertIn("already held", m.book_add(pos("CCC", pool="CURVE1"), m.MAX_OPEN, m.TICKET_PCT))
    def test_ticket_cap(self):
        m = self.m
        self.assertIn("cap", m.book_add(pos("DDD", cost=m.FIXED_TICKET_USD + 0.5), m.MAX_OPEN, 0.03))      # fixed 10 EUR cap
        self.assertIsNone(m.book_add(pos("DDD", cost=m.FIXED_TICKET_USD), m.MAX_OPEN, 0.03))
        self.assertIn("cap", m.book_add(pos("EEE", sleeve="newpairs", cost=m.FIXED_TICKET_USD + 1.0), 2, 0.015))
    def test_sequential_caps(self):
        m = self.m
        r = [m.book_add(pos(f"M{i}"), m.MAX_OPEN, m.TICKET_PCT) for i in range(10)]
        self.assertEqual(sum(x is None for x in r), 8)
        r = [m.book_add(pos(f"N{i}", sleeve="newpairs", cost=1.0), 2, 0.015) for i in range(3)]
        self.assertEqual(sum(x is None for x in r), 2)       # new pairs max 2; total 10 reached
        self.assertEqual(len(json.load(open(m.POS))["open"]), 10)
    def test_constants(self):
        import newpairs
        self.assertEqual((self.m.MAX_OPEN, self.m.TOTAL_MAX_OPEN, newpairs.NP_MAX_OPEN, newpairs.TOTAL_MAX_OPEN), (8, 10, 2, 10))
    def test_only_book_add_appends_positions(self):
        """Structural: no code path appends to the real book except book_add (so no path can skip the checks)."""
        hits = []
        for fn in ("meme.py", "newpairs.py", "scan.py", "shadow.py", "wallet_signal.py", "scan/wallet_signal.py"):
            p = f"{DESK}/{fn}"
            if not os.path.exists(p): continue
            src = open(p).read()
            if fn == "shadow.py": continue   # shadow book is a separate file (shadow_positions.json)
            for mm in re.finditer(r'p\["open"\]\.append\(', src):
                line = src[:mm.start()].count("\n") + 1; hits.append((fn, line))
        src = open(f"{DESK}/meme.py").read(); a = src.index("def book_add"); b = src.index("\ndef ", a + 5)
        a_line, b_line = src[:a].count("\n") + 1, src[:b].count("\n") + 1
        self.assertEqual([h for h in hits if not (h[0] == "meme.py" and a_line <= h[1] <= b_line)], [])

def _worker(args):
    tmp, tok, sleeve = args
    sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos
    m, _ = iso_meme(); m.DESK = tmp
    m.POS, m.POS_LOCK, m.TRADES, m.RISKST, m.RISK_JOURNAL = f"{tmp}/meme_positions.json", f"{tmp}/.pos.lock", f"{tmp}/logs/t.jsonl", f"{tmp}/risk_state.json", f"{tmp}/logs/rs.jsonl"
    m.meme_state = lambda p=None: {"equity": 100.0, "cash": 100.0}
    import time; time.sleep(0.2)
    o = pos(tok, sleeve=sleeve, cost=1.0)
    return m.book_add(o, m.MAX_OPEN if sleeve == "main" else 2, m.TICKET_PCT if sleeve == "main" else 0.015)

class Concurrent(unittest.TestCase):
    def test_concurrent_processes_respect_caps(self):
        m, tmp = iso_meme()
        jobs = [(tmp, f"T{i}", "main") for i in range(8)] + [(tmp, f"T{i}", "main") for i in range(4)] + [(tmp, f"Q{i}", "newpairs") for i in range(6)]
        with mp.get_context("fork").Pool(18) as pl: res = pl.map(_worker, jobs)
        book = json.load(open(m.POS))["open"]
        main = [o for o in book if o.get("sleeve", "main") == "main"]; np_ = [o for o in book if o.get("sleeve") == "newpairs"]
        self.assertLessEqual(len(main), 8); self.assertLessEqual(len(np_), 2); self.assertLessEqual(len(book), 10)
        self.assertEqual(len({o["token"] for o in book}), len(book))          # never two positions in one coin
        self.assertEqual(sum(r is None for r in res), len(book))             # every 'added' is really in the book

if __name__ == "__main__": unittest.main()
