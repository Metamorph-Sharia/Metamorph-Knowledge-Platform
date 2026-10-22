from metamorph_pdf_text import page_quality

VOCABULARY = {"setiap", "pelaku", "usaha", "wajib", "memiliki", "izin", "pasal", "dewan", "syariah", "nasional"}


def test_a_clean_page_is_not_noisy() -> None:
    quality = page_quality("Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin.", VOCABULARY)

    assert quality.unknown_word_rate == 0
    assert quality.confusions_per_thousand == 0
    assert not quality.is_noisy


def test_letter_spaced_words_are_unknown() -> None:
    quality = page_quality("Dew an Syar iah Nas ional", VOCABULARY)

    assert quality.unknown_word_rate == 1
    assert quality.is_noisy


def test_ocr_confusions_are_counted() -> None:
    quality = page_quality("REPUBL1K Pasal 1O BERUS!A wajib", VOCABULARY)

    assert quality.confusions_per_thousand == 3 / 5 * 1000


def test_damaged_headings_are_counted_not_roman_or_inserted_ones() -> None:
    text = "Pasa1 5\nPasal 1O\nP a s a l 3\nPasal II\nPasal 7B\nPasal 8"

    assert page_quality(text, VOCABULARY).damaged_headings == 3


def test_glyph_junk_is_measured() -> None:
    quality = page_quality("152 Penghimpunan Dana\n動物乃らθrc′′", VOCABULARY)

    assert quality.junk_rate == 5 / 28  # 動 物 乃 ら θ of 28 printed characters
    assert quality.is_noisy


def test_an_empty_page_has_no_rates() -> None:
    quality = page_quality("", VOCABULARY)

    assert (quality.characters, quality.unknown_word_rate, quality.junk_rate) == (0, 0, 0)
