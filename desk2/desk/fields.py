"""fields.py - raw-key mapping (verified on STEP 2 samples) from STEP 2 samples (logs/raw/, captured 2026-11-01 ~22:56 CET).
Agents read source JSON ONLY through this module. A path of None = key not present in the raw
sample; the getter returns None and the agent must treat it as "no data" (never a pass, never a guess).
Paths are tuples; ("[]", ...) means "each element of the list".
"""
from __future__ import annotations
from typing import Any

# ---- PumpPortal wss://pumpportal.fun/api/data  subscribeMigration  (raw: pumpportal_migration.json)
# sample: {"signature","mint","txType":"migrate","pool":"pump-amm"}
PUMPPORTAL = {
    "mint":        ("mint",),
    "signature":   ("signature",),
    "tx_type":     ("txType",),          # "migrate"
    "pool_kind":   ("pool",),            # "pump-amm" = venue label, NOT a pool address
    "pool":        None,                 # no pool address in message -> DexScreener pumpswap pairAddress / RugCheck market pubkey
    "creator":     None,                 # not in message -> RugCheck report "creator"
    "migrated_at": None,                 # no timestamp in message -> receive time (UTC) is migratedAt
    "name":        None,
    "symbol":      None,
}

# ---- DexScreener pair object (raw: dexscreener_*.json). Pick dexId == "pumpswap", most liquidity.
DEXSCREENER_PAIR = {
    "dex_id":          ("dexId",),               # "pumpswap" | "pumpfun" (old curve) | "meteora" ...
    "pair_address":    ("pairAddress",),
    "base_mint":       ("baseToken", "address"),
    "name":            ("baseToken", "name"),
    "symbol":          ("baseToken", "symbol"),
    "price_usd":       ("priceUsd",),            # STRING -> float()
    "liquidity_usd":   ("liquidity", "usd"),     # ABSENT on the pumpfun curve pair
    "market_cap":      ("marketCap",),
    "fdv":             ("fdv",),
    "volume_m5":       ("volume", "m5"),
    "volume_h1":       ("volume", "h1"),
    "volume_h24":      ("volume", "h24"),
    "buys_m5":         ("txns", "m5", "buys"),
    "sells_m5":        ("txns", "m5", "sells"),
    "buys_h1":         ("txns", "h1", "buys"),
    "sells_h1":        ("txns", "h1", "sells"),
    "buys_h6":         ("txns", "h6", "buys"),
    "sells_h6":        ("txns", "h6", "sells"),
    "buys_h24":        ("txns", "h24", "buys"),
    "sells_h24":       ("txns", "h24", "sells"),
    "price_change_m5": ("priceChange", "m5"),    # can be ABSENT (seen on stale pair: only h6/h24)
    "price_change_h1": ("priceChange", "h1"),    # can be ABSENT
    "price_change_h24":("priceChange", "h24"),
    "pair_created_at": ("pairCreatedAt",),       # epoch ms
    "image_url":       ("info", "imageUrl"),     # coin logo for pushes (optional)
    "price_native":    ("priceNative",),         # STRING, price in quote (SOL)
    "quote_symbol":    ("quoteToken", "symbol"),
}

# ---- RugCheck /v1/tokens/{mint}/report (raw: rugcheck_report_*.json)
RUGCHECK_REPORT = {
    "creator":          ("creator",),
    "creator_balance":  ("creatorBalance",),           # raw units (int)
    "token_program":    ("tokenProgram",),
    "mint_authority":   ("mintAuthority",),
    "freeze_authority": ("freezeAuthority",),
    "supply":           ("token", "supply"),
    "decimals":         ("token", "decimals"),
    "total_holders":    ("totalHolders",),
    "top_holders":      ("topHolders",),               # [{address, owner, amount, pct, insider}]
    "known_accounts":   ("knownAccounts",),            # {addr: {name, type: AMM|CREATOR|LOCKER}}
    "markets":          ("markets",),                  # list
    "market_pool":      ("pubkey",),                   # inside a market; == Scanner pool
    "market_type":      ("marketType",),               # "pump_fun_amm" for PumpSwap
    "market_lp_locked_pct": ("lp", "lpLockedPct"),     # layer 5 (RugCheck folds burned into locked)
    "market_lp_burned_pct": None,                      # no separate burned key exists
    "market_lp_locked_usd": ("lp", "lpLockedUSD"),
    "market_lp_holders":    ("lp", "holders"),
    "graph_insiders_detected": ("graphInsidersDetected",),
    "permanent_delegate": ("token_extensions", "permanentDelegate"),
    "transfer_fee_pct":   ("transferFee", "pct"),
    "rugged":             ("rugged",),
    "name":               ("tokenMeta", "name"),
    "symbol":             ("tokenMeta", "symbol"),
    "market_vault_a":     ("liquidityA",),            # pool token vault (inside a market)
    "market_vault_b":     ("liquidityB",),
}

# ---- RugCheck /v1/tokens/{mint}/insiders/graph (raw: rugcheck_insiders_graph_*.json)
# Top level is a LIST of networks; [] when RugCheck found none.
RUGCHECK_GRAPH = {
    "networks":      (),                    # the list itself
    "network_type":  ("network_type",),     # "transfer"
    "nodes":         ("nodes",),            # [{id, participant, holdings}]
    "node_wallet":   ("id",),
    "node_holdings": ("holdings",),         # raw units; >0 = holds this mint
    "edges":         ("links",),            # prompt says "edges"; real key is "links" [{source, target}]
    "edge_from":     ("source",),
    "edge_to":       ("target",),
}

# ---- Solana RPC getAccountInfo(mint, jsonParsed) (raw: rpc_getAccountInfo_*.json)
RPC_MINT = {
    "program":          ("result", "value", "owner"),   # Tokenz... = Token-2022 (pump.fun mints)
    "mint_authority":   ("result", "value", "data", "parsed", "info", "mintAuthority"),
    "freeze_authority": ("result", "value", "data", "parsed", "info", "freezeAuthority"),
    "supply":           ("result", "value", "data", "parsed", "info", "supply"),   # STRING raw
    "decimals":         ("result", "value", "data", "parsed", "info", "decimals"),
}

# ---- getProgramAccounts / getTokenAccountsByOwner element (jsonParsed)
RPC_TOKEN_ACCOUNT = {
    "pubkey":   ("pubkey",),
    "owner":    ("account", "data", "parsed", "info", "owner"),
    "mint":     ("account", "data", "parsed", "info", "mint"),
    "amount":   ("account", "data", "parsed", "info", "tokenAmount", "amount"),   # STRING raw
    "delegate": ("account", "data", "parsed", "info", "delegate"),               # key ABSENT if none
    "delegated_amount": ("account", "data", "parsed", "info", "delegatedAmount", "amount"),
    "state":    ("account", "data", "parsed", "info", "state"),
}

# ---- getTokenSupply / getTokenLargestAccounts
RPC_SUPPLY = {"amount": ("result", "value", "amount"), "decimals": ("result", "value", "decimals")}
RPC_LARGEST = {"accounts": ("result", "value"), "address": ("address",), "amount": ("amount",)}
RPC_MULTI = {"values": ("result", "value"), "owner": ("data", "parsed", "info", "owner")}
RPC_OWNER_ACCOUNTS = {"values": ("result", "value")}   # list of RPC_TOKEN_ACCOUNT elements
GPA = {"values": ("result",)}
# ---- GeckoTerminal /networks/solana/dexes/pumpswap/pools + /networks/solana/pools/{pool} (verified 2026-11-04)
GECKO_POOL = {
    "pool":         ("attributes", "address"),
    "created_at":   ("attributes", "pool_created_at"),      # ISO "2026-11-04T03:10:13Z"
    "reserve_usd":  ("attributes", "reserve_in_usd"),       # STRING, pool liquidity $
    "base_id":      ("relationships", "base_token", "data", "id"),   # "solana_<mint>"
    "dex_id":       ("relationships", "dex", "data", "id"),          # "pumpswap"
    "name":         ("attributes", "name"),
    "buyers_m5":    ("attributes", "transactions", "m5", "buyers"),
    "sellers_m5":   ("attributes", "transactions", "m5", "sellers"),
    "buyers_h1":    ("attributes", "transactions", "h1", "buyers"),
    "sellers_h1":   ("attributes", "transactions", "h1", "sellers"),
    "buyers_h24":   ("attributes", "transactions", "h24", "buyers"),
    "sellers_h24":  ("attributes", "transactions", "h24", "sellers"),
}
# ---- DexScreener token-boosts/top/v1, token-boosts/latest/v1, token-profiles/latest/v1 elements (verified 2026-11-04)
DEXSCREENER_LIST = {"chain": ("chainId",), "mint": ("tokenAddress",)}
# ---- getSignaturesForAddress element
RPC_SIGS = {"values": ("result",), "block_time": ("blockTime",)}
JEV = {"model": ("model",), "answers": ("answers",), "noul": ("noul",), "input_tokens": ("usage", "input_tokens"),
       "output_tokens": ("usage", "output_tokens")}
# NOTE: getTokenLargestAccounts returned 429 on api.mainnet-beta.solana.com every try (2026-11-01).


def get(obj: Any, path: tuple | None) -> Any:
    """Walk a mapped path. None path or missing key -> None. Never guesses."""
    if path is None:
        return None
    cur = obj
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def read(obj: Any, table: dict, field: str) -> Any:
    return get(obj, table[field])
