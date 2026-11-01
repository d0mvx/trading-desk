"""In-process bus: agent queues + SSE fan-out (events: scan, audit_layer, verdict, signal, fill, exit, balance)."""
from __future__ import annotations
import asyncio, json, itertools

to_auditor: asyncio.Queue = asyncio.Queue()
to_analyst: asyncio.Queue = asyncio.Queue()
to_executor: asyncio.Queue = asyncio.Queue()
_subs: set[asyncio.Queue] = set()
_ids = itertools.count(1)
recent: list[dict] = []

def emit(event: str, data: dict):
    msg = {"id": next(_ids), "event": event, "data": data}
    recent.append(msg)
    del recent[:-200]
    for q in list(_subs):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass

def subscribe() -> asyncio.Queue:
    q = asyncio.Queue(maxsize=500)
    _subs.add(q)
    return q

def unsubscribe(q):
    _subs.discard(q)

def sse(msg: dict) -> str:
    return f"id: {msg['id']}\nevent: {msg['event']}\ndata: {json.dumps(msg['data'], default=str)}\n\n"

paused: set[str] = set()
