"""small shared helpers: time, night boundaries, paths."""
from __future__ import annotations
import os, datetime as dt
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # /workspace/desk2
SECRETS = os.path.join(ROOT, ".secrets")
LOGS = os.path.join(ROOT, "logs")
TZ = ZoneInfo("Europe/Berlin")

def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def iso(t: dt.datetime | None = None) -> str:
    return (t or now()).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def parse(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)

def ts() -> float:
    return now().timestamp()

def night_start(report_time: str = "08:00", at: dt.datetime | None = None) -> dt.datetime:
    """A 'night' runs from one report_time (Berlin) to the next. Returns the start (UTC)."""
    at = (at or now()).astimezone(TZ)
    h, m = (int(x) for x in report_time.split(":"))
    b = at.replace(hour=h, minute=m, second=0, microsecond=0)
    if at < b:
        b -= dt.timedelta(days=1)
    return b.astimezone(dt.timezone.utc)

def night_key(report_time: str = "08:00", at=None) -> str:
    return night_start(report_time, at).astimezone(TZ).strftime("%Y-%m-%d")

def local_hm(iso_s: str) -> str:
    return parse(iso_s).astimezone(TZ).strftime("%H:%M")

def secret(name: str) -> str | None:
    p = os.path.join(SECRETS, name)
    if not os.path.exists(p):
        return None
    return open(p).read().strip()

def short(addr: str | None) -> str:
    return f"{addr[:4]}...{addr[-3:]}" if addr and len(addr) > 9 else (addr or "")

def money(x: float | None) -> str:
    if x is None:
        return "n/a"
    a = abs(x)
    if a >= 1e6: return f"${x/1e6:.1f}M"
    if a >= 1e3: return f"${x/1e3:.1f}K"
    return f"${x:,.2f}"
