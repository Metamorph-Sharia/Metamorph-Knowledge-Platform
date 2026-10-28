"""Reports cut into passages with their pages (market-data-layer-plan.md, Phase 4: Passages)."""

from __future__ import annotations

from dataclasses import replace

from market_platform_samples import report_record
from metamorph_contract import join_pages

from metamorph_platform.domain.market.reports import MAX_WORDS, MIN_WORDS, passages, reports


def paragraph(count: int, word: str = "kata") -> str:
    return " ".join([word] * count)


def test_paragraphs_gather_into_passages_of_about_250_words() -> None:
    text = join_pages(["\n\n".join(paragraph(100) for _ in range(5))])

    first, second = passages(text)

    assert (first.words, second.words) == (300, 200)  # 300 reached the minimum; the tail of 200 doesn't fit in 400
    assert (first.address, second.address) == ("p-1", "p-2")


def test_a_passage_never_passes_400_words() -> None:
    text = join_pages(["\n\n".join([paragraph(200), paragraph(150), paragraph(200)])])

    assert [passage.words for passage in passages(text)] == [350, 200]


def test_a_passage_carries_the_pages_it_spans() -> None:
    text = join_pages([paragraph(120), paragraph(120), "", paragraph(120)])

    (first,) = passages(text)  # 360 words over pages 1-4; page 3 holds nothing

    assert (first.page_start, first.page_end, first.words) == (1, 4, 360)


def test_a_paragraph_longer_than_400_words_is_split_at_its_line_ends() -> None:
    table = "\n".join(f"Bank {row} | 1.234 | 5.678 | " + paragraph(10) for row in range(60))

    found = passages(join_pages([table]))

    assert all(passage.words <= MAX_WORDS for passage in found)
    assert sum(passage.words for passage in found) == 60 * 17  # each row: Bank, its number, 3 cells, 4 bars, 10
    assert found[0].text.startswith("Bank 0 | 1.234")


def test_a_line_longer_than_400_words_is_split_by_words() -> None:
    found = passages(join_pages([paragraph(900)]))

    assert [passage.words for passage in found] == [MAX_WORDS, MAX_WORDS, 100]


def test_a_short_tail_joins_the_passage_before_it_when_both_fit() -> None:
    text = join_pages(["\n\n".join([paragraph(MIN_WORDS), paragraph(40)])])

    (only,) = passages(text)

    assert only.words == MIN_WORDS + 40


def test_paragraphs_keep_their_breaks_inside_a_passage() -> None:
    (only,) = passages(join_pages(["Perbankan Syariah\n\n" + paragraph(10)]))

    assert only.text == "Perbankan Syariah\n\n" + paragraph(10)


def test_a_text_without_words_has_no_passages() -> None:
    assert passages(join_pages(["", "   "])) == ()


def test_a_report_is_published_with_its_citation_file_and_passages() -> None:
    record = report_record()
    text = join_pages([paragraph(300), paragraph(300)])

    found = reports([record], {record.text.file: text}, {record.files[0].sha256: "blobs/lpksi-2025.pdf"})

    (report,) = found.reports
    assert report.id == "ojk:lpksi:2025"
    assert report.citation == "Otoritas Jasa Keuangan, Laporan Perkembangan Keuangan Syariah Indonesia 2025"
    assert (report.storage_key, report.passages, report.pages) == ("blobs/lpksi-2025.pdf", 2, 244)
    assert [passage.address for passage in found.passages] == ["p-1", "p-2"]
    assert found.passages[1].report == "ojk:lpksi:2025"


def test_a_report_without_text_is_held_back() -> None:
    record = report_record()
    other = replace(record, report=replace(record.report, id="ojk:lpksi:2024", edition="2024"))

    found = reports([record, other], {record.text.file: join_pages([""])}, {})

    assert found.reports == ()
    assert found.held_back == ("ojk:lpksi:2024", "ojk:lpksi:2025")
