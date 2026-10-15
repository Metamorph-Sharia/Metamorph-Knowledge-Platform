"""Dates a document states about itself: when it was enacted, promulgated, and takes effect."""

from __future__ import annotations

from datetime import date

from metamorph_platform.domain.dates import TextDates, text_dates

CLOSING = """\
Pasal 50
Peraturan Otoritas Jasa Keuangan ini mulai berlaku pada tanggal diundangkan.
Ditetapkan di Jakarta
pada tanggal 26 Februari 2019
KETUA DEWAN KOMISIONER,
Diundangkan di Jakarta
pada tanggal 27 Februari 2019
"""


def test_enactment_promulgation_and_entry_into_force_on_promulgation():
    assert text_dates(CLOSING) == TextDates(
        enacted=date(2019, 2, 26), promulgated=date(2019, 2, 27), effective=date(2019, 2, 27)
    )


def test_entry_into_force_on_enactment():
    circular = (
        "Surat Edaran ini mulai berlaku pada tanggal ditetapkan.\nDitetapkan di Jakarta\npada tanggal 3 Maret 2020\n"
    )

    assert text_dates(circular) == TextDates(enacted=date(2020, 3, 3), effective=date(2020, 3, 3))


def test_an_explicit_date_of_entry_into_force_wins():
    text = "Peraturan ini mulai berlaku pada tanggal 1 Januari 2020.\n" + CLOSING.split("Pasal 50\n")[0] + CLOSING[-80:]

    assert text_dates(text).effective == date(2020, 1, 1)


def test_the_last_entry_into_force_is_the_regulation_s_own():
    """Transitional articles say when *some* provisions apply; the closing article speaks for the whole."""
    text = "Ketentuan Pasal 5 mulai berlaku pada tanggal 1 Juli 2021.\n" + CLOSING

    assert text_dates(text).effective == date(2019, 2, 27)


def test_a_fatwa_dated_in_both_calendars_keeps_the_gregorian_date():
    fatwa = "Ditetapkan di : Jakarta\nTanggal : 16 Shafar 1439 H\n06 November 2017 M\n"

    assert text_dates(fatwa).enacted == date(2017, 11, 6)


def test_a_text_without_dates_has_none():
    assert text_dates("Pasal 1\nIsi.\n") == TextDates()
