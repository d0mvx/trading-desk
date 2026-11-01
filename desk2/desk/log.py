"""one log file per agent, rotated daily (STEP 3). Never log secrets: httpx/httpcore request logging is off
because the RPC URL carries the Helius key."""
from __future__ import annotations
import logging, os
from logging.handlers import TimedRotatingFileHandler
from . import util

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
_made = {}

def get(name: str) -> logging.Logger:
    if name in _made:
        return _made[name]
    os.makedirs(util.LOGS, exist_ok=True)
    lg = logging.getLogger("desk." + name)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    h = TimedRotatingFileHandler(os.path.join(util.LOGS, f"{name}.log"), when="midnight", backupCount=14, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    lg.addHandler(h)
    _made[name] = lg
    return lg
