"""What a curator may change, and when a source's new value collides with a curator's correction."""

from __future__ import annotations

from dataclasses import replace

import pytest
from contract_samples import build_document
from metamorph_contract import join_pages

from metamorph_platform.domain.curation import (
    ActiveOverride,
    InvalidCorrection,
    checked_text_correction,
    conflicts,
    id_parts,
    parse_correction,
    source_values,
    validate_assigned_id,
    with_assigned_id,
)


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("title", "  Perizinan Usaha  ", "Perizinan Usaha"),
        ("status", "revoked", "revoked"),
        ("kind", "implementing_rule", "implementing_rule"),
        ("effective_on", "2019-02-27", "2019-02-27"),
        ("year", "2019", 2019),
    ],
)
def test_a_correction_is_parsed_by_its_field(field, raw, expected):
    assert parse_correction(field, raw) == expected


@pytest.mark.parametrize(
    ("field", "raw", "message"),
    [
        ("title", "   ", "can't be empty"),
        ("status", "repealed", "one of"),
        ("effective_on", "27/02/2019", "YYYY-MM-DD"),
        ("year", "twenty", "a year"),
        ("id", "ojk:pojk:2019:10", "can't be corrected"),
    ],
)
def test_a_bad_correction_says_what_is_expected(field, raw, message):
    with pytest.raises(InvalidCorrection, match=message):
        parse_correction(field, raw)


def test_the_source_values_are_the_overridable_fields_as_the_source_states_them():
    values = source_values(build_document())

    assert values["citation"] == "POJK 5/POJK.05/2014"
    assert values["status"] == "in_force"
    assert values["effective_on"] == "2014-04-08"
    assert values["year"] == 2014


def test_a_source_change_under_an_override_is_a_conflict():
    override = ActiveOverride(7, "title", value="Perizinan Usaha", source_value="Perizinan")

    assert conflicts([override], {"title": "Perizinan dan Kelembagaan"}) == [(override, "Perizinan dan Kelembagaan")]
    assert conflicts([override], {"title": "Perizinan"}) == []  # the source still says what it said
    assert conflicts([override], {"title": "Perizinan Usaha"}) == []  # the source now agrees with the curator


def test_an_assigned_id_must_be_canonical():
    assert validate_assigned_id(" ojk:pojk:2019:10 ") == "ojk:pojk:2019:10"
    for bad in ("unresolved:ojk:abc", "pojk 10/2019", "xx:pojk:2019:10"):
        with pytest.raises(InvalidCorrection):
            validate_assigned_id(bad)


def test_a_document_takes_its_curator_assigned_id_on_every_load():
    document = build_document()
    unresolved = replace(document, document=replace(document.document, id="unresolved:ojk:0f2aa739", issuer="ojk"))

    assigned = with_assigned_id(unresolved, "ojk:pojk:2014:5")

    assert assigned.document.id == "ojk:pojk:2014:5"
    assert assigned.document.id_confidence.value == "high"
    assert "curator" in assigned.document.id_evidence


def test_an_assigned_id_also_sets_the_family_number_and_year_it_names():
    document = build_document()

    assigned = with_assigned_id(document, "ojk:seojk:2016:9").document

    assert (assigned.issuer, assigned.family, assigned.number, assigned.year) == ("ojk", "seojk", "9", 2016)
    assert id_parts("dsnmui:fatwa:117") == ("dsnmui", "fatwa", None, "117")


PAGED = join_pages(["PERATURAN OTORITAS JASA KEUANGAN", "Pasa1 1\nSatu.", "Pasal 2\nDua."])


def test_a_corrected_text_is_normalised_to_newlines_and_a_final_newline():
    assert checked_text_correction("Pasa1 1\n", "Pasal 1\r\nSatu.", paged=False) == "Pasal 1\nSatu.\n"


def test_an_empty_or_unchanged_text_is_refused():
    with pytest.raises(InvalidCorrection, match="empty"):
        checked_text_correction("Pasa1 1\n", "  \n ", paged=False)
    with pytest.raises(InvalidCorrection, match="unchanged"):
        checked_text_correction("Pasal 1\nSatu.", "Pasal 1\r\nSatu.\n", paged=False)


def test_a_paged_text_keeps_every_page_marker_in_order():
    """Page numbers come from the markers: a lost or moved one would misplace every provision after it."""
    fixed = PAGED.replace("Pasa1 1", "Pasal 1")

    assert checked_text_correction(PAGED, fixed, paged=True) == fixed + "\n"
    with pytest.raises(InvalidCorrection, match="page 2"):
        checked_text_correction(PAGED, fixed.replace("<!-- page 2 -->\n", ""), paged=True)
    with pytest.raises(InvalidCorrection, match="page 4"):
        checked_text_correction(PAGED, fixed + "\n<!-- page 4 -->\nLampiran", paged=True)
    swapped = fixed.replace("<!-- page 2 -->", "<!-- page X -->").replace("<!-- page 3 -->", "<!-- page 2 -->")
    with pytest.raises(InvalidCorrection, match="order"):
        checked_text_correction(PAGED, swapped.replace("<!-- page X -->", "<!-- page 3 -->"), paged=True)


def test_an_unpaged_text_may_contain_anything():
    assert checked_text_correction("Pasa1 1\n", "<!-- page 9 -->\nPasal 1\n", paged=False).startswith("<!--")
