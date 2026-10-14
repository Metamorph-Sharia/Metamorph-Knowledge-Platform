import pytest
from metamorph_contract import canonical_id, is_canonical, is_unresolved, unresolved_id


def test_ids_are_named_by_issuer_family_year_and_number() -> None:
    assert canonical_id("ojk", "pojk", 5, 2014) == "ojk:pojk:2014:5"
    assert canonical_id("id", "UU", "21", 2011) == "id:uu:2011:21"


def test_a_number_that_never_repeats_needs_no_year() -> None:
    assert canonical_id("dsnmui", "fatwa", 117) == "dsnmui:fatwa:117"


def test_an_unknown_issuer_is_rejected() -> None:
    assert not is_canonical("kemenkeu:pmk:2017:23")
    with pytest.raises(ValueError, match="not a valid canonical ID"):
        canonical_id("kemenkeu", "pmk", 23, 2017)


def test_a_number_with_slashes_is_not_an_id_segment() -> None:
    with pytest.raises(ValueError):
        canonical_id("bi", "pbi", "23/6/PBI/2021", 2021)


def test_unresolved_ids_are_stable_safe_and_never_canonical() -> None:
    url = "https://www.bi.go.id/id/publikasi/peraturan/Pages/Ketentuan Sistem Pembayaran Nasional.aspx"

    first, second = unresolved_id("bi-website", url), unresolved_id("bi-website", url)

    assert first == second
    assert first.startswith("unresolved:bi-website:")
    assert " " not in first
    assert is_unresolved(first)
    assert not is_canonical(first)
