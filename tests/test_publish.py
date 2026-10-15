"""Publish against in-memory ports, and the publishing rules it applies."""

from __future__ import annotations

from datetime import date

import pytest
from fakes import MemoryBlobReader, MemoryPublication

from metamorph_platform.application.publish import Publish
from metamorph_platform.domain.publishing import (
    DocumentSnapshot,
    LinkRecord,
    Override,
    ProvisionRecord,
    SourceRecord,
    StatusEventRecord,
    StoredContent,
    effective_values,
    publication_of,
)

SOURCE = SourceRecord("ojk", "regalert:a", "https://regalert.today/document/a", "2026-10-13T02:34:23+00:00")


def snapshot(**changes) -> DocumentSnapshot:
    values = {"id": "ojk:pojk:2014:5", "title": "PERIZINAN USAHA", "status": "in_force"}
    base = dict(
        id="ojk:pojk:2014:5",
        values=values,
        aliases=("POJK 5/2014",),
        sources=(SOURCE,),
        files=(),
        texts=(StoredContent("a" * 64, "public", "blobs/aa/" + "a" * 64, {"language": "id"}),),
    )
    return DocumentSnapshot(**{**base, **changes})


def test_overrides_win_and_mark_the_document_curated() -> None:
    values, curated = effective_values({"title": "A", "status": "in_force"}, (Override("title", "B"),))

    assert values == {"title": "B", "status": "in_force"} and curated


def test_an_override_equal_to_the_source_value_is_not_curation() -> None:
    assert effective_values({"title": "A"}, (Override("title", "A"),)) == ({"title": "A"}, False)


def test_only_known_fields_can_be_overridden() -> None:
    with pytest.raises(ValueError, match="can't be overridden"):
        effective_values({"title": "A"}, (Override("id", "ojk:pojk:2099:1"),))


def test_suppressed_or_sourceless_documents_are_not_published() -> None:
    assert publication_of(snapshot(suppressed=True)) is None
    assert publication_of(snapshot(sources=())) is None


def test_a_document_its_source_stopped_listing_is_still_published() -> None:
    gone_from_listing = SourceRecord(**{**SOURCE.__dict__, "missing_since": "2026-10-14T00:00:00+00:00"})

    assert publication_of(snapshot(sources=(gone_from_listing,))) is not None


def test_restricted_content_never_reaches_published() -> None:
    restricted = StoredContent("b" * 64, "restricted", "blobs/bb/" + "b" * 64)

    publication = publication_of(snapshot(texts=(restricted, *snapshot().texts)))

    assert [t.rights for t in publication.texts] == ["public"]


def test_publish_adds_updates_and_removes() -> None:
    publication = MemoryPublication({"ojk:pojk:2014:5": snapshot()})
    publish = Publish(publication, publication, MemoryBlobReader({}))

    assert publish.run().counts() == {"added": 1, "updated": 0, "removed": 0}
    assert publish.run().counts() == {"added": 0, "updated": 1, "removed": 0}

    publication.snapshots["ojk:pojk:2014:5"] = snapshot(suppressed=True)
    assert publish.run().counts() == {"added": 0, "updated": 0, "removed": 1}
    assert publication.published == {}


TEXT_SHA = "a" * 64
TEXT = "BAB I\nUMUM\nPasal 1\n(1) Satu.\n(2) Dua.\n"


def provision(address, kind, start, end, parent=None):
    return ProvisionRecord(TEXT_SHA, address, kind, address, 0, start, end, parent_address=parent)


def test_provisions_are_published_with_their_text_but_containers_without() -> None:
    provisions = (
        provision("bab-i", "bab", 0, len(TEXT)),
        provision("pasal-1", "pasal", 11, len(TEXT), "bab-i"),
        provision("pasal-1/ayat-1", "ayat", 19, 29, "pasal-1"),
    )

    publication = publication_of(snapshot(provisions=provisions), {TEXT_SHA: TEXT})

    bodies = {p.record.address: p.body for p in publication.provisions}
    assert bodies == {"bab-i": "", "pasal-1": "Pasal 1\n(1) Satu.\n(2) Dua.\n", "pasal-1/ayat-1": "(1) Satu.\n"}


def test_provisions_of_a_text_that_is_not_published_are_not_either() -> None:
    restricted = StoredContent("b" * 64, "restricted", "blobs/bb/" + "b" * 64)
    hidden = ProvisionRecord("b" * 64, "pasal-1", "pasal", "Pasal 1", 0, 0, 5)

    publication = publication_of(snapshot(texts=(restricted,), provisions=(hidden,)), {"b" * 64: "Pasal"})

    assert publication.provisions == ()


def test_dates_a_text_states_fill_only_what_the_sources_left_empty() -> None:
    stated = {"enacted_on": date(2019, 2, 26), "effective_on": date(2019, 2, 27)}
    values = {**snapshot().values, "enacted_on": date(2019, 2, 25), "effective_on": None}

    publication = publication_of(snapshot(values=values, stated_dates=stated))

    assert (publication.values["enacted_on"], publication.values["effective_on"]) == (
        date(2019, 2, 25),
        date(2019, 2, 27),
    )


def test_an_unknown_status_takes_the_latest_one_links_give_the_whole_document() -> None:
    events = (
        StatusEventRecord(None, "amended", date(2020, 1, 1), "links"),
        StatusEventRecord("pasal-5", "revoked", date(2023, 1, 1), "links"),
        StatusEventRecord(None, "revoked", date(2022, 1, 1), "links"),
    )
    unknown = {**snapshot().values, "status": "unknown"}

    assert publication_of(snapshot(values=unknown, status_events=events)).values["status"] == "revoked"
    assert publication_of(snapshot(status_events=events)).values["status"] == "in_force"  # a source's status stands


def test_links_and_status_events_are_published_as_they_are() -> None:
    link = LinkRecord("legal_basis", None, "id:uu:2011:21", None, None, "high")
    event = StatusEventRecord(None, "amended", None, "links")

    publication = publication_of(snapshot(links=(link,), status_events=(event,)))

    assert (publication.links, publication.status_events) == ((link,), (event,))


def test_publish_reads_each_text_its_provisions_point_into_once() -> None:
    provisions = (provision("pasal-1", "pasal", 11, len(TEXT)), provision("pasal-1/ayat-1", "ayat", 19, 29, "pasal-1"))
    publication = MemoryPublication({"ojk:pojk:2014:5": snapshot(provisions=provisions)})
    texts = MemoryBlobReader({"blobs/aa/" + TEXT_SHA: TEXT.encode()})

    Publish(publication, publication, texts).run()

    assert texts.reads == ["blobs/aa/" + TEXT_SHA]
    assert [p.body for p in publication.published["ojk:pojk:2014:5"].provisions][1] == "(1) Satu.\n"
