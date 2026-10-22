"""A passage laid out for reading: its printed lines joined into paragraphs and list items (domain/layout.py)."""

from __future__ import annotations

import re

from metamorph_platform.domain.layout import Block, layout

DEFINITIONS = """\
Dalam Peraturan Anggota Dewan Gubernur ini yang
dimaksud dengan:
16. Pengolahan Uang Rupiah Kertas dan Logam yang
selanjutnya disebut Pengolahan adalah kegiatan
penyortiran dan penghitungan Uang Rupiah Kertas dan
Logam.
17. Penukaran Uang Rupiah Kertas dan Logam yang
selanjutnya disebut Penukaran adalah kegiatan.
"""


def wording(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_printed_lines_are_joined_into_a_paragraph_and_list_items_hang_from_their_number() -> None:
    assert layout(DEFINITIONS) == [
        Block("Dalam Peraturan Anggota Dewan Gubernur ini yang dimaksud dengan:"),
        Block(
            "Pengolahan Uang Rupiah Kertas dan Logam yang selanjutnya disebut Pengolahan adalah kegiatan "
            "penyortiran dan penghitungan Uang Rupiah Kertas dan Logam.",
            marker="16.",
        ),
        Block(
            "Penukaran Uang Rupiah Kertas dan Logam yang selanjutnya disebut Penukaran adalah kegiatan.", marker="17."
        ),
    ]


def test_a_line_split_a_word_at_a_time_or_a_number_alone_on_its_line_read_as_printed() -> None:
    """Texts extracted before printed lines (metamorph_contract.printed_lines) still read as a paragraph."""
    split = "16.\nPengolahan\nadalah\nkegiatan\npenyortiran dan penghitungan Uang Rupiah Kertas dan\nLogam.\n"

    assert layout(split) == [
        Block("Pengolahan adalah kegiatan penyortiran dan penghitungan Uang Rupiah Kertas dan Logam.", marker="16.")
    ]


def test_list_items_nest_by_the_order_their_kinds_of_number_appear() -> None:
    text = "(1) Perusahaan wajib:\na. melapor; dan\nb. membayar:\n1. pokok; dan\n2. bunga.\n(2) Laporan disampaikan.\n"

    assert [(block.marker, block.depth) for block in layout(text)] == [
        ("(1)", 0), ("a.", 1), ("b.", 1), ("1.", 2), ("2.", 2), ("(2)", 0),
    ]  # fmt: skip


def test_a_paragraph_ends_where_a_sentence_ends_well_short_of_the_line() -> None:
    text = (
        "Ketentuan lebih lanjut mengenai tata cara penyampaian laporan sebagaimana\n"
        "dimaksud diatur dalam Surat Edaran.\n"
        "Laporan yang disampaikan melewati batas waktu dianggap tidak menyampaikan\n"
        "laporan.\n"
    )

    assert [block.text[:20] for block in layout(text)] == ["Ketentuan lebih lanj", "Laporan yang disampa"]


def test_a_blank_line_a_line_in_capitals_and_a_heading_line_stand_apart() -> None:
    text = "PERATURAN BANK INDONESIA\nNOMOR 5 TAHUN 2026\nTENTANG\nUANG RUPIAH\n\nHuruf a\nCukup jelas.\n"

    assert [block.text for block in layout(text)] == [
        "PERATURAN BANK INDONESIA", "NOMOR 5 TAHUN 2026", "TENTANG", "UANG RUPIAH", "Huruf a", "Cukup jelas.",
    ]  # fmt: skip


def test_a_page_break_mid_sentence_is_a_page_start_in_its_paragraph_and_its_furniture_is_dropped() -> None:
    text = (
        "13. Pengedaran adalah suatu rangkaian kegiatan\n"
        "mengedarkan atau mendistribusikan Uang Rupiah\n"
        "\n"
        "<!-- page 3 -->\n"
        "3\n"
        "\n"
        "Kertas dan Logam di Wilayah Negara Kesatuan\n"
        "Republik Indonesia.\n"
    )

    [block] = layout(text)

    assert block.text == (
        "Pengedaran adalah suatu rangkaian kegiatan mengedarkan atau mendistribusikan Uang Rupiah Kertas dan Logam "
        "di Wilayah Negara Kesatuan Republik Indonesia."
    )
    assert block.pages == ((block.text.index("Kertas dan Logam"), 3),)


def test_a_catchword_at_a_pages_foot_is_dropped_and_a_page_starting_a_block_starts_at_its_first_word() -> None:
    text = "b. FPJPS jatuh tempo; dan/atau\n\nc.  FPJPS .…\n\n<!-- page 13 -->\n- 13 -\nc. FPJPS diakhiri.\n"

    blocks = layout(text)

    assert [(block.marker, block.text, block.pages) for block in blocks] == [
        ("b.", "FPJPS jatuh tempo; dan/atau", ()),
        ("c.", "FPJPS diakhiri.", ((0, 13),)),
    ]


def test_furniture_goes_only_from_a_pages_top_so_wording_that_looks_like_it_stays() -> None:
    letterhead = "<!-- page 5 -->\nPRESIDEN\nREPUBLIK INDONESIA\n- 5 -\n"
    text = letterhead + "Pasal ini berlaku di Negara Kesatuan\nRepublik Indonesia.\n"

    assert layout(text) == [Block("Pasal ini berlaku di Negara Kesatuan Republik Indonesia.", pages=((0, 5),))]


def test_a_number_alone_on_its_line_waits_for_its_wording_and_is_never_lost() -> None:
    ruling = "Pertama\n\n1.\n\nBerdasarkan sifatnya.\n"

    assert layout(ruling) == [Block("Pertama"), Block("Berdasarkan sifatnya.", "1.")]
    assert layout("I.\nKETENTUAN UMUM\n") == [Block("KETENTUAN UMUM", "I.")]
    assert layout("a.\nb. Dua.\n") == [Block("", "a."), Block("Dua.", "b.")]


def test_a_page_starting_after_a_passages_last_words_starts_at_its_end() -> None:
    assert layout("Satu.\n<!-- page 2 -->\n") == [Block("Satu.", pages=((5, 2),))]
    assert layout("Satu dan\n<!-- page 2 -->\n") == [Block("Satu dan", pages=((8, 2),))]


def test_a_catchword_is_dropped_even_where_the_text_marks_no_page() -> None:
    """OJK's own texts carry no page markers, but do carry each page's catchword ("4. Perusahaan...")."""
    text = "3. Perusahaan Pembiayaan adalah badan usaha.\n4. Perusahaan...\n\n4. Perusahaan Penjaminan adalah badan.\n"

    assert [(block.marker, block.text) for block in layout(text)] == [
        ("3.", "Perusahaan Pembiayaan adalah badan usaha."),
        ("4.", "Perusahaan Penjaminan adalah badan."),
    ]


def test_a_word_hyphenated_across_lines_keeps_its_hyphen_and_loses_the_space() -> None:
    assert layout("masing-\nmasing pihak.\n") == [Block("masing-masing pihak.")]


def test_only_whitespace_and_page_furniture_change_never_the_wording() -> None:
    blocks = layout(DEFINITIONS + "<!-- page 4 -->\n4\nLanjutan teks.\n")

    laid_out = "".join((block.marker or "") + block.text for block in blocks)
    assert wording(laid_out) == wording(DEFINITIONS + "Lanjutan teks.")


def test_a_passage_without_wording_lays_out_to_nothing() -> None:
    assert layout("") == [] and layout("\n \n") == []


def test_a_passage_holding_only_a_page_turn_keeps_it_so_the_reader_shows_where_the_page_starts() -> None:
    assert layout("\n<!-- page 2 -->\n2\n") == [Block("", pages=((0, 2),))]
