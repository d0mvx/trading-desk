"""STOP ALL switch: a ~/.desk/STOP_ALL file blocks every new paper buy (meme main + new pairs via meme.book_add; Alpaca buys via
alp_common.submit_block_reason). Exits are NOT blocked. Isolated temp dirs, no network."""
import os, sys, json, unittest
sys.path.insert(0, os.path.dirname(__file__)); from _iso import iso_meme, pos

class StopAllMeme(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = iso_meme(); self.m.meme_state = lambda p=None: {"equity": 100.0, "cash": 100.0}
    def test_blocks_book_add(self):
        m = self.m; open(f"{self.tmp}/STOP_ALL", "w").close()
        self.assertIn("STOP_ALL", m.book_add(pos("X", cost=1.0), m.MAX_OPEN, m.TICKET_PCT))
        self.assertIn("STOP_ALL", m.book_add(pos("Y", sleeve="newpairs", cost=1.0), 2, 0.015))
        self.assertEqual(json.load(open(m.POS))["open"], [])
    def test_removed_file_allows_again(self):
        m = self.m; open(f"{self.tmp}/STOP_ALL", "w").close(); os.remove(f"{self.tmp}/STOP_ALL")
        self.assertIsNone(m.book_add(pos("X", cost=1.0), m.MAX_OPEN, m.TICKET_PCT))

if __name__ == "__main__":
    unittest.main()
