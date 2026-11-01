"""Notifier = Web Push (VAPID), replaces telegram.py. VAPID private key is server-only (.secrets/).
Subscriptions in db.push_subs; a 404/410 from the push service deletes the subscription.
Every push carries url = links.coin_url(mint); PAPER pushes start with 'PAPER · '."""
from __future__ import annotations
import asyncio, json, os
from pywebpush import webpush, WebPushException
from . import db, util, config, log, links

L = log.get("webpush")
SUBJECT = "https://relight-stalling-periscope.ngrok-free.dev"  # Apple rejects localhost subjects (403 BadJwtToken)

def public_key() -> str:
    return util.secret("vapid_public.txt") or ""

def _send_one(sub: dict, payload: str) -> str:
    try:
        webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=payload, vapid_private_key=os.path.join(util.SECRETS, "vapid_private.pem"),
                vapid_claims={"sub": SUBJECT}, ttl=3600, timeout=15)
        return "ok"
    except WebPushException as e:
        code = getattr(e.response, "status_code", None)
        if code in (404, 410):
            db.x("DELETE FROM push_subs WHERE endpoint=?", (sub["endpoint"],))
            return "gone"
        return f"error {code}"
    except Exception as e:
        return f"error {type(e).__name__}"

async def push(title: str, body: str, mint: str | None = None, kind: str = "info", url: str | None = None) -> dict:
    mode = config.get("desk.mode")
    if mode == "PAPER" and not title.startswith("PAPER · "):
        title = "PAPER · " + title
    url = url or (links.coin_url(mint) if mint else None)
    icon = ((db.coin(mint) or {}).get("image") if mint else None)
    payload = json.dumps({"title": title, "body": body, "url": url, "mint": mint, "kind": kind, "icon": icon, "tag": f"{kind}-{mint}" if mint else kind})
    subs = db.q("SELECT * FROM push_subs")
    results = []
    for s in subs:
        results.append(await asyncio.to_thread(_send_one, s, payload))
    ok = sum(r == "ok" for r in results)
    db.insert("pushes", ts=util.iso(), mint=mint, kind=kind, title=title, body=body, url=url, delivered=ok)
    L.info("push kind=%s mint=%s subs=%d ok=%d results=%s", kind, mint, len(subs), ok, results)
    return {"subs": len(subs), "ok": ok, "results": results, "title": title, "url": url}
