"""Reading a text as the parser cut it: passages in reading order, parts of a bounded size, offsets for an editor."""

from __future__ import annotations

from dataclasses import dataclass

from metamorph_platform.domain.reading import Passage, list_depth, parts, passages, split_long, utf16_offsets

TEXT = """\
PERATURAN OTORITAS JASA KEUANGAN
NOMOR 10/POJK.05/2019
BAB I
KETENTUAN UMUM
Pasal 1
Dalam Peraturan ini yang dimaksud dengan Perusahaan adalah perusahaan pembiayaan.
Pasal 2
(1) Perusahaan wajib melapor.
(2) Laporan disampaikan setiap bulan.
Ditetapkan di Jakarta
"""


@dataclass(frozen=True)
class Unit:
    address: str
    parent_address: str | None
    label: str
    heading: str | None
    char_start: int
    char_end: int


def unit(address, parent, label, heading, start_text, end_text=None) -> Unit:
    start = TEXT.index(start_text)
    end = TEXT.index(end_text) if end_text else len(TEXT)
    return Unit(address, parent, label, heading, start, end)


UNITS = [
    unit("bab-i", None, "BAB I", "KETENTUAN UMUM", "BAB I", "Ditetapkan"),
    unit("pasal-1", "bab-i", "Pasal 1", None, "Pasal 1", "Pasal 2"),
    unit("pasal-2", "bab-i", "Pasal 2", None, "Pasal 2", "Ditetapkan"),
    unit("pasal-2/ayat-1", "pasal-2", "(1)", None, "(1)", "(2)"),
    unit("pasal-2/ayat-2", "pasal-2", "(2)", None, "(2)", "Ditetapkan"),
]


def test_each_character_is_read_once_in_the_innermost_provision_that_holds_it() -> None:
    read = passages(TEXT, UNITS)

    assert read == [
        Passage(None, "PERATURAN OTORITAS JASA KEUANGAN\nNOMOR 10/POJK.05/2019\n", opens=False),
        Passage("bab-i", "", opens=True, titled=True),
        Passage("pasal-1", "Dalam Peraturan ini yang dimaksud dengan Perusahaan adalah perusahaan pembiayaan.\n",
                opens=True, titled=True),
        Passage("pasal-2", "", opens=True, titled=True),
        Passage("pasal-2/ayat-1", "(1) Perusahaan wajib melapor.\n", opens=True),
        Passage("pasal-2/ayat-2", "(2) Laporan disampaikan setiap bulan.\n", opens=True),
        Passage(None, "Ditetapkan di Jakarta\n", opens=False),
    ]  # fmt: skip
    assert "".join(p.text for p in read) == TEXT.replace("BAB I\nKETENTUAN UMUM\n", "").replace(
        "Pasal 1\n", ""
    ).replace("Pasal 2\n", "")


def test_a_label_opening_the_wording_on_its_line_is_taken_off_it_as_the_heading() -> None:
    """Printed a line to a line, a fatwa's ruling shares its line with its first item (dsnmui:fatwa:24)."""
    text = "Menimbang : a. bahwa perlu diatur;\n"
    ruling = "Pertama 1. Berdasarkan sifatnya,\nSDB adalah ijarah.\n"

    assert passages(text, [Unit("menimbang", None, "Menimbang", None, 0, len(text))]) == [
        Passage("menimbang", "a. bahwa perlu diatur;\n", opens=True, titled=True)
    ]
    assert passages(ruling, [Unit("diktum-pertama", None, "Pertama", None, 0, len(ruling))]) == [
        Passage("diktum-pertama", "1. Berdasarkan sifatnya,\nSDB adalah ijarah.\n", opens=True, titled=True)
    ]


def test_a_heading_split_by_a_page_break_is_still_taken_off_and_the_page_break_kept() -> None:
    """UU 42/1999: "BAB I", then the next page, then its title."""
    text = "BAB I\n<!-- page 2 -->\n2\nKETENTUAN UMUM\n"
    chapter = Unit("bab-i", None, "BAB I", "KETENTUAN UMUM", 0, len(text))

    assert passages(text, [chapter]) == [Passage("bab-i", "<!-- page 2 -->\n2\n", opens=True, titled=True)]


def test_a_heading_printed_with_its_label_on_one_line_is_taken_off_and_so_is_a_catchword_repeating_it() -> None:
    """BI: "BAB VI" at a page's foot (the next page's first words), then the page's "BAB VI KETENTUAN PENUTUP"."""
    text = "BAB VI\n<!-- page 16 -->\nBAB VI KETENTUAN PENUTUP\n"
    chapter = Unit("bab-vi", None, "BAB VI", "KETENTUAN PENUTUP", 0, len(text))

    assert passages(text, [chapter]) == [Passage("bab-vi", "<!-- page 16 -->\n", opens=True, titled=True)]


def test_a_paragraphs_number_stays_in_its_wording_where_it_hangs() -> None:
    text = "(1) Perusahaan wajib melapor.\n"

    assert passages(text, [Unit("pasal-1/ayat-1", None, "(1)", None, 0, len(text))]) == [
        Passage("pasal-1/ayat-1", text, opens=True)
    ]


def test_a_heading_line_ending_in_a_colon_is_still_the_heading() -> None:
    text = "MEMUTUSKAN:\nMenetapkan : PERATURAN OTORITAS JASA KEUANGAN.\n"
    decided = Unit("memutuskan", None, "MEMUTUSKAN", None, 0, len(text))

    assert passages(text, [decided]) == [
        Passage("memutuskan", "Menetapkan : PERATURAN OTORITAS JASA KEUANGAN.\n", opens=True, titled=True)
    ]


def test_a_text_the_parser_found_nothing_in_is_one_passage() -> None:
    assert passages("Sebuah halaman web.\n", []) == [Passage(None, "Sebuah halaman web.\n", opens=False)]


def test_a_passage_longer_than_a_part_is_cut_at_line_ends() -> None:
    long = Passage("lampiran-i", "a" * 6 + "\n" + "b" * 6 + "\n" + "c" * 3 + "\n", opens=True, titled=True)

    assert split_long([long], limit=10) == [
        Passage("lampiran-i", "a" * 6 + "\n", opens=True, titled=True),
        Passage("lampiran-i", "b" * 6 + "\n", opens=False),
        Passage("lampiran-i", "c" * 3 + "\n", opens=False),
    ]


def test_passages_are_grouped_into_parts_no_larger_than_the_budget_and_never_empty() -> None:
    read = [Passage(None, "x" * size, opens=False) for size in (4, 4, 4, 20, 1)]

    assert parts(read, budget=10) == [0, 0, 1, 2, 3]


def test_offsets_count_as_an_editor_does_in_utf16_units() -> None:
    text = "a😀b😀c"

    assert utf16_offsets(text, [0, 1, 2, 3, 5]) == {0: 0, 1: 1, 2: 3, 3: 4, 5: 7}


def test_an_items_letter_stays_in_its_wording_where_it_hangs() -> None:
    text = "a. bahwa untuk melaksanakan ketentuan;\n"

    assert passages(text, [Unit("menimbang/huruf-a", None, "a.", None, 0, len(text))]) == [
        Passage("menimbang/huruf-a", text, opens=True)
    ]


def test_an_items_marker_hangs_at_the_depth_of_its_list() -> None:
    assert [list_depth(a) for a in ("pasal-1", "pasal-1/angka-2", "pasal-2/ayat-1", "pasal-2/ayat-1/huruf-a")] == [
        0, 0, 0, 1,
    ]  # fmt: skip
    assert list_depth("pasal-1/angka-2/huruf-a/angka-1") == 2
    assert list_depth("penjelasan/pasal-1/huruf-a") == 0
