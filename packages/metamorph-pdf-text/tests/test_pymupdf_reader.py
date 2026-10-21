import pytest
from metamorph_pdf_text import ExtractionFailed, OcrMode, ReadRequest, Tier
from metamorph_pdf_text.adapters.pymupdf_reader import PyMuPdfReader
from pdf_text_files import A4, pdf, regulation_pdf

REQUEST = ReadRequest(Tier.STANDARD, OcrMode.AUTO)


def test_each_text_block_is_a_block_where_it_sits() -> None:
    page = PyMuPdfReader().read(regulation_pdf(), REQUEST).pages[0]

    assert (page.number, page.width, page.height) == (1, *A4)
    assert [block.text for block in page.blocks] == [
        "BANK INDONESIA",
        "Pasal 5",
        "Setiap Pelaku Usaha wajib\nmemiliki izin.",  # its plain text has a word a line
        "SK No 054949 C",
    ]
    assert page.blocks[0].bbox.y1 < 0.12 * A4[1] < 0.88 * A4[1] < page.blocks[-1].bbox.y0


def test_it_reads_the_text_layer_whatever_is_asked() -> None:
    assert PyMuPdfReader().read(regulation_pdf(), ReadRequest(Tier.BASIC, OcrMode.OCR)).ocr_mode is OcrMode.TXT


def test_a_page_without_text_has_no_blocks() -> None:
    assert PyMuPdfReader().read(pdf(), REQUEST).pages[0].blocks == ()


def test_a_file_that_isnt_a_pdf_fails() -> None:
    with pytest.raises(ExtractionFailed):
        PyMuPdfReader().read(b"PK\x03\x04 a zip", REQUEST)
