"""The registry-build use cases against in-memory ports: parse texts, resolve citations, compute validity."""

from __future__ import annotations

from datetime import date

from fakes import MemoryBlobReader, MemoryCitationLinks, MemoryParsedTexts, MemoryReviewQueue, MemoryValidity

from metamorph_platform.application.compute_validity import ComputeValidity
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.ports import OpenCitation, TextToParse
from metamorph_platform.application.resolve_citations import ResolveCitations
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.structure import PARSER_VERSION
from metamorph_platform.domain.validity import DatedLink, ProvisionExpiry, StatusChange

GOOD = """\
Mengingat : Undang-Undang Nomor 21 Tahun 2011 tentang Otoritas Jasa Keuangan;
MEMUTUSKAN:
Pasal 1
Isi.
Pasal 2
Peraturan ini mulai berlaku pada tanggal diundangkan.
Ditetapkan di Jakarta
pada tanggal 26 Februari 2019
Diundangkan di Jakarta
pada tanggal 27 Februari 2019
"""
GAPPY = "Pasal 1\nSatu.\nPasal 3\nTiga.\n"


def text(text_version_id: int, document_id: str = "ojk:pojk:2019:10") -> TextToParse:
    return TextToParse(text_version_id, document_id, "ojk", "pojk", f"{text_version_id:064d}", f"key-{text_version_id}")


def parse_all(*contents: str):
    texts = [text(number) for number in range(1, len(contents) + 1)]
    store = MemoryParsedTexts(texts)
    reviews = MemoryReviewQueue()
    blobs = MemoryBlobReader({t.storage_key: content.encode() for t, content in zip(texts, contents, strict=True)})
    report = ParseTexts(store, blobs, reviews).run()
    return store, reviews, report


def test_each_text_is_parsed_once_into_provisions_citations_and_dates() -> None:
    store, reviews, report = parse_all(GOOD)

    [parsed] = store.saved
    assert parsed.parser_version == PARSER_VERSION
    assert [n.address for n in parsed.structure.nodes][:3] == ["mengingat", "memutuskan", "pasal-1"]
    assert [c.target_id for c in parsed.citations] == ["id:uu:2011:21"]
    assert parsed.dates.effective == date(2019, 2, 27)
    assert reviews.open == []
    assert report.counts() == {"texts": 1, "provisions": 5, "citations": 1, "suspect": 0}
    assert ParseTexts(store, MemoryBlobReader({}), reviews).run().texts == 0  # nothing left at this version


def test_a_text_whose_structure_looks_wrong_is_queued_for_review() -> None:
    _, reviews, report = parse_all(GAPPY)

    assert report.suspect == 1
    assert reviews.open == [
        (ReviewKind.STRUCTURE_SUSPECT, {"document_id": "ojk:pojk:2019:10", "text_sha256": text(1).sha256,
                                        "problems": ["Pasal 2 missing"]})
    ]  # fmt: skip


def citation(id_: int, target_id: str | None, target_text: str, relation: str = "legal_basis") -> OpenCitation:
    return OpenCitation(id_, "ojk:pojk:2019:10", relation, target_text, target_id, None, "pasal-5", "high")


def test_citations_to_held_documents_become_links_and_the_rest_wait_or_go_to_review() -> None:
    links = MemoryCitationLinks(
        open=[
            citation(1, "id:uu:2011:21", "UU 21/2011"),
            citation(2, None, "Peraturan Pemerintah Nomor 9 Tahun 2009"),  # not held yet: waits
            citation(3, None, "peraturan pelaksanaannya"),  # names nothing: a person decides
            citation(4, None, "UU OJK"),
        ],
        documents={"id:uu:2011:21", "ojk:pojk:2019:10"},
        aliases={"uu ojk": "id:uu:2011:21"},
    )
    reviews = MemoryReviewQueue()

    report = ResolveCitations(links, reviews).run()

    assert [(cid, link.to_document, link.method, link.to_address) for cid, link in links.linked] == [
        (1, "id:uu:2011:21", "exact_id", "pasal-5"),
        (4, "id:uu:2011:21", "alias", "pasal-5"),
    ]
    assert reviews.open == [
        (ReviewKind.UNRESOLVED_CITATION, {"document_id": "ojk:pojk:2019:10", "target_text": "peraturan pelaksanaannya"})
    ]
    assert report.counts() == {"linked": 2, "waiting": 1, "unidentified": 1, "links_dropped": 0}


def test_a_document_never_links_to_itself() -> None:
    links = MemoryCitationLinks(open=[citation(1, "ojk:pojk:2019:10", "itself")], documents={"ojk:pojk:2019:10"})

    ResolveCitations(links, MemoryReviewQueue()).run()

    assert links.linked == []


def test_validity_applies_what_the_dated_links_mean() -> None:
    day = date(2022, 3, 1)
    store = MemoryValidity([DatedLink(7, "amends", "ojk:pojk:2022:7", "ojk:pojk:2018:35", "pasal-115", day)])

    report = ComputeValidity(store).run()

    assert store.applied == (
        [StatusChange("ojk:pojk:2018:35", "pasal-115", "amended", day, 7)],
        [ProvisionExpiry("ojk:pojk:2018:35", "pasal-115", day)],
    )
    assert report.counts() == {"status_changes": 1, "expiries": 1, "documents_changed": 1}
