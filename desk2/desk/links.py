"""The ONLY place URLs to the venue are built (STEP 4, adapted: venue = pump.fun, no FOMO handle/referral).
Every push, button, Activity row, coin screen and the morning Page uses coin_url()."""
from __future__ import annotations
import re

VENUE = "pump.fun"
SIGNUP_URL = "https://pump.fun"          # no referral programme in use; plain home page
_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

def coin_url(mint: str, chain: str = "solana") -> str:
    if chain != "solana" or not mint or not _B58.match(mint):
        return SIGNUP_URL
    return f"https://pump.fun/coin/{mint}"

def profile_url() -> None:
    """FOMO had a profile page; pump.fun is used without an account handle here."""
    return None
