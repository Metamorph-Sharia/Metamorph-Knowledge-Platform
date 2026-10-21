import pytest
from metamorph_pdf_text import OcrMode, PageQuality, ReadRequest, Tier, request_for

CLEAN = PageQuality(characters=900, unknown_word_rate=0.01, confusions_per_thousand=0, damaged_headings=0, junk_rate=0)
NOISY = PageQuality(characters=900, unknown_word_rate=0.3, confusions_per_thousand=12, damaged_headings=0, junk_rate=0)


@pytest.mark.parametrize(("role", "tier"), [("main", Tier.STANDARD), ("annex", Tier.BASIC), ("faq", Tier.BASIC)])
def test_the_regulation_gets_the_vision_model_and_the_rest_the_small_models(role, tier) -> None:
    assert request_for(role, [CLEAN]) == ReadRequest(tier, OcrMode.AUTO)


def test_ocr_is_forced_when_more_than_a_fifth_of_the_text_layer_is_noisy() -> None:
    assert request_for("main", [NOISY, NOISY, CLEAN, CLEAN, CLEAN]).ocr_mode is OcrMode.OCR


def test_a_fifth_noisy_is_left_to_the_reader() -> None:
    assert request_for("main", [NOISY, CLEAN, CLEAN, CLEAN, CLEAN]).ocr_mode is OcrMode.AUTO


def test_a_file_without_a_text_layer_is_left_to_the_reader() -> None:
    assert request_for("main", []).ocr_mode is OcrMode.AUTO
