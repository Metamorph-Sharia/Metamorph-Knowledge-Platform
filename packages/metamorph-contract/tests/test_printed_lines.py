"""A PDF page's text a printed line to a line, from PyMuPDF's layout of the page (as plain data, built here)."""

import pytest
from metamorph_contract import LINES_SETTING, printed_text, wants_printed_lines

SIZE = 12.0
CHAR = 6.0  # the width of a character, near enough


def line(text: str, x: float, baseline: float, *, size: float = SIZE, direction=(1.0, 0.0)) -> dict:
    return {
        "dir": direction,
        "bbox": (x, baseline - size, x + CHAR * len(text), baseline + size / 4),
        "spans": [{"text": text, "origin": (x, baseline), "size": size}],
    }


def layout(*blocks: list[dict]) -> dict:
    return {"blocks": [{"type": 0, "lines": lines} for lines in blocks]}


def plain(page: dict) -> str:
    """The page as `page.get_text()` gives it: each of the layout's lines, in order, on a line of its own."""
    lines = [line for block in page["blocks"] if block["type"] == 0 for line in block["lines"]]
    return "".join("".join(span["text"] for span in line["spans"]) + "\n" for line in lines)


def read(page: dict) -> str:
    return printed_text(plain(page), page)


def justified(words: list[str], baseline: float, x: float = 72.0, gap: float = 30.0) -> list[dict]:
    """A justified line as some PDFs set it: each word on its own, the gaps wide."""
    lines = []
    for word in words:
        lines.append(line(word, x, baseline))
        x += CHAR * len(word) + gap
    return lines


def test_a_justified_line_set_word_by_word_is_one_line() -> None:
    page = layout(justified(["selanjutnya ", "disebut ", "Pengolahan ", "adalah ", "kegiatan "], 100))

    assert read(page) == "selanjutnya disebut Pengolahan adalah kegiatan \n"


def test_a_lists_number_set_apart_from_its_text_is_on_its_line() -> None:
    page = layout([line("1.", 72, 100), line("Uang Rupiah adalah alat pembayaran", 100, 100)])

    assert read(page) == "1. Uang Rupiah adalah alat pembayaran\n"


def test_every_other_line_break_stays_where_it_was() -> None:
    page = layout(
        [line("Pasal 1", 250, 80)],
        [line("Dalam Peraturan ini yang dimaksud", 72, 100), line("dengan:", 72, 114)],
    )

    assert read(page) == "Pasal 1\nDalam Peraturan ini yang dimaksud\ndengan:\n"


def test_lines_of_separate_blocks_are_not_joined_even_on_one_baseline() -> None:
    page = layout([line("Ditetapkan di Jakarta", 72, 600)], [line("Diundangkan di Jakarta", 350, 600)])

    assert read(page) == "Ditetapkan di Jakarta\nDiundangkan di Jakarta\n"


def test_a_raised_footnote_number_or_a_line_back_to_the_left_is_a_line_of_its_own() -> None:
    raised = layout([line("bank syariah", 72, 100), line("1", 150, 95, size=7)])
    back = layout([line("halaman kedua", 300, 100), line("halaman pertama", 72, 100)])

    assert read(raised) == "bank syariah\n1\n"
    assert read(back) == "halaman kedua\nhalaman pertama\n"


def test_vertical_text_and_images_are_left_as_they_are() -> None:
    page = {
        "blocks": [
            {"type": 1, "bbox": (0, 0, 10, 10)},
            {"type": 0, "lines": [line("SALINAN", 20, 400, direction=(0.0, -1.0)), line("SALINAN", 100, 400)]},
        ]
    }

    assert read(page) == "SALINAN\nSALINAN\n"


def test_the_words_are_joined_by_one_space_however_their_spaces_fall() -> None:
    page = layout([line("dan", 72, 100), line("Logam", 120, 100), line(" ke", 200, 100), line("Bank ", 260, 100)])

    assert read(page) == "dan Logam ke Bank \n"


def test_a_line_without_spans_stays_an_empty_line() -> None:
    page = layout([line("SALINAN", 72, 100), {"dir": (1.0, 0.0), "bbox": (0, 0, 0, 0), "spans": []}])

    assert read(page) == "SALINAN\n\n"


def test_a_page_whose_layout_misses_some_of_its_text_is_left_as_pymupdf_reads_it() -> None:
    # Live: some BI FAQ files set glyphs with no width, and PyMuPDF's layout leaves them out while its text keeps them.
    page = layout(justified(["Penerbitan ", "PADG "], 100))
    text = "1.\nQ\nPenerbitan \nPerubahan\nPADG \n"

    assert printed_text(text, page) == text


def test_printed_lines_are_the_default_and_extracted_lines_bring_back_pymupdfs_own() -> None:
    assert wants_printed_lines({})
    assert wants_printed_lines({LINES_SETTING: "printed"})
    assert not wants_printed_lines({LINES_SETTING: "extracted"})
    with pytest.raises(ValueError, match="METAMORPH_PDF_LINES"):
        wants_printed_lines({LINES_SETTING: "extract"})  # a typo must not quietly pick one
