import pytest
from metamorph_pdf_text import BlockKind, clean
from pdf_text_pages import FOOT, TOP, annex_page, block, page


def texts(cleaned) -> list[list[str]]:
    return [[block.text for block in page.blocks] for page in cleaned.pages]


def removed(cleaned, rule: str) -> list[tuple[int, str]]:
    return [(removal.page, removal.text) for removal in cleaned.removals if removal.rule == rule]


# Furniture the reader marked


@pytest.mark.parametrize("kind", [BlockKind.HEADER, BlockKind.FOOTER, BlockKind.PAGE_NUMBER, BlockKind.ASIDE])
def test_a_block_the_reader_marks_as_furniture_goes(kind) -> None:
    cleaned = clean([page(1, block("Pasal 1")), page(2, block("BANK INDONESIA", TOP, kind), block("Wording."))])

    assert texts(cleaned) == [["Pasal 1"], ["Wording."]]
    assert removed(cleaned, "furniture") == [(2, "BANK INDONESIA")]


def test_a_marked_block_that_opens_a_provision_stays() -> None:
    marked = [block("Pasal 12", TOP, BlockKind.HEADER), block("(2) Ketentuan lebih lanjut", FOOT, BlockKind.FOOTER)]

    cleaned = clean([page(1, block("Pasal 11")), page(2, *marked)])

    assert texts(cleaned)[1] == ["Pasal 12", "(2) Ketentuan lebih lanjut"]


@pytest.mark.parametrize("label", ["Mengingat", "Menimbang :", "MEMUTUSKAN:", "Kedua :"])
def test_an_opening_label_or_ruling_in_the_margin_stays(label) -> None:
    # MinerU marks the preamble's labels, set in a column of their own, as text beside the page (aside_text)
    cleaned = clean([page(1, block("Pasal 1")), page(2, block(label, kind=BlockKind.ASIDE), block("1. Undang-Undang"))])

    assert texts(cleaned)[1] == [label, "1. Undang-Undang"]


def test_the_first_pages_head_stays_it_names_the_issuer() -> None:
    cleaned = clean([page(1, block("PRESIDEN\nREPUBLIK INDONESIA", TOP, BlockKind.HEADER), block("Menimbang"))])

    assert texts(cleaned) == [["PRESIDEN\nREPUBLIK INDONESIA", "Menimbang"]]


# The print serial


@pytest.mark.parametrize(
    "serial", ["SK No 054949 C", "SK No 054949C", "SK No ll5207 C", "SK N0 I05207 A", "SK No. 054949"]
)
def test_the_print_serial_goes_as_printed_or_misread(serial) -> None:
    cleaned = clean([page(1, block(f"dan pemilik modal nasional\n{serial}", FOOT))])

    assert texts(cleaned) == [["dan pemilik modal nasional"]]
    assert removed(cleaned, "serial") == [(1, serial)]


@pytest.mark.parametrize(  # as OCR misread it in BPK's text layers
    "serial",
    ["SK No l19tt6l C", "SK No I l29l2c", "SK No 1478M C", "SK No LIS5611A", "SK No 115627 A:", "SK No 067-569 A"],
)
def test_the_print_serial_goes_however_ocr_misread_it(serial) -> None:
    assert removed(clean([page(1, block(f"Pasal 1\n{serial}", FOOT))]), "serial") == [(1, serial)]


@pytest.mark.parametrize(
    "wording",
    ["berdasarkan SK No 12 Tahun 2020 tentang", "SK No 12 Tahun 2020 tentang", "SK No 12 Tahun", "SK Nomor 12/2020"],
)
def test_a_line_naming_a_decree_number_stays(wording) -> None:
    assert texts(clean([page(1, block(wording))])) == [[wording]]


# Lines repeated at the top or foot of the pages


def test_a_running_head_and_page_number_go_however_the_page_misreads_them() -> None:
    heads = ["PRES I DEN\nREPUBLIK INDONESIA", "PRES IDEN\nREPUBLIK INDONESTA", "PRESIDEN\nREPUBLIK INDONESIA"]
    pages = [annex_page(1)] + [annex_page(number, head) for number, head in enumerate(heads, start=2)]

    cleaned = clean(pages)

    assert [blocks[0] for blocks in texts(cleaned)[1:]] == [
        "22. Angkutan sungai dan danau untuk barang umum\nModal asing maksimal 49%",
        "23. Angkutan sungai dan danau untuk barang umum\nModal asing maksimal 49%",
        "24. Angkutan sungai dan danau untuk barang umum\nModal asing maksimal 49%",
    ]
    assert (3, "PRES IDEN") in removed(cleaned, "repeated")
    assert (3, "REPUBLIK INDONESTA") in removed(cleaned, "repeated")
    assert (3, "-3-") in removed(cleaned, "repeated")


def test_the_first_pages_running_head_stays() -> None:
    cleaned = clean([annex_page(number) for number in range(1, 5)])

    assert texts(cleaned)[0][0] == "PRES I DEN\nREPUBLIK INDONESIA\n-1-"


def test_headings_that_open_every_page_stay() -> None:
    pages = [page(number, block(f"Pasal {number}\nCukup jelas.", TOP)) for number in range(1, 6)]

    cleaned = clean(pages)

    assert texts(cleaned) == [[f"Pasal {number}\nCukup jelas."] for number in range(1, 6)]


def test_wording_that_recurs_at_the_top_of_pages_stays() -> None:
    pages = [page(number, block("Cukup jelas.\nHuruf b", TOP)) for number in range(1, 6)]

    cleaned = clean(pages)

    assert all(blocks == ["Cukup jelas.\nHuruf b"] for blocks in texts(cleaned))


def test_a_printed_page_number_goes_when_it_follows_the_pages() -> None:
    pages = [page(number, block("Wording."), block(f"- {number - 1} -", FOOT)) for number in range(1, 6)]

    cleaned = clean(pages)  # an unnumbered cover: page 2 prints "1"

    assert texts(cleaned) == [["Wording."]] * 5


def test_numbers_at_the_top_of_a_table_that_dont_follow_the_pages_stay() -> None:
    rows = [21, 34, 35, 52, 60]  # a KBLI table's row numbers, OCR having dropped their full stops
    pages = [page(number, block(f"{row}\nAngkutan sungai dan danau", TOP)) for number, row in enumerate(rows, start=1)]

    cleaned = clean(pages)

    assert [blocks[0].split("\n")[0] for blocks in texts(cleaned)] == ["21", "34", "35", "52", "60"]


def test_the_first_place_of_a_recurring_line_stays() -> None:
    pages = [page(1, block("Pasal 1"))] + [
        page(number, block("BIDANG USAHA\nKBLI", TOP), block(f"Baris {number}")) for number in range(2, 6)
    ]

    cleaned = clean(pages)

    assert [blocks[0] for blocks in texts(cleaned)] == [
        "Pasal 1",
        "BIDANG USAHA\nKBLI",
        "Baris 3",
        "Baris 4",
        "Baris 5",
    ]


def test_an_annexs_title_stays_on_every_page_it_heads() -> None:
    pages = [
        page(number, block(f"LAMPIRAN {numeral}", TOP)) for number, numeral in enumerate(["I", "I", "II", "II"], 1)
    ]

    assert [blocks[0] for blocks in texts(clean(pages))] == ["LAMPIRAN I", "LAMPIRAN I", "LAMPIRAN II", "LAMPIRAN II"]


def test_a_line_in_the_middle_of_a_page_is_never_judged_by_repetition() -> None:
    pages = [page(number, block("SALINAN"), block(f"Pasal {number}")) for number in range(1, 6)]

    cleaned = clean(pages)

    assert all(blocks[0] == "SALINAN" for blocks in texts(cleaned))


def test_a_short_document_keeps_its_band_lines() -> None:
    cleaned = clean([page(number, block("BANK INDONESIA", TOP), block("Wording.")) for number in (1, 2)])

    assert texts(cleaned)[1] == ["BANK INDONESIA", "Wording."]  # two pages are too few to tell


# Catchwords


def test_a_catchword_the_next_page_opens_with_goes() -> None:
    cleaned = clean(
        [page(1, block("menetapkan Peraturan.\nPasal 5 . . .", FOOT)), page(2, block("Pasal 5\n(1) Setiap"))]
    )

    assert texts(cleaned)[0] == ["menetapkan Peraturan."]
    assert removed(cleaned, "catchword") == [(1, "Pasal 5 . . .")]


def test_the_annex_pages_catchword_goes() -> None:
    cleaned = clean([annex_page(3), annex_page(4)])

    assert removed(cleaned, "catchword") == [(3, "24. Angkutan .")]


def test_a_closing_ellipsis_the_next_page_does_not_continue_stays() -> None:
    cleaned = clean([page(1, block("dan seterusnya ...")), page(2, block("Pasal 6"))])

    assert texts(cleaned)[0] == ["dan seterusnya ..."]


# Tidying


@pytest.mark.parametrize(
    ("lines", "joined"),
    [
        ("kegiatan usaha perusa-\nhaan efek", "kegiatan usaha perusahaan efek"),
        ("para badan-\nbadan usaha", "para badan-badan usaha"),
        ("sebagaimana dimaksud dalam Undang-\nUndang Nomor 21", "sebagaimana dimaksud dalam Undang-Undang Nomor 21"),
        ("Bank Indonesia-\nOtoritas Jasa Keuangan", "Bank Indonesia-\nOtoritas Jasa Keuangan"),
    ],
)
def test_a_word_hyphenated_across_lines_is_joined(lines, joined) -> None:
    assert texts(clean([page(1, block(lines))])) == [[joined]]


def test_spaces_are_collapsed_and_empty_lines_and_blocks_go() -> None:
    cleaned = clean([page(1, block("  Pasal   5  \n\n(1)  Setiap"), block("  \n"))])

    assert texts(cleaned) == [["Pasal 5\n(1) Setiap"]]


def test_cleaning_never_changes_a_word_it_keeps() -> None:
    pages = [annex_page(number) for number in range(1, 5)]

    cleaned = clean(pages)

    kept = {word for blocks in texts(cleaned) for text in blocks for word in text.split()}
    original = {word for page in pages for block in page.blocks for word in block.text.split()}
    assert kept <= original


# Text a vision model wrote about a picture, instead of reading it


CHART = (
    "The chart displays the distribution of data points across different categories, with a notable "
    "concentration in the lower range and sparse outliers extending towards higher values."
)
NO_TEXT = "The image contains no discernible text or characters. Therefore, the correct OCR output is an empty string."


def test_a_models_description_of_a_picture_goes_from_a_page_read_from_its_image() -> None:
    # PERMA 2/2015, page 7: MinerU's OCR of a scan, a speckled region described in English
    pages = [page(7, block(CHART), block(NO_TEXT), block("Pasal 11"), block("(1) Hakim memeriksa materi gugatan."))]

    cleaned = clean(pages, from_images={7})

    assert texts(cleaned) == [["Pasal 11", "(1) Hakim memeriksa materi gugatan."]]
    assert removed(cleaned, "generated") == [(7, CHART), (7, NO_TEXT)]


def test_english_wording_on_a_page_read_from_its_characters_stays() -> None:
    assert texts(clean([page(1, block(CHART))])) == [[CHART]]


def test_indonesian_wording_with_english_terms_stays() -> None:
    wording = "Rasio loan to value untuk kredit properti dan uang muka untuk kredit kendaraan bermotor yang berlaku."

    assert texts(clean([page(1, block(wording))], from_images={1})) == [[wording]]
