"""What publishing makes of series: datasets linked to registers and regulations, series, and observations."""

from __future__ import annotations

from datetime import date

import pytest
from market_platform_samples import answer_sha, macro_series, series_record
from metamorph_market import Frequency

from metamorph_platform.domain.market.statistics import IndustryLink, in_datasets, source_of, statistics

LPBBTI_SYARIAH = "Layanan Pendanaan Bersama Berbasis Teknologi Informasi (LPBBTI) Syariah"
LINKS = [
    IndustryLink("ojk:portal", "Bank Umum Syariah", None, ("id:uu:2008:21", "ojk:pojk:2022:16")),
    IndustryLink("ojk:portal", LPBBTI_SYARIAH, "ojk:lpbbti", ()),
]
REGISTERS = {"ojk:lpbbti": ("ojk:pojk:2024:40", "ojk:seojk:2025:19")}
KEYS = {answer_sha(year): f"blobs/{year}" for year in ("2025", "2026")}


def records():
    return [
        series_record("BU_Syariah_PosisiKeuangan", "110001010100", "003. 1. Kas dan Setara Kas",
                      {"2025-12": 10.0, "2026-01": 12.0}),
        series_record("BU_Syariah_PosisiKeuangan", "110001010200", "004. 2. Piutang Usaha", {"2026-01": 5.0}),
        series_record("LPBBTI_Syariah_PosisiKeuangan", "110001010100", "003. 1. Kas dan Setara Kas",
                      {"2026-01": 1.0}, industry=LPBBTI_SYARIAH),
    ]


def test_a_dataset_is_published_with_its_span_and_its_industry_s_regulations() -> None:
    datasets = {dataset.id: dataset for dataset in statistics(LINKS, REGISTERS, records(), KEYS).datasets}

    bus = datasets["ojk:portal:bu_syariah_posisikeuangan"]
    assert (bus.source, bus.industry, bus.metric, bus.series) == (
        "ojk:portal", "Bank Umum Syariah", "Laporan Posisi Keuangan", 2,
    )
    assert (bus.first_period, bus.last_period, bus.updated) == (date(2025, 12, 1), date(2026, 1, 1), date(2026, 10, 26))
    assert (bus.register, bus.governed_by) == (None, ("id:uu:2008:21", "ojk:pojk:2022:16"))


def test_a_dataset_of_a_register_s_industry_takes_the_register_and_its_regulations() -> None:
    datasets = {dataset.id: dataset for dataset in statistics(LINKS, REGISTERS, records(), KEYS).datasets}

    lpbbti = datasets["ojk:portal:lpbbti_syariah_posisikeuangan"]
    assert (lpbbti.register, lpbbti.governed_by) == ("ojk:lpbbti", ("ojk:pojk:2024:40", "ojk:seojk:2025:19"))


def test_an_industry_without_a_link_is_published_without_one() -> None:
    (dataset,) = statistics([], {}, records()[:1], KEYS).datasets

    assert (dataset.register, dataset.governed_by) == (None, ())


def test_a_series_is_labelled_by_its_measure_and_members() -> None:
    published = statistics(LINKS, REGISTERS, records(), KEYS)

    kas_id = "ojk:portal:bu_syariah_posisikeuangan:posisi-keuangan:akun=110001010100"
    kas = next(series for series in published.series if series.id == kas_id)
    assert kas.label == "Posisi Keuangan: 003. 1. Kas dan Setara Kas"
    assert kas.dimensions == ({"name": "Akun", "key": "110001010100", "label": "003. 1. Kas dan Setara Kas"},)
    assert (kas.first_period, kas.last_period, kas.observations) == (date(2025, 12, 1), date(2026, 1, 1), 2)


def test_each_observation_is_a_month_with_its_answer_s_place_in_the_object_store() -> None:
    published = statistics(LINKS, REGISTERS, records(), KEYS)

    assert len(published.observations) == 4
    first = published.observations[0]
    assert (first.period, first.value, first.storage_key) == (date(2025, 12, 1), 10.0, "blobs/2025")


def test_a_dataset_s_source_is_its_issuer_and_source() -> None:
    assert source_of("ojk:portal:bu_syariah_posisikeuangan") == "ojk:portal"


def test_a_macro_series_publishes_its_frequency_unit_and_marks() -> None:
    published = statistics([], {}, [macro_series({"2026-Q1": 783624.1, "2026-Q2": 889052.3})], KEYS,
                           citations={"bi:seki": "Bank Indonesia, SEKI"})

    (dataset,) = published.datasets
    assert (dataset.industry, dataset.register, dataset.citation) == (None, None, "Bank Indonesia, SEKI")
    assert (dataset.first_period, dataset.last_period) == (date(2026, 1, 1), date(2026, 4, 1))
    (series,) = published.series
    assert (series.frequency, series.unit) == ("quarterly", "Miliar Rp")
    assert [(o.period, o.value, o.provisional) for o in published.observations] == [
        (date(2026, 1, 1), 783624.1, False), (date(2026, 4, 1), 889052.3, True)
    ]


def test_a_period_is_published_as_its_first_day() -> None:
    halves = statistics([], {}, [macro_series({"2026-S2": 1.0}, Frequency.SEMIANNUAL)], KEYS).observations
    years = statistics([], {}, [macro_series({"2025": 1.0}, Frequency.ANNUAL)], KEYS).observations

    assert [o.period for o in halves + years] == [date(2026, 7, 1), date(2025, 1, 1)]


def test_series_come_in_parts_of_whole_datasets_each_at_least_the_size_asked() -> None:
    kas, piutang, lpbbti = records()

    parts = list(in_datasets([kas, piutang, lpbbti], size=1))

    assert parts == [[kas, piutang], [lpbbti]]  # a dataset is never split: its summary needs every series


def test_parts_gather_datasets_until_the_size_is_reached() -> None:
    assert [len(part) for part in in_datasets(records(), size=3)] == [3]
    assert list(in_datasets([], size=3)) == []


def test_series_out_of_dataset_order_stop_the_publish() -> None:
    kas, piutang, lpbbti = records()

    with pytest.raises(ValueError, match="not ordered by dataset: ojk:portal:bu_syariah_posisikeuangan"):
        list(in_datasets([kas, lpbbti, piutang], size=1))
