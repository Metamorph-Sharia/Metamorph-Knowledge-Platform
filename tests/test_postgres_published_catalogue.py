"""The published catalogue in PostgreSQL: newest first, complete pages, faceted counts, and only what is published."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.published_catalogue import PostgresPublishedCatalogue
from metamorph_platform.application.published_catalogue import CatalogueFilters, InvalidCursor

pytestmark = pytest.mark.database

# id, issuer, family, number, year, citation, title, status, promulgated_on, effective_on, aliases
DOCUMENTS = [
    (
        "ojk:pojk:2020:47",
        "ojk",
        "pojk",
        "47",
        2020,
        "POJK 47/POJK.05/2020",
        "PERIZINAN USAHA PERUSAHAAN PEMBIAYAAN",
        "in_force",
        date(2020, 11, 25),
        date(2020, 11, 26),
        ["POJK 47/2020"],
    ),
    (
        "ojk:pojk:2026:11",
        "ojk",
        "pojk",
        "11",
        2026,
        "POJK 11 Tahun 2026",
        "PENYELENGGARAAN USAHA PEMBIAYAAN SYARIAH",
        "in_force",
        date(2026, 6, 1),
        date(2027, 1, 1),
        [],
    ),
    (
        "ojk:seojk:2025:23",
        "ojk",
        "seojk",
        "23",
        2025,
        "SEOJK 23/SEOJK.06/2025",
        "LAPORAN BULANAN",
        "not_yet_in_force",
        None,
        date(2027, 4, 1),
        [],
    ),  # no promulgation date: dated by its year, not by 2027
    (
        "bi:padg:2026:31",
        "bi",
        "padg",
        "31",
        2026,
        "PADG No. 31 Tahun 2026",
        "KEBIJAKAN MAKROPRUDENSIAL",
        "in_force",
        date(2026, 12, 31),
        date(2026, 12, 31),
        [],
    ),
    (
        "dsn-mui:fatwa:2000:4",
        "dsn-mui",
        "fatwa",
        "4",
        2000,
        "Fatwa DSN-MUI 04/DSN-MUI/IV/2000",
        "MURABAHAH",
        "in_force",
        None,
        None,
        [],
    ),
    ("ojk:undated:0:1", "ojk", "pojk", "1", None, "POJK tanpa tahun", "TANPA TANGGAL", "revoked", None, None, []),
]


@pytest.fixture
def catalogue(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        for row in DOCUMENTS:
            connection.execute(
                "INSERT INTO published.document (id, issuer, family, number, year, citation, title, status, "
                "promulgated_on, effective_on, aliases, language, kind, id_confidence) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'id', 'regulation', 'exact')",
                row,
            )
        yield PostgresPublishedCatalogue(connection)


def ids(page):
    return [entry.id for entry in page.entries]


def test_newest_first_by_the_day_made_with_the_undated_last(catalogue):
    page = catalogue.page(CatalogueFilters(), None, 25)
    assert ids(page) == [
        "bi:padg:2026:31",
        "ojk:pojk:2026:11",
        "ojk:seojk:2025:23",
        "ojk:pojk:2020:47",
        "dsn-mui:fatwa:2000:4",
        "ojk:undated:0:1",
    ]
    assert page.total == 6 and page.next_cursor is None


def test_pages_follow_each_other_without_a_gap_or_a_repeat(catalogue):
    seen, cursor = [], None
    while True:
        page = catalogue.page(CatalogueFilters(), cursor, 2)
        seen += ids(page)
        assert page.total == 6
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == ids(catalogue.page(CatalogueFilters(), None, 25))


def test_filters_narrow_and_words_match_citation_title_or_alias(catalogue):
    assert ids(catalogue.page(CatalogueFilters(issuer="bi"), None, 25)) == ["bi:padg:2026:31"]
    narrowed = CatalogueFilters(issuer="ojk", family="pojk", year=2026)
    assert ids(catalogue.page(narrowed, None, 25)) == ["ojk:pojk:2026:11"]
    assert ids(catalogue.page(CatalogueFilters(query="pojk 47/2020"), None, 25)) == ["ojk:pojk:2020:47"]
    assert ids(catalogue.page(CatalogueFilters(query="syariah pembiayaan"), None, 25)) == ["ojk:pojk:2026:11"]
    assert ids(catalogue.page(CatalogueFilters(query="100%_"), None, 25)) == []


def test_an_entry_keeps_both_days_apart(catalogue):
    entry = next(e for e in catalogue.page(CatalogueFilters(issuer="ojk", family="seojk"), None, 25).entries)
    assert entry.year == 2025 and entry.promulgated_on is None and entry.effective_on == date(2027, 4, 1)


def test_each_facet_counts_with_every_filter_but_its_own(catalogue):
    facets = catalogue.facets(CatalogueFilters(issuer="ojk"))
    assert facets.total == 4
    assert {f.value: f.count for f in facets.issuers} == {"ojk": 4, "bi": 1, "dsn-mui": 1}
    assert {f.value: f.count for f in facets.families} == {"pojk": 3, "seojk": 1}
    assert [f.value for f in facets.years] == ["2026", "2025", "2020"]
    assert {f.value: f.count for f in facets.statuses} == {"in_force": 2, "not_yet_in_force": 1, "revoked": 1}


def test_only_what_is_published_is_listed(catalogue, database_url):
    with psycopg.connect(database_url) as connection:
        held = connection.execute("SELECT count(*) FROM registry.document").fetchone()[0]
    assert held == 0  # the registry may hold anything; the catalogue never reads it
    assert catalogue.page(CatalogueFilters(), None, 25).total == len(DOCUMENTS)


def test_a_cursor_the_catalogue_didnt_give_is_refused(catalogue):
    with pytest.raises(InvalidCursor):
        catalogue.page(CatalogueFilters(), "not-a-cursor!", 25)
