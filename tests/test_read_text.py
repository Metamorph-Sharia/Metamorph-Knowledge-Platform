"""Reading a document's text as the parser cut it, a part at a time (application/reading.py), with fakes."""

from __future__ import annotations

from datetime import date

from fakes import MemoryBlobReader

from metamorph_platform.application.reading import ReadText
from metamorph_platform.application.views import (
    PassageReference,
    ProvisionChange,
    ReadableText,
    ReadingPassage,
    ReadingSource,
    SourceProvision,
)

DOC = "ojk:pojk:2018:35"
TEXT = "PERATURAN\nPasal 1\nSatu 😀.\nPasal 2\n(1) Dua.\n(2) Tiga 😀 menurut ayat (1).\n"
CHANGE = ProvisionChange("amends", "ojk:pojk:2022:7", "POJK 7/2022", date(2022, 2, 27), "pasal-i/pasal-2")


def provision(address, parent, kind, label, start_text, end_text=None, changes=()) -> SourceProvision:
    start = TEXT.index(start_text)
    end = TEXT.index(end_text) if end_text else len(TEXT)
    return SourceProvision(address, parent, kind, label, None, start, end, 1, 1, None, changes)


class Texts:
    def __init__(self, provisions) -> None:
        self.provisions = provisions
        self.asked: list[tuple[str, str | None]] = []

    def reading_source(self, document_id: str, sha256: str | None) -> ReadingSource | None:
        self.asked.append((document_id, sha256))
        if document_id != DOC:
            return None
        texts = (ReadableText("a" * 64, "id", "self extracted, text layer", main=True),)
        return ReadingSource(DOC, "POJK 35/2018", "Penjaminan", "a" * 64, "blobs/aa/text", ("Pasal 3 missing",),
                             corrected=False, editable=True, pdf_sha256="f" * 64, texts=texts,
                             provisions=tuple(self.provisions))  # fmt: skip


PROVISIONS = [
    provision("pasal-1", None, "pasal", "Pasal 1", "Pasal 1", "Pasal 2"),
    provision("pasal-2", None, "pasal", "Pasal 2", "Pasal 2", changes=(CHANGE,)),
    provision("pasal-2/ayat-1", "pasal-2", "ayat", "(1)", "(1)", "(2)"),
    provision("pasal-2/ayat-2", "pasal-2", "ayat", "(2)", "(2)"),
]


def read_text(provisions=PROVISIONS, budget=None) -> tuple[ReadText, Texts]:
    texts = Texts(provisions)
    reader = ReadText(texts, MemoryBlobReader({"blobs/aa/text": TEXT.encode()}))
    if budget:
        reader.budget = budget
    return reader, texts


def test_a_text_is_read_whole_when_it_is_short_with_its_outline_and_what_changed_each_article() -> None:
    reader, texts = read_text()

    reading = reader.read(DOC)

    assert texts.asked == [(DOC, None)]  # the document's main text, unless another is asked for
    assert (reading.part, reading.parts) == (0, 1)
    assert reading.passages == (
        ReadingPassage(None, "PERATURAN\n", opens=False, titled=False),
        ReadingPassage("pasal-1", "Satu 😀.\n", opens=True, titled=True),
        ReadingPassage("pasal-2", "", opens=True, titled=True),
        ReadingPassage("pasal-2/ayat-1", "(1) Dua.\n", opens=True, titled=False),
        ReadingPassage(
            "pasal-2/ayat-2",
            "(2) Tiga 😀 menurut ayat (1).\n",
            opens=True,
            titled=False,
            references=(PassageReference(20, 28, "pasal-2/ayat-1"),),  # 😀 counts twice
        ),
    )
    assert [(p.address, p.depth, p.part) for p in reading.provisions] == [
        ("pasal-1", 0, 0),
        ("pasal-2", 0, 0),
        ("pasal-2/ayat-1", 1, 0),
        ("pasal-2/ayat-2", 1, 0),
    ]
    assert reading.provisions[1].changes == (CHANGE,)
    assert (reading.citation, reading.problems, reading.pdf_sha256) == ("POJK 35/2018", ("Pasal 3 missing",), "f" * 64)


def test_each_provision_says_where_an_editor_finds_it_counting_as_the_editor_does() -> None:
    reader, _ = read_text()

    second = reader.read(DOC).provisions[1]

    assert (second.edit_from, second.edit_to) == (TEXT.index("Pasal 2") + 1, len(TEXT) + 2)  # each 😀 counts twice


def test_a_long_text_is_read_a_part_at_a_time_and_an_address_finds_its_part() -> None:
    reader, _ = read_text(budget=14)

    first, last = reader.read(DOC), reader.read(DOC, at="pasal-2/ayat-2")

    assert first.parts == last.parts > 1
    assert first.part == 0 and first.passages[0].text == "PERATURAN\n"
    assert last.part == last.parts - 1
    assert last.passages[-1].address == "pasal-2/ayat-2" and last.passages[-1].opens
    assert {p.address: p.part for p in last.provisions}["pasal-2/ayat-2"] == last.part


def test_a_part_beyond_the_last_reads_the_last() -> None:
    reader, _ = read_text(budget=12)

    reading = reader.read(DOC, part=99)

    assert reading.part == reading.parts - 1


def test_a_document_or_text_without_provisions_to_read_is_not_found() -> None:
    reader, _ = read_text()

    assert reader.read("ojk:pojk:1999:1") is None
