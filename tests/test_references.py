"""Mentions of other instruments in a legal text, and the canonical IDs they name."""

from __future__ import annotations

import pytest

from metamorph_platform.domain.references import references


def ids(text: str) -> list[str | None]:
    return [reference.target_id for reference in references(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Undang-Undang Nomor 21 Tahun 2011 tentang Otoritas Jasa Keuangan", "id:uu:2011:21"),
        ("Undang-Undang Republik Indonesia Nomor 4 Tahun 2023", "id:uu:2023:4"),
        ("Peraturan Pemerintah Pengganti Undang-Undang Nomor 2 Tahun 2008", "id:perppu:2008:2"),
        ("Peraturan Pemerintah Nomor 5 Tahun 2021", "id:pp:2021:5"),
        ("Peraturan Presiden Nomor 10 Tahun 2021", "id:perpres:2021:10"),
        ("Peraturan Menteri Keuangan Nomor 130/PMK.010/2012", "id:pmk:2012:130"),
        ("Peraturan Otoritas Jasa Keuangan Nomor 10 /POJK.05/2019", "ojk:pojk:2019:10"),
        ("Peraturan Otoritas Jasa Keuangan Nomor 11 Tahun 2022", "ojk:pojk:2022:11"),
        ("Surat Edaran Otoritas Jasa Keuangan Nomor 1/SEOJK.04/2020", "ojk:seojk:2020:1"),
        ("Peraturan Anggota Dewan Komisioner Otoritas Jasa Keuangan Nomor 1 Tahun 2026", "ojk:padk:2026:1"),
        ("Peraturan\nBank\nIndonesia\nNomor\n22/23/PBI/2020", "bi:pbi:2020:23"),
        ("Peraturan Bank Indonesia Nomor 1 Tahun 2025", "bi:pbi:2025:1"),
        ("Peraturan Anggota Dewan Gubernur Nomor 24/8/PADG/2022", "bi:padg:2022:8"),
        ("Surat Edaran Bank Indonesia Nomor 15/34/DPSP", "bi:sebi:2013:34"),
        ("Fatwa DSN-MUI Nomor 01/DSNMUI/IV/2000 tentang Giro", "dsnmui:fatwa:1"),
        ("Fatwa Dewan Syariah Nasional (DSN) Nomor 96/DSN-MUI/IV/2015", "dsnmui:fatwa:96"),
    ],
)
def test_each_kind_of_instrument_is_recognised(text, expected):
    assert ids(text) == [expected]


def test_several_mentions_are_found_in_reading_order_with_their_spans():
    text = (
        "Undang-Undang Nomor 23 Tahun 1999 tentang Bank Indonesia sebagaimana telah diubah dengan "
        "Undang-Undang Nomor 6 Tahun 2009 tentang Penetapan Peraturan Pemerintah Pengganti Undang-Undang "
        "Nomor 2 Tahun 2008"
    )

    found = references(text)

    assert [r.target_id for r in found] == ["id:uu:1999:23", "id:uu:2009:6", "id:perppu:2008:2"]
    assert text[found[0].start : found[0].end] == "Undang-Undang Nomor 23 Tahun 1999"


def test_a_mention_without_a_number_names_nothing():
    assert references("sebagaimana dimaksud dalam Undang-Undang mengenai perbankan") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("POJK Nomor 10/POJK.04 Tahun 2018 tentang Penerapan Tata Kelola Manajer Investasi", "ojk:pojk:2018:10"),
        ("SEOJK Nomor 24/SEOJK.03 Tahun 2016 tentang Perhitungan Aset Tertimbang", "ojk:seojk:2016:24"),
        ("Keputusan Presiden Nomor 84/P Tahun 2009", "id:keppres:2009:84"),
        ("Peraturan Otoritas Jasa Keuangan Nomor 27/POJK.03/201 Tahun 2015", "ojk:pojk:2015:27"),  # cut short
        ("Peraturan Bank Indonesia Nomor 10/4/PBI Tahun 2008", "bi:pbi:2008:4"),
    ],
)
def test_a_slashed_number_may_give_its_year_after_tahun(text, expected):
    """JDIH OJK writes 10/POJK.04 Tahun 2018 for 10/POJK.04/2018."""
    assert ids(text) == [expected]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("POJK Nomor POJK Nomor 3/POJK.05 Tahun 2013 tentang Laporan Bulanan", "ojk:pojk:2013:3"),
        ("POJK Nomor Nomor 24/POJK.05 Tahun 2019 tentang Rencana Bisnis", "ojk:pojk:2019:24"),
        ("POJK Nomor Peraturan Otoritas Jasa Keuangan Nomor 52/POJK.04 Tahun 2020", "ojk:pojk:2020:52"),
    ],
)
def test_a_label_the_source_repeats_names_one_instrument(text, expected):
    """JDIH OJK puts its own "POJK Nomor" before the citation as the regulation writes it."""
    assert ids(text) == [expected]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SEOJK Nomor POJK Nomor 3/SEOJK.03 Tahun 2021", "ojk:seojk:2021:3"),
        ("POJK Nomor POJK Nomor 24 /SEOJK.04 Tahun 2022 tentang Perlakuan Akuntansi", "ojk:seojk:2022:24"),
        ("Surat Edaran Otoritas Jasa Keuangan Nomor 5/POJK.03/2016", "ojk:pojk:2016:5"),
    ],
)
def test_an_ojk_number_names_its_kind_over_the_label(text, expected):
    """OJK's numbers carry the kind (10/POJK.05/2019, 1/SEOJK.04/2020); a label can be the source's mistake."""
    assert ids(text) == [expected]


def test_a_number_without_its_year_still_names_nothing():
    assert ids("Keputusan Presiden Nomor 56/P") == [None]
