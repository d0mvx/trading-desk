"""quant_dial FRED fetch (2026-10-21): HTML maintenance page must not parse; fallbacks + cache keep age rules. No network."""
import os, sys, json, tempfile, unittest, importlib
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HTML = "<!doctype html>\n<html lang=\"en\">\n<head>\n<title>Site Maintenance | St. Louis Fed</title>\n<p>a, b, c</p>\n</html>"
CSV = "observation_date,VIXCLS\n2026-10-15,20.1\n2026-10-16,.\n2026-10-19,18.44\n"

class FredFetch(unittest.TestCase):
    def setUp(self):
        import quant_dial; self.q = importlib.reload(quant_dial)
        self.tmp = tempfile.mkdtemp(); self.q.FRED_CACHE = self.tmp
    def test_html_maintenance_page_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "non-CSV.*maintenance"):
            self.q.parse_fred_csv(HTML, "VIXCLS")
    def test_valid_csv_parses_and_drops_missing(self):
        s = self.q.parse_fred_csv(CSV, "VIXCLS")
        self.assertEqual(len(s), 2); self.assertEqual(float(s.iloc[-1]), 18.44)
    def test_wrong_series_csv_rejected(self):
        with self.assertRaises(RuntimeError):
            self.q.parse_fred_csv(CSV, "WALCL")
    def test_fallback_then_cache(self):
        q = self.q
        def down(series): raise RuntimeError("non-CSV response from fredgraph.csv (FRED maintenance page)")
        q.src_fredgraph = down; q.src_fred_api = down
        good = q.parse_fred_csv(CSV, "VIXCLS")
        q.FALLBACKS["VIXCLS"] = [("cboe", lambda s: good)]
        s = q.fred("VIXCLS"); self.assertEqual(q.SOURCES["VIXCLS"], "cboe"); self.assertTrue(s.equals(good))
        q.FALLBACKS["VIXCLS"] = [("cboe", down)]        # every live source down -> last good cache
        s2 = q.fred("VIXCLS"); self.assertTrue(q.SOURCES["VIXCLS"].startswith("cache(cboe"))
        self.assertEqual(list(s2.index), list(good.index)); self.assertEqual(list(s2.values), list(good.values))
    def test_all_down_no_cache_raises(self):
        q = self.q
        def down(series): raise RuntimeError("down")
        q.src_fredgraph = down; q.src_fred_api = down; q.FALLBACKS["BAMLH0A0HYM2"] = []
        with self.assertRaisesRegex(RuntimeError, "all sources failed"):
            q.fred("BAMLH0A0HYM2")
    def test_age_thresholds_unchanged(self):
        self.assertEqual(self.q.MAX_AGE_H, {"WALCL": 240, "WTREGEN": 240, "RRPONTSYD": 120, "VIXCLS": 120, "BAMLH0A0HYM2": 120,
                                            "BTC/USD": 48, "SOL/USD": 48, "ETH/USD": 48, "QQQ": 120})

if __name__ == "__main__":
    unittest.main()
