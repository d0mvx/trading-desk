"""Shared reads used by Scanner + Auditor. All raw keys via fields.py."""
from __future__ import annotations
from . import fields as F, sources as S

def fnum(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

def pair_view(p: dict | None) -> dict | None:
    if not p:
        return None
    r = lambda k: F.read(p, F.DEXSCREENER_PAIR, k)
    price, native = fnum(r("price_usd")), fnum(r("price_native"))
    return {"pool": r("pair_address"), "dex": r("dex_id"), "name": r("name"), "symbol": r("symbol"),
            "price": price, "liquidity": fnum(r("liquidity_usd")), "mcap": fnum(r("market_cap")), "fdv": fnum(r("fdv")),
            "vol_m5": fnum(r("volume_m5")), "vol_h1": fnum(r("volume_h1")), "vol_h24": fnum(r("volume_h24")),
            "buys_m5": r("buys_m5"), "sells_m5": r("sells_m5"), "buys_h1": r("buys_h1"), "sells_h1": r("sells_h1"),
            "ch_m5": fnum(r("price_change_m5")), "ch_h1": fnum(r("price_change_h1")), "ch_h24": fnum(r("price_change_h24")),
            "created_ms": r("pair_created_at"), "image": r("image_url"),
            "sol_usd": (price / native) if (price and native) else None}

def market_of(report: dict, pool: str | None = None) -> dict | None:
    for m in (F.read(report, F.RUGCHECK_REPORT, "markets") or []):
        if pool and F.get(m, F.RUGCHECK_REPORT["market_pool"]) == pool:
            return m
        if not pool and F.get(m, F.RUGCHECK_REPORT["market_type"]) == "pump_fun_amm":
            return m
    return None

def amm_accounts(report: dict | None, pool: str | None) -> set:
    s = set()
    if pool: s.add(pool)
    if report:
        for addr, info in (F.read(report, F.RUGCHECK_REPORT, "known_accounts") or {}).items():
            if (info or {}).get("type") == "AMM":
                s.add(addr)
        for m in (F.read(report, F.RUGCHECK_REPORT, "markets") or []):
            for k in ("market_pool", "market_vault_a", "market_vault_b"):
                v = F.get(m, F.RUGCHECK_REPORT[k])
                if v: s.add(v)
    return s

async def mint_info(mint: str) -> dict:
    j = await S.rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    if F.get(j, ("result", "value")) is None:
        raise S.NoData("mint account not found")
    r = lambda k: F.read(j, F.RPC_MINT, k)
    return {"program": r("program"), "mint_authority": r("mint_authority"), "freeze_authority": r("freeze_authority"),
            "supply": fnum(r("supply")), "decimals": r("decimals")}

async def top10_pct(mint: str, supply_raw: float, exclude: set) -> float:
    """top 10 holders % of supply, pool + curve accounts excluded (owner or account address in exclude)."""
    j = await S.rpc("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}])
    accs = F.read(j, F.RPC_LARGEST, "accounts")
    if accs is None:
        raise S.NoData("largest accounts")
    addrs = [F.read(a, F.RPC_LARGEST, "address") for a in accs]
    owners = {}
    if addrs:
        m = await S.rpc("getMultipleAccounts", [addrs, {"encoding": "jsonParsed"}])
        for a, v in zip(addrs, F.read(m, F.RPC_MULTI, "values") or []):
            owners[a] = F.read(v or {}, F.RPC_MULTI, "owner")
    kept = []
    for a in accs:
        ad = F.read(a, F.RPC_LARGEST, "address")
        if ad in exclude or owners.get(ad) in exclude:
            continue
        kept.append(fnum(F.read(a, F.RPC_LARGEST, "amount")) or 0)
    kept.sort(reverse=True)
    if not supply_raw:
        raise S.NoData("supply")
    return sum(kept[:10]) / supply_raw * 100

async def owner_balance(owner: str, mint: str) -> float:
    j = await S.rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
    vals = F.read(j, F.RPC_OWNER_ACCOUNTS, "values")
    if vals is None:
        raise S.NoData("owner accounts")
    return sum(fnum(F.read(v, F.RPC_TOKEN_ACCOUNT, "amount")) or 0 for v in vals)

async def holder_accounts(mint: str) -> list[dict]:
    """getProgramAccounts on Token AND Token-2022, memcmp offset 0 = mint. Returns parsed accounts."""
    out = []
    for prog in (S.TOKEN, S.TOKEN22):
        flt = [{"memcmp": {"offset": 0, "bytes": mint}}]
        if prog == S.TOKEN:
            flt.append({"dataSize": 165})
        j = await S.rpc("getProgramAccounts", [prog, {"encoding": "jsonParsed", "filters": flt}], gpa=True)
        vals = F.read(j, F.GPA, "values")
        if vals is None:
            raise S.NoData("program accounts")
        for v in vals:
            out.append({"owner": F.read(v, F.RPC_TOKEN_ACCOUNT, "owner"),
                        "amount": fnum(F.read(v, F.RPC_TOKEN_ACCOUNT, "amount")) or 0,
                        "delegate": F.read(v, F.RPC_TOKEN_ACCOUNT, "delegate")})
    return out

def biggest_bundle(graph, holders_only: bool = True) -> int | None:
    """connected components over links among wallets holding this mint. None = no usable data."""
    if not isinstance(graph, list):
        return None
    holding, adj = set(), {}
    for net in graph:
        nodes = F.get(net, F.RUGCHECK_GRAPH["nodes"])
        links = F.get(net, F.RUGCHECK_GRAPH["edges"])
        if nodes is None or links is None:
            return None
        for n in nodes:
            if (fnum(F.get(n, F.RUGCHECK_GRAPH["node_holdings"])) or 0) > 0:
                holding.add(F.get(n, F.RUGCHECK_GRAPH["node_wallet"]))
        for e in links:
            a, b = F.get(e, F.RUGCHECK_GRAPH["edge_from"]), F.get(e, F.RUGCHECK_GRAPH["edge_to"])
            adj.setdefault(a, set()).add(b); adj.setdefault(b, set()).add(a)
    seen, best = set(), 0
    for w in holding:
        if w in seen: continue
        stack, size = [w], 0
        seen.add(w)
        while stack:
            c = stack.pop(); size += 1
            for nb in adj.get(c, ()):
                if nb in holding and nb not in seen:
                    seen.add(nb); stack.append(nb)
        best = max(best, size)
    return best
