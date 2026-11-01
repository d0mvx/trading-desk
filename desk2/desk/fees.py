"""Fee + slippage model for PAPER PnL (pump.fun canonical PumpSwap pools).

Sources (read 2026-11-01):
  * https://pump.fun/docs/fees  (last updated 17 Oct 2026): canonical-pool fees are tiered by the coin's
    SOL market cap (price in SOL x 1B tokens). Table below = creator + protocol + LP, per swap, each side.
    0-420 SOL mcap: 1.25% total, then 1.20% ... down to 0.30% at >= 98,240 SOL.
  * docs.rs pump-swap-sdk FeeConfig: pump-amm picks the tier by market_cap_lamports, highest threshold <= mcap;
    the base rung is 125 bps; non-canonical pools use flat 30 bps.
Slippage (assumption, documented): constant-product price impact on the quote side of the pool
(liquidity_usd / 2) for our size, plus fees.extra_slippage_pct per side for latency / MEV on fast memecoins,
plus Solana network + priority fee fees.gas_sol_per_side. PAPER fills stay at the signal/polled price
(STEP 6) and these costs are booked in positions.fees_usd.
"""
from __future__ import annotations

# (min SOL market cap, total fee %)
SOL_TIERS = [(0, 1.25), (420, 1.20), (1470, 1.15), (2460, 1.10), (3440, 1.05), (4420, 1.00), (9820, 0.95),
             (14740, 0.90), (19650, 0.85), (24560, 0.80), (29470, 0.75), (34380, 0.70), (39300, 0.65),
             (44210, 0.60), (49120, 0.55), (54030, 0.525), (58940, 0.50), (63860, 0.475), (68770, 0.45),
             (73681, 0.425), (78590, 0.40), (83500, 0.375), (88400, 0.35), (93330, 0.325), (98240, 0.30)]
SOURCE = "https://pump.fun/docs/fees"

def fee_pct(mcap_sol: float | None) -> float:
    if mcap_sol is None:
        return SOL_TIERS[0][1]          # unknown -> worst (base) rung, never under-charge
    pct = SOL_TIERS[0][1]
    for lo, p in SOL_TIERS:
        if mcap_sol >= lo:
            pct = p
    return pct

def side_cost(size_usd: float, liquidity_usd: float | None, mcap_usd: float | None, sol_usd: float | None,
              gas_sol: float = 0.0005, extra_slip_pct: float = 0.5) -> dict:
    mcap_sol = (mcap_usd / sol_usd) if (mcap_usd and sol_usd) else None
    fp = fee_pct(mcap_sol)
    quote = (liquidity_usd or 0) / 2
    impact = (size_usd / (quote + size_usd) * 100) if quote > 0 else 100.0
    slip_pct = impact + extra_slip_pct
    gas_usd = gas_sol * (sol_usd or 0)
    fee_usd = size_usd * fp / 100
    slip_usd = size_usd * slip_pct / 100
    return {"fee_pct": fp, "fee_usd": fee_usd, "slippage_pct": round(slip_pct, 4), "slippage_usd": slip_usd,
            "gas_usd": gas_usd, "total_usd": fee_usd + slip_usd + gas_usd, "mcap_sol": mcap_sol}

def round_trip(size_usd, liq_in, mcap_in, liq_out, mcap_out, sol_usd, gas_sol=0.0005, extra=0.5, exit_value=None):
    a = side_cost(size_usd, liq_in, mcap_in, sol_usd, gas_sol, extra)
    b = side_cost(exit_value if exit_value is not None else size_usd, liq_out, mcap_out, sol_usd, gas_sol, extra)
    return a["total_usd"] + b["total_usd"]
