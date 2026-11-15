"""The services that may read the published catalogue (/api/v1/published), each by a token of its own.

    METAMORPH_API_CLIENTS='[{"name": "mira", "token_sha256": "…"}]'

A client is a service, not a person: it can read what is published and do nothing else, and it can never act as a
curator. Its token is 32 random bytes (`metamorph client token NAME` makes one and prints the entry to add); only the
token's SHA-256 is kept here. A slow password hash would add nothing for a token with 256 bits of randomness, and a
fast one keeps every request cheap. Tokens are compared in constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

TOKEN_BYTES = 32


class ClientsError(ValueError):
    """METAMORPH_API_CLIENTS can't be used; the message says what to fix."""


@dataclass(frozen=True)
class _Client:
    name: str
    token_sha256: str


class ServiceClients:
    def __init__(self, clients: tuple[_Client, ...] = ()) -> None:
        self._clients = clients

    @classmethod
    def from_json(cls, value: str | None) -> ServiceClients:
        """No value means no clients: the published catalogue then refuses every request."""
        if not value:
            return cls()
        try:
            entries = json.loads(value)
            clients = tuple(_Client(str(entry["name"]), str(entry["token_sha256"]).lower()) for entry in entries)
        except (ValueError, TypeError, KeyError) as error:
            raise ClientsError('METAMORPH_API_CLIENTS must be a JSON list of {"name", "token_sha256"}') from error
        if any(not client.name or len(client.token_sha256) != hashlib.sha256().digest_size * 2 for client in clients):
            raise ClientsError("each client needs a name and the 64-character SHA-256 of its token")
        if len({client.name for client in clients}) != len(clients):
            raise ClientsError("each client's name must be its own")
        return cls(clients)

    def verify(self, token: str) -> str | None:
        """The client's name when the token is one of theirs; None otherwise."""
        digest = sha256_of(token)
        found = None
        for client in self._clients:  # every entry is compared, so the time taken says nothing about which matched
            if hmac.compare_digest(digest, client.token_sha256):
                found = client.name
        return found


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def sha256_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
