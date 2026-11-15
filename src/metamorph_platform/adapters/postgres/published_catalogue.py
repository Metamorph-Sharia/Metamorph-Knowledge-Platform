"""PostgreSQL behind the published catalogue (application/published_catalogue.py). Read-only, and only `published`.

Pages are keyset-paginated on (made_on, id), newest first, so a page stays right while documents are published
between two requests and no page scans past the ones before it. The cursor is that key, opaque to clients.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from metamorph_platform.application.published_catalogue import (
    CATALOGUE_FACETS,
    CatalogueEntry,
    CatalogueFacets,
    CatalogueFilters,
    CataloguePage,
    FacetCount,
    InvalidCursor,
)

# The day a regulation was made, for "newest first" (see the application module); never null, so keysets work.
MADE_ON = sql.SQL(
    "coalesce(promulgated_on, enacted_on, CASE WHEN year BETWEEN 1 AND 9999 THEN make_date(year, 1, 1) END, "
    "effective_on, date '0001-01-01')"
)
COLUMNS = sql.SQL("id, citation, title, kind, issuer, family, number, year, status, promulgated_on, effective_on")
SEARCHED = sql.SQL("concat_ws(' ', id, citation, title, array_to_string(aliases, ' '))")


class PostgresPublishedCatalogue:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def page(self, filters: CatalogueFilters, cursor: str | None, limit: int) -> CataloguePage:
        where, arguments = _where(filters)
        after = _decoded(cursor)
        keyset = sql.SQL("({made_on}, id) < (%(after_on)s, %(after_id)s)").format(made_on=MADE_ON) if after else None
        if after:
            arguments |= {"after_on": after[0], "after_id": after[1]}
        query = sql.SQL(
            "SELECT {columns}, {made_on} AS made_on FROM published.document {where} "
            "ORDER BY made_on DESC, id DESC LIMIT %(limit)s"
        ).format(columns=COLUMNS, made_on=MADE_ON, where=_joined([*where, keyset] if keyset else where))
        with self._connection.cursor(row_factory=dict_row) as rows:
            found = rows.execute(query, arguments | {"limit": limit + 1}).fetchall()
            total = rows.execute(
                sql.SQL("SELECT count(*) AS n FROM published.document {where}").format(where=_joined(where)), arguments
            ).fetchone()["n"]
        shown = found[:limit]
        last = shown[-1] if len(found) > limit else None
        return CataloguePage(
            entries=tuple(_entry(row) for row in shown),
            total=total,
            next_cursor=_encoded(last["made_on"], last["id"]) if last else None,
        )

    def facets(self, filters: CatalogueFilters) -> CatalogueFacets:
        counted: dict[str, tuple[FacetCount, ...]] = {}
        with self._connection.cursor(row_factory=dict_row) as rows:
            for facet in CATALOGUE_FACETS:
                where, arguments = _where(filters, without=facet)
                where.append(sql.SQL("{} IS NOT NULL").format(sql.Identifier(facet)))
                order = sql.SQL("value DESC") if facet == "year" else sql.SQL("count DESC, value")
                query = sql.SQL(
                    "SELECT {facet}::text AS value, count(*) AS count FROM published.document {where} "
                    "GROUP BY 1 ORDER BY {order}"
                ).format(facet=sql.Identifier(facet), where=_joined(where), order=order)
                counted[facet] = tuple(FacetCount(row["value"], row["count"]) for row in rows.execute(query, arguments))
            where, arguments = _where(filters)
            total = rows.execute(
                sql.SQL("SELECT count(*) AS n FROM published.document {where}").format(where=_joined(where)), arguments
            ).fetchone()["n"]
        return CatalogueFacets(
            total=total,
            issuers=counted["issuer"],
            families=counted["family"],
            years=counted["year"],
            statuses=counted["status"],
            kinds=counted["kind"],
        )


def _where(filters: CatalogueFilters, *, without: str = "") -> tuple[list[sql.Composable], dict[str, Any]]:
    """The conditions the filters set, leaving out the one named `without` (for that facet's own counts)."""
    conditions: list[sql.Composable] = []
    arguments: dict[str, Any] = {}
    exact = {"issuer": filters.issuer, "family": filters.family, "status": filters.status, "kind": filters.kind}
    for name, value in exact.items():
        if value and name != without:
            conditions.append(sql.SQL("{} = %({})s").format(sql.Identifier(name), sql.SQL(name)))
            arguments[name] = value
    if filters.year is not None and without != "year":
        conditions.append(sql.SQL("year = %(year)s"))
        arguments["year"] = filters.year
    for place, word in enumerate(filters.query.split()):
        name = f"word{place}"
        conditions.append(sql.SQL("{searched} ILIKE %({name})s").format(searched=SEARCHED, name=sql.SQL(name)))
        arguments[name] = f"%{_escaped(word)}%"
    return conditions, arguments


def _joined(conditions: list[sql.Composable]) -> sql.Composable:
    return sql.SQL("WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")


def _escaped(word: str) -> str:
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _entry(row: dict[str, Any]) -> CatalogueEntry:
    return CatalogueEntry(
        id=row["id"],
        citation=row["citation"],
        title=" ".join(row["title"].split()),
        kind=row["kind"],
        issuer=row["issuer"],
        family=row["family"],
        number=row["number"],
        year=row["year"],
        status=row["status"],
        promulgated_on=row["promulgated_on"],
        effective_on=row["effective_on"],
    )


def _encoded(made_on: date, document_id: str) -> str:
    return base64.urlsafe_b64encode(f"{made_on.isoformat()}|{document_id}".encode()).decode().rstrip("=")


def _decoded(cursor: str | None) -> tuple[date, str] | None:
    if not cursor:
        return None
    try:
        made_on, _, document_id = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode().partition("|")
        return date.fromisoformat(made_on), document_id
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidCursor("this cursor wasn't given by the catalogue; leave it out for the first page") from error
