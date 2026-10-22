import pytest
from metamorph_pdf_text import BBox, BlockKind, ExtractionFailed, OcrMode, clean, render
from metamorph_pdf_text.adapters.mineru_layout import reading_from_middle_json
from pdf_text_files import middle_json


def test_pages_are_numbered_from_one_and_the_resolved_mode_is_kept() -> None:
    reading = reading_from_middle_json(middle_json())

    assert [page.number for page in reading.pages] == [1, 2]
    assert reading.ocr_mode is OcrMode.TXT


def test_each_block_type_is_translated() -> None:
    first = reading_from_middle_json(middle_json()).pages[0]

    assert [block.kind for block in first.blocks] == [
        BlockKind.HEADER,
        BlockKind.TITLE,
        BlockKind.TITLE,
        BlockKind.TEXT,
        BlockKind.LIST_ITEM,
        BlockKind.LIST_ITEM,
        BlockKind.TEXT,  # the table's caption
        BlockKind.TABLE,
        BlockKind.FOOTNOTE,
        BlockKind.FOOTER,
        BlockKind.PAGE_NUMBER,
    ]


def test_bboxes_stay_normalised_to_a_page_of_one_by_one() -> None:
    first = reading_from_middle_json(middle_json()).pages[0]

    assert (first.width, first.height) == (1.0, 1.0)
    assert first.blocks[0].bbox == BBox(0.38, 0.03, 0.62, 0.07)


def test_a_link_keeps_its_wording() -> None:
    item = reading_from_middle_json(middle_json()).pages[0].blocks[4]

    assert item.text.endswith("sebagaimana dimaksud dalam Undang-Undang Nomor 25 Tahun 2007.")


def test_a_table_body_is_its_rows_of_cells() -> None:
    table = reading_from_middle_json(middle_json()).pages[0].blocks[7]

    assert table.text == "No.\tBidang Usaha\tKBLI\n21\tAngkutan penyeberangan perintis\t50217"


def test_an_equation_is_a_formula_and_an_image_has_no_block() -> None:
    reading = reading_from_middle_json(middle_json())

    assert [block.kind for block in reading.pages[1].blocks] == [BlockKind.FORMULA, BlockKind.TEXT]
    assert BlockKind.IMAGE not in {block.kind for block in reading.pages[0].blocks}


def test_a_block_type_unknown_to_the_translation_keeps_its_wording() -> None:
    document = middle_json()
    document["pages"][1]["blocks"][1]["type"] = "a_newer_block_type"

    assert reading_from_middle_json(document).pages[1].blocks[1].text.startswith("Peraturan Presiden ini")


def test_a_blank_page_mineru_writes_without_blocks_is_an_empty_page() -> None:
    # MinerU leaves out a default: a page with nothing on it is {"page_idx": 69} (PADG 19/6/PADG/2017, page 70)
    document = middle_json()
    del document["pages"][1]["blocks"]

    reading = reading_from_middle_json(document)

    assert [page.number for page in reading.pages] == [1, 2]
    assert reading.pages[1].blocks == ()


def test_cleaned_and_rendered_the_page_reads_as_the_parser_expects() -> None:
    page = render(clean(reading_from_middle_json(middle_json()).pages).pages)[0]

    assert page.startswith("PRESIDEN REPUBLIK INDONESIA\n\nPERATURAN PRESIDEN")  # the first page's head stays
    assert "\n\nPasal 1\n\nDalam Peraturan Presiden ini" in page
    assert "\n\n1. Penanaman Modal adalah" in page
    assert "No. | Bidang Usaha | KBLI\n21 | Angkutan penyeberangan perintis | 50217" in page
    assert "SK No" not in page and "- 1 -" not in page


@pytest.mark.parametrize(
    "broken",
    [
        lambda document: document.update(schema="docvortex.model"),
        lambda document: document.update(schema_version="1.0"),
        lambda document: document["extensions"].pop("mineru"),
        lambda document: document["extensions"]["mineru"].update(parse_mode="auto"),
    ],
)
def test_a_document_of_another_shape_fails(broken) -> None:
    document = middle_json()
    broken(document)

    with pytest.raises(ExtractionFailed):
        reading_from_middle_json(document)
