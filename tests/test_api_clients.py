"""The services that may read the published catalogue: how their tokens are kept and checked."""

from __future__ import annotations

import json

import pytest

from metamorph_platform.adapters.api.clients import ClientsError, ServiceClients, new_token, sha256_of


def clients(*names_and_tokens: tuple[str, str]) -> ServiceClients:
    return ServiceClients.from_json(
        json.dumps([{"name": name, "token_sha256": sha256_of(token)} for name, token in names_and_tokens])
    )


def test_a_clients_token_names_the_client_and_any_other_names_none():
    mira = new_token()
    known = clients(("mira", mira), ("other", new_token()))
    assert known.verify(mira) == "mira"
    assert known.verify(new_token()) is None
    assert known.verify("") is None


def test_no_clients_set_refuses_every_token():
    assert ServiceClients.from_json(None).verify(new_token()) is None


def test_a_new_token_is_long_and_unguessable():
    assert len(new_token()) >= 43 and new_token() != new_token()


@pytest.mark.parametrize(
    "value",
    [
        "not json",
        json.dumps([{"name": "mira"}]),
        json.dumps([{"name": "mira", "token_sha256": "short"}]),
        json.dumps([{"name": "", "token_sha256": "a" * 64}]),
        json.dumps([{"name": "mira", "token_sha256": "a" * 64}, {"name": "mira", "token_sha256": "b" * 64}]),
    ],
)
def test_an_unusable_setting_says_so(value):
    with pytest.raises(ClientsError):
        ServiceClients.from_json(value)
