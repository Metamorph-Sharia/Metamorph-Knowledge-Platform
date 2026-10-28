"""`problems(record)`: the schema, plus the rules that compare one value with another."""

from dataclasses import replace

from market_samples import EDITION_SHA, build_record, build_report, build_series
from metamorph_market import Frequency, Listing, SeriesRecord, problems


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


def test_a_valid_series_has_no_problems() -> None:
    assert problems(build_series()) == []


def test_a_series_id_must_belong_to_its_dataset() -> None:
    record = build_series()
    record = replace(record, series=replace(record.series, id="ojk:portal:other:posisi-keuangan"))

    assert problems(record) == [
        "series.id: 'ojk:portal:other:posisi-keuangan' is not in dataset 'ojk:portal:bu_syariah_posisikeuangan'"
    ]


def test_an_observation_must_point_at_a_file_of_the_record() -> None:
    record = build_series()
    stray = replace(record.observations[0], file="d" * 64)

    assert problems(replace(record, observations=(stray, record.observations[1]))) == [
        f"observations[0].file: {'d' * 12}… is not in files"
    ]


def test_a_period_is_observed_once() -> None:
    record = build_series()
    first = record.observations[0]

    assert problems(replace(record, observations=(first, first))) == [
        "observations[1].period: 2026-07 is observed twice"
    ]


def test_a_series_period_must_be_a_month() -> None:
    record = build_series()
    odd = replace(record.observations[0], period="2026-13")

    found = problems(replace(record, observations=(odd,)))
    assert found[0].startswith("observations[0].period: '2026-13' does not match")


def _quarterly(*periods: str) -> SeriesRecord:
    record = build_series()
    observations = tuple(replace(record.observations[0], period=period) for period in periods)
    return replace(record, series=replace(record.series, frequency=Frequency.QUARTERLY), observations=observations)


def test_a_series_may_be_quarterly_semiannual_or_annual() -> None:
    record = build_series()
    for frequency, period in [
        (Frequency.QUARTERLY, "2026-Q2"),
        (Frequency.SEMIANNUAL, "2026-S1"),
        (Frequency.ANNUAL, "2025"),
    ]:
        observation = replace(record.observations[0], period=period)
        changed = replace(record, series=replace(record.series, frequency=frequency), observations=(observation,))
        assert problems(changed) == [], frequency


def test_a_period_must_be_of_its_series_frequency() -> None:
    assert problems(_quarterly("2026-Q1", "2026-08")) == ["observations[1].period: 2026-08 is not quarterly"]


def test_a_quarter_is_one_to_four() -> None:
    found = problems(_quarterly("2026-Q5"))
    assert found[0].startswith("observations[0].period: '2026-Q5' does not match")


def test_a_macro_series_belongs_to_no_industry() -> None:
    record = build_series()
    assert problems(replace(record, series=replace(record.series, industry=None, unit="Miliar Rp"))) == []


def test_an_observation_may_be_provisional() -> None:
    record = build_series()
    provisional = replace(record.observations[1], provisional=True)
    assert problems(replace(record, observations=(record.observations[0], provisional))) == []


def test_a_valid_report_has_no_problems() -> None:
    assert problems(build_report()) == []


def test_a_report_id_names_its_issuer_and_family() -> None:
    record = build_report()
    record = replace(record, report=replace(record.report, id="bi:keksi:2024"))

    assert problems(record) == ["report.id: 'bi:keksi:2024' is not of issuer 'ojk' and family 'lpksi'"]


def test_a_roadmap_id_may_carry_the_year_and_a_short_name() -> None:
    record = build_report()
    report = replace(record.report, id="ojk:roadmap:2023:rp3si", family="roadmap", edition="2023-2027")

    assert problems(replace(record, report=report)) == []


def test_a_report_has_pages() -> None:
    record = build_report()

    assert problems(replace(record, text=replace(record.text, pages=0))) == [
        "text.pages: 0 is less than the minimum of 1"
    ]

