"""The curation API's session token: signed, short-lived, naming the curator every action is audited under."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from metamorph_platform.adapters.api.tokens import TOKEN_LIFETIME, InvalidToken, issue, verify
from metamorph_platform.application.ports import Curator

ANI = Curator("ani", "Ani Rahma")
SECRET = "s" * 32
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def test_a_token_names_the_curator_it_was_issued_to_until_it_expires() -> None:
    token = issue(ANI, SECRET, now=NOW)

    assert verify(token, SECRET, now=NOW + TOKEN_LIFETIME - timedelta(seconds=1)) == ANI
    with pytest.raises(InvalidToken, match="expired"):
        verify(token, SECRET, now=NOW + TOKEN_LIFETIME)


def test_a_token_signed_with_another_secret_or_changed_is_refused() -> None:
    token = issue(ANI, SECRET, now=NOW)
    payload, signature = token.split(".")
    forged = issue(Curator("admin", "Admin"), SECRET, now=NOW).split(".")[0] + "." + signature

    for bad in (forged, issue(ANI, "x" * 32, now=NOW), payload, "not-a-token", ""):
        with pytest.raises(InvalidToken):
            verify(bad, SECRET, now=NOW)
