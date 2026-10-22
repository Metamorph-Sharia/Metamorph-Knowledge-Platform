from collections import Counter

from metamorph_pdf_text import aligned, respelled


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


def test_a_word_joined_at_its_hyphen_is_spelled_as_the_text_layer_has_it() -> None:
    # MinerU runs a paragraph's lines together and drops the hyphen a line ended with
    read = "sesuai dengan ketentuan peraturan perundangundangan, masingmasing pihak."
    layer = "sesuai dengan ketentuan peraturan perundang-\nundangan, masing-masing pihak."

    assert respelled(read, layer) == "sesuai dengan ketentuan peraturan perundang-undangan, masing-masing pihak."


def test_a_joined_word_the_text_layer_also_holds_stays() -> None:
    assert respelled("pertanggungjawaban", "pertanggungjawaban dan pertanggung-jawaban") == "pertanggungjawaban"
