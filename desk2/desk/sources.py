"""HTTP sources: DexScreener (by pool address), RugCheck, Solana RPC (Helius). Rate-limited.
Field paths come from fields.py only."""
from __future__ import annotations
import asyncio, time, httpx
from . import config, log

L = log.get("sources")

class RateLimited(Exception):
    pass

class NoData(Exception):
    pass

class _Limiter:
    def __init__(self, per_s: float):
        self.gap = 1.0 / per_s
        self.t = 0.0
        self.lock = asyncio.Lock()
    async def wait(self):
        async with self.lock:
            d = self.t + self.gap - time.monotonic()
            if d > 0:
                await asyncio.sleep(d)
            self.t = time.monotonic()

_client: httpx.AsyncClient | None = None
_client_loop = None
DEX = _Limiter(250 / 60)          # stay under 250 requests/min (STEP 6)
RUG = _Limiter(3)
RPC = _Limiter(8)                 # Helius free: 10 req/s
GPA = _Limiter(4)                 # Helius free: getProgramAccounts 5/s

def client() -> httpx.AsyncClient:
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:   # one client per event loop (tests run several loops)
        _client_loop = loop
        _client = httpx.AsyncClient(timeout=20, headers={"user-agent": "desk2/1.0"}, follow_redirects=True)
    return _client

async def _get(url, lim):
    await lim.wait()
    r = await client().get(url)
    if r.status_code == 429:
        raise RateLimited(url.split("?")[0])
    if r.status_code >= 400:
        raise NoData(f"HTTP {r.status_code} {url.split('?')[0]}")
    return r.json()

async def dex_pairs(pools: list[str]) -> dict[str, dict]:
    """latest/dex/pairs/solana/{pool,...} (approved: by pool address; tokens/v1 can return a stale curve pair)."""
    out = {}
    for i in range(0, len(pools), 30):
        chunk = pools[i:i + 30]
        j = await _get("https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(chunk), DEX)
        for p in (j.get("pairs") or []):
            out[p.get("pairAddress")] = p
    return out

async def dex_token_pairs(mint: str) -> list[dict]:
    j = await _get(f"https://api.dexscreener.com/token-pairs/v1/solana/{mint}", DEX)
    return j if isinstance(j, list) else []

async def rug_report(mint: str) -> dict:
    return await _get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", RUG)

async def rug_graph(mint: str):
    return await _get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/insiders/graph", RUG)

async def rpc(method: str, params: list, gpa: bool = False):
    await (GPA if gpa else RPC).wait()
    url = config.rpc_url()
    r = await client().post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
    if r.status_code == 429:
        raise RateLimited(method)
    if r.status_code >= 400:
        raise NoData(f"rpc {method} HTTP {r.status_code}")
    j = r.json()
    if "error" in j:
        if j["error"].get("code") == 429:
            raise RateLimited(method)
        raise NoData(f"rpc {method} {j['error'].get('message', '')[:80]}")
    return j

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN22 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
