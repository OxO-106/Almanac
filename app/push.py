"""Web Push to devices (the iPhone Home Screen app, or a laptop browser).

Every Almanac notification is also pushed to each subscribed device. Pushes
go through the device maker's push service (Apple's for an iPhone), encrypted
end to end; the VAPID key pair that signs them is generated once and kept in
the local settings table."""

import base64
import json
import threading
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, HTTPException, Request

from .db import WRITE, settings
from .scheduler import ON_NOTIFY

router = APIRouter(prefix="/api/push")
BACKGROUND = True  # send in a thread so a slow push service never delays a job (tests turn it off)


def send(sub: dict, payload: str, key_pem: str, claims: dict):
    from py_vapid import Vapid
    from pywebpush import webpush
    # a Vapid object: pywebpush reads a plain string as a file path or raw DER, not PEM
    webpush(subscription_info=sub, data=payload, vapid_private_key=Vapid.from_pem(key_pem.encode()),
            vapid_claims=dict(claims), ttl=86400)


def _keys(con) -> dict:
    k = settings(con).get("push_vapid")
    if k:
        return k
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    point = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    k = {"private_pem": pem, "public": base64.urlsafe_b64encode(point).rstrip(b"=").decode()}
    with WRITE:
        con.execute("insert into settings (key, value) values ('push_vapid', ?) on conflict(key) do nothing", (json.dumps(k),))
    return settings(con)["push_vapid"]


def push_all(con, title, body, url):
    subs = [dict(r) for r in con.execute("select * from push_subscriptions")]
    if not subs:
        return
    keys = _keys(con)
    payload = json.dumps({"title": title, "body": body or "", "url": url or "#today"})

    def run():
        for s in subs:
            info = {"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}
            try:
                send(info, payload, keys["private_pem"], {"sub": s["contact"]})
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):  # the device unsubscribed or the app was removed
                    with WRITE:
                        con.execute("delete from push_subscriptions where endpoint = ?", (s["endpoint"],))
                else:
                    print(f"push: {type(e).__name__}: {e}")

    threading.Thread(target=run, daemon=True).start() if BACKGROUND else run()


ON_NOTIFY.append(push_all)


@router.get("/key")
def key(request: Request):
    return {"key": _keys(request.app.state.db)["public"]}


@router.post("/subscribe")
async def subscribe(request: Request):
    b = await request.json()
    keys = b.get("keys") or {}
    if not (str(b.get("endpoint", "")).startswith("https://") and keys.get("p256dh") and keys.get("auth")):
        raise HTTPException(422, "Not a push subscription.")
    # VAPID needs a contact: this site's own address (no personal email involved)
    origin = request.headers.get("origin") or str(request.base_url)
    contact = "https://" + (urlsplit(origin).hostname or "localhost")  # py_vapid accepts no port here
    with WRITE:
        request.app.state.db.execute(
            "insert into push_subscriptions (endpoint, p256dh, auth, contact) values (?,?,?,?) "
            "on conflict(endpoint) do update set p256dh = excluded.p256dh, auth = excluded.auth, contact = excluded.contact",
            (b["endpoint"], keys["p256dh"], keys["auth"], contact))
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(request: Request):
    endpoint = (await request.json()).get("endpoint")
    with WRITE:
        request.app.state.db.execute("delete from push_subscriptions where endpoint = ?", (endpoint,))
    return {"ok": True}


@router.get("/devices")
def devices(request: Request):
    return {"count": request.app.state.db.execute("select count(*) from push_subscriptions").fetchone()[0]}


@router.post("/test")
def test(request: Request):
    push_all(request.app.state.db, "Notifications are on", "Almanac can reach this device.", "#settings")
    return {"ok": True}
