"""2026-10-20: 215nhc, 2026-10-21: EwJYY4 are OBSERVE-only (not copyable) -> their buys must never appear in wallet_signal.json "mints"."""
import os, sys, json, time, tempfile, unittest, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("WS_SRC") or os.path.join(os.path.dirname(HERE), "scan", "wallet_signal.py")
W215, WEWJ = "215nhcAHjQQGgwpQSJQ7zR26etbjjtVdW74NLzwEgQjP", "EwJYY4q2rcrdEH26doRbYX9JxbpYPSNZvRLgzhPKi418"
def tx(w, mint, ts):
    return {"blockTime": ts, "meta": {"err": None, "preBalances": [2_000_000_000], "postBalances": [1_000_000_000],
            "preTokenBalances": [], "postTokenBalances": [{"owner": w, "mint": mint, "uiTokenAmount": {"uiAmount": 1000.0}}]},
            "transaction": {"message": {"accountKeys": [{"pubkey": w, "signer": True}]}}}
class Observe(unittest.TestCase):
    def test_215n_not_in_mints(self):
        spec = importlib.util.spec_from_file_location("ws_t", SRC); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        d = tempfile.mkdtemp(); m.OUT, m.STATE = f"{d}/o.json", f"{d}/s.json"; m.DRY = False; m.T0 = time.time()
        now = int(time.time())
        def rpc(method, params, errs):
            if method == "getSignaturesForAddress": return [{"signature": "S" + params[0][:4], "blockTime": now - 60}]
            w = W215 if params[0] == "S215n" else WEWJ
            return tx(w, "MINT215" if w == W215 else "MINTEWJ", now - 60)
        m.rpc = rpc; m.sol_usd = lambda st: 150.0
        for w in (W215, WEWJ): self.assertNotIn(w, m.WALLETS); self.assertIn(w, m.OBSERVE)
        m.main(); o = json.load(open(m.OUT))
        self.assertEqual(o["mints"], {}); self.assertEqual(o["of"], 0)
        self.assertIn("MINT215", o["observe_mints"]); self.assertIn("MINTEWJ", o["observe_mints"])
if __name__ == "__main__": unittest.main()
