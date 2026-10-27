"""`problems(record)`: the schema, plus the rules that compare one value with another."""

from dataclasses import replace

from market_samples import EDITION_SHA, build_record
from metamorph_market import Listing, problems


def test_a_valid_record_has_no_problems() -> None:
    assert problems(build_record()) == []


def test_the_id_must_belong_to_its_register() -> None:
    record = build_record()
    record = replace(record, entity=replace(record.entity, id="bi:pjp:kep-123-d.05-2019"))

    assert problems(record) == ["entity.id: 'bi:pjp:kep-123-d.05-2019' is not on register 'ojk:lpbbti'"]


def test_a_listing_must_point_at_a_file_of_the_record() -> None:
    record = build_record()
    stray = replace(record.listings[0], file="b" * 64)

    assert problems(replace(record, listings=(stray,))) == [
        f"listings[0].file: {'b' * 12}… is not in files"
    ]


def test_an_edition_is_listed_once() -> None:
    record = build_record()
    again = Listing(edition=record.listings[0].edition, file=EDITION_SHA, page=2, row=40, legal_name="", cells={})

    assert problems(replace(record, listings=(record.listings[0], again))) == [
        "listings[1].edition: 2026-07-31 is listed twice"
    ]


def test_schema_problems_are_reported_with_their_path() -> None:
    record = build_record()
    record = replace(record, entity=replace(record.entity, business_type="islamic"))

    assert problems(record) == ["entity.business_type: 'islamic' is not one of ['sharia', 'conventional', 'unknown']"]
