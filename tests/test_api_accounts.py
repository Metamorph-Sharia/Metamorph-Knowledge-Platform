"""Team accounts for the curation app: from the environment, never stored in plain text."""

from __future__ import annotations

import json

import pytest

from metamorph_platform.adapters.api.accounts import Accounts, AccountsError, hash_password


@pytest.fixture(scope="module")
def ani_hash() -> str:
    return hash_password("kata-sandi-panjang", iterations=1_000)


def test_a_team_member_signs_in_with_their_password(ani_hash) -> None:
    accounts = Accounts.from_json(json.dumps([{"username": "ani", "name": "Ani Rahma", "password_hash": ani_hash}]))

    curator = accounts.verify("ani", "kata-sandi-panjang")

    assert (curator.username, curator.display_name) == ("ani", "Ani Rahma")
    assert accounts.verify("ani", "salah") is None
    assert accounts.verify("budi", "kata-sandi-panjang") is None


def test_hashes_are_salted(ani_hash) -> None:
    assert hash_password("kata-sandi-panjang", iterations=1_000) != ani_hash
    assert "kata-sandi-panjang" not in ani_hash


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        json.dumps([{"username": "ani"}]),
        json.dumps([{"username": "ani", "name": "A", "password_hash": "x"}]),
    ],
)
def test_a_broken_account_list_is_refused_with_a_reason(raw) -> None:
    with pytest.raises(AccountsError):
        Accounts.from_json(raw)
