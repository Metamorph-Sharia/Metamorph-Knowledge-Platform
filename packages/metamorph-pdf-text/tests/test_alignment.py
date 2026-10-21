from collections import Counter

from metamorph_pdf_text import aligned


def test_the_same_words_in_another_order_keep_the_wording() -> None:
    alignment = aligned("Kolom kanan. Kolom kiri berlanjut.", "Kolom kiri berlanjut.\nKolom kanan.")

    assert alignment.keeps_wording


def test_spacing_and_punctuation_between_words_do_not_count() -> None:
    assert aligned("Pasal 5 , ayat ( 1 )", "Pasal 5, ayat (1)").keeps_wording


def test_a_word_dropped_or_misread_is_reported() -> None:
    alignment = aligned("Modal asing maksimal 497o", "Modal asing maksimal 49%")

    assert not alignment.keeps_wording
    assert alignment.missing == Counter({"49": 1})
    assert alignment.added == Counter({"497o": 1})


def test_a_word_repeated_once_too_often_is_reported() -> None:
    alignment = aligned("wajib wajib memiliki", "wajib memiliki")

    assert alignment.added == Counter({"wajib": 1})


def test_case_counts() -> None:
    assert not aligned("bank indonesia", "Bank Indonesia").keeps_wording
