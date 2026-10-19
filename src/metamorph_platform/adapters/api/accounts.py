"""The team's curation accounts (the curation API signs them in): from METAMORPH_CURATORS, hashed with PBKDF2.

    METAMORPH_CURATORS='[{"username": "ani", "name": "Ani Rahma", "password_hash": "pbkdf2_sha256$…"}]'

`metamorph curator hash-password` prints a hash to put there. Plain passwords are never stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

from metamorph_platform.application.ports import Curator

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000  # OWASP's 2023 guidance for PBKDF2-HMAC-SHA256
SALT_BYTES = 16
HASH_PARTS = 4


class AccountsError(ValueError):
    """METAMORPH_CURATORS can't be used; the message says what to fix."""


@dataclass(frozen=True)
class _Account:
    curator: Curator
    password_hash: str


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def _matches(password: str, stored: str) -> bool:
    algorithm, iterations, salt, digest = stored.split("$")
    computed = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
    return algorithm == ALGORITHM and hmac.compare_digest(computed, base64.b64decode(digest))


class Accounts:
    def __init__(self, accounts: list[_Account]) -> None:
        self._accounts = {account.curator.username: account for account in accounts}
        self._verified: dict[tuple[str, str], Curator] = {}  # spares a 600k-round hash on every request

    @classmethod
    def from_json(cls, raw: str) -> Accounts:
        try:
            entries = json.loads(raw)
            accounts = [
                _Account(Curator(entry["username"], entry["name"]), entry["password_hash"]) for entry in entries
            ]
        except (ValueError, TypeError, KeyError) as error:
            raise AccountsError("METAMORPH_CURATORS must be a JSON list of {username, name, password_hash}") from error
        for account in accounts:
            parts = account.password_hash.split("$")
            if len(parts) != HASH_PARTS or parts[0] != ALGORITHM:
                raise AccountsError(
                    f"{account.curator.username}: password_hash isn't a {ALGORITHM} hash; "
                    "make one with `metamorph curator hash-password`"
                )
        if not accounts:
            raise AccountsError("METAMORPH_CURATORS lists no one: add at least one team member")
        return cls(accounts)

    def verify(self, username: str, password: str) -> Curator | None:
        key = (username, hashlib.sha256(password.encode()).hexdigest())
        if key in self._verified:
            return self._verified[key]
        account = self._accounts.get(username)
        if account is None or not _matches(password, account.password_hash):
            return None
        self._verified[key] = account.curator
        return account.curator


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()
