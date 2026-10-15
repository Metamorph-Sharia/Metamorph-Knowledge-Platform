"""What a curator may change, and when a source's new value collides with a curator's correction."""

from __future__ import annotations

from dataclasses import replace

import pytest
from contract_samples import build_document

from metamorph_platform.domain.curation import (
    ActiveOverride,
    InvalidCorrection,
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
