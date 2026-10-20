"""The curation pages' queries against PostgreSQL, on a built registry: lineage, reading, search and browsing."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest
from amendment_world import AMENDING, TARGET, build, load
from fakes import MemoryBlobStore

from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.views import PostgresCurationViews
from metamorph_platform.application.views import ProvisionChange, SearchFilters

pytestmark = pytest.mark.database


@pytest.fixture
def views(database_url, tmp_path):
    blobs = MemoryBlobStore()
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        load(connection, blobs, tmp_path)
        build(connection, blobs)
        yield PostgresCurationViews(connection)


def test_a_link_names_the_other_document_and_the_day_the_change_took_effect(views) -> None:
    target = views.document(TARGET)

    assert {(link.type, link.document_id, link.document_citation, link.to_address, link.effective_on)
            for link in target.links_in} == {
        ("amends", AMENDING, "POJK 7/2022", None, date(2022, 2, 27)),
        ("amends", AMENDING, "POJK 7/2022", "pasal-115", date(2022, 2, 27)),
        ("partly_revokes", AMENDING, "POJK 7/2022", "pasal-110", date(2022, 2, 27)),
    }  # fmt: skip
    assert {link.document_citation for link in views.document(AMENDING).links_out} >= {"POJK 35/2018"}


def test_a_status_derived_from_links_names_the_document_that_caused_it(views) -> None:
    caused = {(row.address, row.status, row.caused_by, row.caused_by_citation)
              for row in views.document(TARGET).status_history if row.source == "links"}  # fmt: skip

    assert caused == {
        (None, "amended", AMENDING, "POJK 7/2022"),
        ("pasal-110", "revoked", AMENDING, "POJK 7/2022"),
        ("pasal-115", "amended", AMENDING, "POJK 7/2022"),
    }


def test_a_text_to_read_comes_with_its_provisions_and_what_changed_each_one(views) -> None:
    source = views.reading_source(TARGET, None)

    assert (source.document_id, source.citation, source.corrected, source.editable) == (
        TARGET,
        "POJK 35/2018",
        False,
        True,
    )
    assert source.storage_key.startswith("blobs/") and [t.sha256 for t in source.texts] == [source.sha256]
    assert [(p.address, p.label) for p in source.provisions] == [
        ("pasal-110", "Pasal 110"),
        ("pasal-115", "Pasal 115"),
        ("pasal-115/ayat-1", "(1)"),
        ("pasal-115/ayat-2", "(2)"),
    ]
    changes = {p.address: p.changes for p in source.provisions}
    assert changes["pasal-115"] == (
        ProvisionChange("amends", AMENDING, "POJK 7/2022", date(2022, 2, 27), "pasal-i/pasal-115"),
    )
    assert changes["pasal-110"] == (
        ProvisionChange("partly_revokes", AMENDING, "POJK 7/2022", date(2022, 2, 27), None),
    )
    assert changes["pasal-115/ayat-1"] == ()


def test_only_a_current_text_of_the_document_with_provisions_can_be_read(views) -> None:
    sha = views.reading_source(TARGET, None).sha256

    assert views.reading_source(TARGET, sha).sha256 == sha
    assert views.reading_source(AMENDING, sha) is None
    assert views.reading_source(TARGET, "0" * 64) is None
    assert views.reading_source("ojk:pojk:1999:1", None) is None


def test_search_finds_the_articles_whose_wording_matches_with_an_excerpt(views) -> None:
    found = views.search("wajib melapor", SearchFilters(), kind="articles", page=1)

    assert {(hit.document_id, hit.address) for hit in found.articles} == {
        (TARGET, "pasal-115"),
        (AMENDING, "pasal-i/pasal-115"),  # the quoted article, not the amending Pasal I that holds it
    }
    assert all("«wajib» «melapor»" in hit.excerpt for hit in found.articles)
    assert (found.articles_total, found.documents_total) == (2, 2)


def test_search_finds_documents_by_their_metadata_or_their_wording(views) -> None:
    by_citation = views.search("35/2018", SearchFilters(), kind="documents", page=1)
    by_wording = views.search("setiap bulan", SearchFilters(), kind="documents", page=1)

    assert [hit.id for hit in by_citation.documents] == [TARGET]
    assert [(hit.id, hit.state, hit.family, hit.year) for hit in by_wording.documents] == [
        (AMENDING, "published", "pojk", 2022)
    ]


def test_search_filters_and_counts_each_facet_without_its_own_filter(views) -> None:
    found = views.search("wajib melapor", SearchFilters(year=2022), kind="articles", page=1)

    assert [hit.document_id for hit in found.articles] == [AMENDING]
    assert dict(facet_values(found, "year")) == {"2022": 1, "2018": 1}
    assert dict(facet_values(found, "issuer")) == {"ojk": 1}
    assert dict(facet_values(found, "state")) == {"published": 1}


def test_without_a_query_search_lists_documents_by_their_filters_newest_first(views) -> None:
    found = views.search("", SearchFilters(family="pojk"), kind="documents", page=1)

    assert [hit.id for hit in found.documents] == [AMENDING, TARGET]
    assert (found.articles, found.articles_total) == ((), 0)


def test_a_series_lists_its_years_and_each_years_documents_by_number(views) -> None:
    assert [(s.issuer, s.family, s.documents, s.first_year, s.last_year) for s in views.series()] == [
        ("ojk", "pojk", 2, 2018, 2022)
    ]
    latest = views.series_page("ojk", "pojk", None)
    assert (latest.years, latest.year, [d.id for d in latest.documents]) == (((2022, 1), (2018, 1)), 2022, [AMENDING])
    assert [d.number for d in views.series_page("ojk", "pojk", 2018).documents] == ["35"]
    assert views.series_page("ojk", "nothing", None) is None


def facet_values(found, name: str):
    return next(facet.values for facet in found.facets if facet.name == name)
