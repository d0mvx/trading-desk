"""STEP 13: $200 -> $16; bump -> $47.50; skip skips + warning; $40k liquidity caps at $800 (2%)."""
from desk import config
from desk.agents import executor

def test_sizes(tdb):
    s = config.all_settings()
    assert s["executor.below_min"] == "off"
    assert executor.size_for(200, 200, None, s)[0] == 16
    s2 = dict(s, **{"executor.below_min": "bump"}); assert executor.size_for(200, 200, None, s2)[0] == 47.50
    s3 = dict(s, **{"executor.below_min": "skip"}); sz, why, _ = executor.size_for(200, 200, None, s3); assert sz is None and why.startswith("under $47.50")
    assert executor.size_for(1_000_000, 1_000_000, 40_000, s)[:3:2] == (800, "max_pool_pct")

def test_ticket_warnings(tdb):
    assert config.ticket_check() is None                      # off (approved default)
    config.set("executor.below_min", "skip", "t")
    assert config.ticket_check() == "every coin will be skipped, stack under $593.75. Switch below_min to bump or raise the stack."
    config.set("executor.below_min", "bump", "t")
    assert config.ticket_check() == "tickets bumped to $47.50 = 23.8% of stack"
