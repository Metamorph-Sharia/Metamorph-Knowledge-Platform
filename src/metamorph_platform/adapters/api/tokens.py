"""The session token the curation API issues at sign-in: who the curator is, until when, signed.

    <payload>.<signature>   payload: base64url JSON {"sub", "name", "exp"}; signature: HMAC-SHA256 of it

The web app keeps it in an httpOnly cookie and sends it as a bearer token. It is short-lived, so a stolen
one is soon useless; nothing about it is stored on the server.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta

from metamorph_platform.application.ports import Curator

TOKEN_LIFETIME = timedelta(hours=8)  # a working day


class InvalidToken(Exception):
    """Not a token this API issued, or an expired one: sign in again."""


def issue(curator: Curator, secret: str, *, now: datetime) -> str:
    claims = {"sub": curator.username, "name": curator.display_name, "exp": int((now + TOKEN_LIFETIME).timestamp())}
    payload = _encode(json.dumps(claims, separators=(",", ":")).encode())
    return f"{payload}.{_signature(payload, secret)}"


def verify(token: str, secret: str, *, now: datetime) -> Curator:
    payload, _, signature = token.partition(".")
    if not signature or not hmac.compare_digest(signature, _signature(payload, secret)):
        raise InvalidToken("not a token this API issued")
    claims = json.loads(_decode(payload))
    if now.timestamp() >= claims["exp"]:
        raise InvalidToken("the session expired: sign in again")
    return Curator(claims["sub"], claims["name"])


def _signature(payload: str, secret: str) -> str:
    return _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
