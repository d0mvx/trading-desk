"""2026-10-22 USER ORDER: DexScreener is the primary meme-scan data source (data source change only, no rule change).
Field-mapping parity on a same-moment fixture (GeckoTerminal pool + DexScreener pair for the same pool, box parity run):
  * ds_to_gt maps every DexScreener field 1:1 into the GeckoTerminal shape scan.evaluate reads
  * fields DexScreener lacks (txns m15, unique buyers, price change m15/m30) stay missing -> GT overlay only
  * scan.evaluate gives the SAME pass/fail decision on GT data and on DexScreener+GT-overlay data
  * ds_collect enriches only gate-passers with <= 1 GeckoTerminal call; missing m15 = same gate fails (never a pass)"""
import os, sys, json, copy, unittest, datetime as dt
from unittest import mock
DESK = os.path.expanduser("~/.desk"); sys.path.insert(0, DESK)
import scan, sources
FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "ds_gt_parity.json")))
NOW = dt.datetime.fromisoformat(FX["captured_at"])
WSOL = "So11111111111111111111111111111111111111112"

def ev(p):
    s = sorted(float(x["attributes"]["quote_token_price_usd"]) for x in [p] if x["attributes"].get("quote_token_price_usd"))
    scan.SOL_FALLBACK[0] = s[0] if s else None
    return scan.evaluate(p, NOW)

class Mapping(unittest.TestCase):
    def setUp(self):
        from _iso import legacy_filters; legacy_filters(self)   # 13:57: scan filters are off by default -> legacy behaviour under test
    def test_fixture_has_passers_and_failers(self):
        res = [not ev(copy.deepcopy(x["gt"]))[0]["fail_keys"] for x in FX["pairs"]]
        self.assertGreaterEqual(sum(res), 5); self.assertGreaterEqual(len(res) - sum(res), 5)

    def test_fields_map_one_to_one(self):
        for x in FX["pairs"]:
            d = x["ds"]; g = sources.ds_to_gt(d); a = g["attributes"]
            self.assertEqual(g["id"], "solana_" + d["pairAddress"]); self.assertEqual(a["address"], d["pairAddress"])
            self.assertEqual(a["reserve_in_usd"], (d.get("liquidity") or {}).get("usd"))                  # liquidity
            for w in ("h1", "h6", "h24"): self.assertEqual(a["volume_usd"].get(w), (d.get("volume") or {}).get(w))   # volume
            self.assertEqual(a["market_cap_usd"], d.get("marketCap")); self.assertEqual(a["fdv_usd"], d.get("fdv"))  # mcap/fdv
            for w in ("h1", "h6", "h24"):                                                                      # txns per window
                t = (d.get("txns") or {}).get(w)
                if t: self.assertEqual((a["transactions"][w]["buys"], a["transactions"][w]["sells"]), (t["buys"], t["sells"]))
            self.assertEqual(dt.datetime.fromisoformat(a["pool_created_at"]).timestamp() * 1000, d["pairCreatedAt"])  # pair age
            for w, v in (d.get("priceChange") or {}).items(): self.assertEqual(a["price_change_percentage"][w], v)   # price change
            self.assertAlmostEqual(a["base_token_price_usd"], float(d["priceUsd"]))
            self.assertAlmostEqual(a["quote_token_price_usd"], float(d["priceUsd"]) / float(d["priceNative"]))     # SOL/USD
            self.assertEqual(g["relationships"]["dex"]["data"]["id"], {"pumpfun": "pump-fun", "pumpswap": "pumpswap"}[d["dexId"]])
            self.assertEqual(g["relationships"]["quote_token"]["data"]["id"], "solana_" + d["quoteToken"]["address"])
            # no exact DexScreener equivalent -> left out (GT overlay only)
            self.assertNotIn("m15", a["transactions"]); self.assertNotIn("m15", a["price_change_percentage"]); self.assertNotIn("m30", a["price_change_percentage"])
            self.assertFalse(any("buyers" in t for t in a["transactions"].values()))

    def test_overlay_copies_only_gt_only_fields(self):
        for x in FX["pairs"]:
            g0 = sources.ds_to_gt(x["ds"]); g = sources.gt_overlay(copy.deepcopy(g0), x["gt"]); a, ga = g["attributes"], x["gt"]["attributes"]
            for k in ("reserve_in_usd", "volume_usd", "market_cap_usd", "fdv_usd", "base_token_price_usd", "pool_created_at"):
                self.assertEqual(a[k], g0["attributes"][k], k)                                                 # DexScreener stays
            self.assertEqual(a["transactions"]["m15"], ga["transactions"]["m15"])                              # GT-only
            for w in ("h1", "h6", "h24"):
                self.assertEqual(a["transactions"][w]["buyers"], ga["transactions"][w]["buyers"])
                self.assertEqual(a["transactions"][w]["buys"], g0["attributes"]["transactions"][w]["buys"])
            for w in ("m15", "m30"): self.assertEqual(a["price_change_percentage"].get(w), ga["price_change_percentage"].get(w))

    def test_same_decision_gt_vs_dexscreener(self):
        for x in FX["pairs"]:
            c_gt, _ = ev(copy.deepcopy(x["gt"])); c_ds, _ = ev(sources.gt_overlay(sources.ds_to_gt(x["ds"]), x["gt"]))
            self.assertEqual(bool(c_gt["fail_keys"]), bool(c_ds["fail_keys"]), f"{c_gt['name']}: GT {c_gt['fail_keys']} vs DS {c_ds['fail_keys']}")
            self.assertEqual(c_gt["venue"], c_ds["venue"]); self.assertEqual(c_gt["base_token"], c_ds["base_token"])
            self.assertAlmostEqual(c_gt["age_h"], c_ds["age_h"], delta=0.05)
            if not c_gt["fail_keys"]:   # passers: Judge inputs come through (buyers from GT, m15 from GT, pc h1 present)
                self.assertEqual(c_ds["buyers_h1"], c_gt["buyers_h1"]); self.assertEqual(c_ds["tx_m15"], c_gt["tx_m15"])
                self.assertIsNotNone(c_ds["pc_h1"]); self.assertEqual(c_ds["data"], "dexscreener+gt")

    def test_missing_m15_is_the_same_gate_failing(self):
        x = next(x for x in FX["pairs"] if not ev(copy.deepcopy(x["gt"]))[0]["fail_keys"])
        c, why = ev(sources.ds_to_gt(x["ds"]))
        self.assertEqual(c["fail_keys"], [f"buys m15 < {scan.RULES['min_buys_m15']}"]); self.assertTrue(c["m15_na"])
        self.assertIn("n/a", why[0]); self.assertIsNone(c["buyers_h1"] or None)

    def test_thresholds_unchanged(self):
        # 2026-10-28: these are the CODE base values. The self-learner (learner_overrides.json, bounded + gated) may legitimately tighten
        # scan.RULES.* at runtime (e.g. pumpswap.mcap_min 40k -> 50k on 27.10.) and the runner imports that state before the pre-start
        # tests; comparing the live dict made every run fail. Compare the pre-override base values captured by learner.apply() instead.
        import learner
        for n, v in learner.BASE.items():
            spec = learner.PARAMS.get(n)
            if spec and spec["mod"] == "scan": learner._set(vars(scan), spec["path"], v)   # back to the code value, in place
        self.assertEqual(scan.RULES["bonding_curve"], {"age_min_h": 0.25, "age_max_h": 72, "mcap_min": 15_000, "mcap_max": 90_000, "vol24_min": 20_000, "liq_min": 5_000, "max_vol24_to_liq": 100})
        self.assertEqual(scan.RULES["pumpswap"], {"age_min_h": 0.25, "age_max_h": 72, "mcap_min": 40_000, "mcap_max": 8_000_000, "vol24_min": 40_000, "liq_min": 12_000, "max_vol24_to_liq": 40})
        self.assertEqual((scan.RULES["min_buys_h1"], scan.RULES["min_buys_m15"], scan.RULES["max_out"]), (10, 2, 60))

class Collect(unittest.TestCase):
    def setUp(self):
        from _iso import legacy_filters; legacy_filters(self)   # 13:57: scan filters are off by default -> legacy behaviour under test
    def test_ds_collect_one_gt_call_only_for_passers(self):
        pairs = [x["ds"] for x in FX["pairs"]]; gtp = {x["gt"]["attributes"]["address"]: x["gt"] for x in FX["pairs"]}
        def fake_get(url, params=None):
            if "/latest/dex/search" in url: return {"pairs": pairs if params["q"] == "pumpswap" else []}
            if "/tokens/v1/" in url: return []
            return []
        calls = []
        def fake_gt(path, params=None, deadline=None):
            addrs = path.rsplit("/", 1)[1].split(","); calls.append(addrs)
            return {"data": [copy.deepcopy(gtp[a]) for a in addrs if a in gtp]}
        with mock.patch.object(sources, "_get", fake_get), mock.patch.object(sources.gt, "get", fake_gt), \
             mock.patch.object(sources, "load_wallet_signal", lambda: {}), mock.patch.object(scan, "cooldown_active", lambda at=None: {}), \
             mock.patch.object(sources.time, "time", lambda: NOW.timestamp()):
            pools, n, errs, st = scan.ds_collect(NOW, {}, NOW.timestamp() + 40)
        self.assertEqual(n, 1); self.assertEqual(len(calls), 1); self.assertLessEqual(len(calls[0]), sources.GT_ENRICH_MAX)
        want_pass = {a for a, g in gtp.items() if not ev(copy.deepcopy(g))[0]["fail_keys"]}
        self.assertTrue(want_pass <= set(calls[0]), "every GT passer must be enriched")
        got_pass = {p["attributes"]["address"] for p in pools.values() if not ev(p)[0]["fail_keys"]}
        self.assertEqual(got_pass, want_pass)

    def test_gt_enrich_failure_never_creates_a_pass(self):
        pairs = [x["ds"] for x in FX["pairs"]]
        def boom(*a, **k): raise RuntimeError("GeckoTerminal 429")
        with mock.patch.object(sources, "_get", lambda url, params=None: {"pairs": pairs} if "search" in url else []), \
             mock.patch.object(sources.gt, "get", boom), mock.patch.object(sources, "load_wallet_signal", lambda: {}), \
             mock.patch.object(scan, "cooldown_active", lambda at=None: {}), mock.patch.object(sources.time, "time", lambda: NOW.timestamp()):
            pools, n, errs, st = scan.ds_collect(NOW, {}, NOW.timestamp() + 40)
        self.assertTrue(any("gt enrich" in e for e in errs))
        self.assertFalse([p for p in pools.values() if not ev(p)[0]["fail_keys"]])

if __name__ == "__main__": unittest.main()
