"""PostgreSQL side of what the platform derives: parsed texts, citation links, link-derived validity.

Every write touches `registry.document.updated_at` of the documents it changes, so the next publish
picks them up.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

import psycopg

from metamorph_platform.application.ports import NewLink, OpenCitation, ParsedText, TextToParse
from metamorph_platform.domain.validity import SOURCE as LINKS
from metamorph_platform.domain.validity import DatedLink, ProvisionExpiry, StatusChange

PARSED_CITATION_CONFIDENCE = "medium"  # found by pattern in the text: reliable, not checked by a person
CHANGING_LINKS = ("revokes", "supersedes", "partly_revokes", "amends")

# The text whose structure is parsed: the Indonesian text of the document's main file, or one with no file.
MAIN_TEXT = """t.language = 'id'
  AND (t.of_file IS NULL OR EXISTS (
        SELECT 1 FROM registry.document_file f
        WHERE f.document_id = t.document_id AND f.sha256 = t.of_file AND f.role = 'main'))"""

# The content to parse is the text's effective one: a curator's active correction of it, or its own.
_TEXTS_TO_PARSE = f"""
SELECT t.id, t.document_id, d.issuer, d.family,
       coalesce(c.sha256, t.sha256), coalesce(c.storage_key, b.storage_key)
FROM registry.text_version t
JOIN registry.document d ON d.id = t.document_id
JOIN registry.blob b ON b.sha256 = t.sha256
LEFT JOIN curation.text_correction c ON c.document_id = t.document_id AND c.corrects_sha256 = t.sha256 AND c.active
WHERE t.is_current AND {MAIN_TEXT}
  AND (%(everything)s OR t.parsed_with IS DISTINCT FROM %(version)s
       OR t.parsed_sha256 IS DISTINCT FROM coalesce(c.sha256, t.sha256))
ORDER BY t.id
"""


def touch(connection: psycopg.Connection, document_ids: Iterable[str]) -> None:
    connection.execute(
        "UPDATE registry.document SET updated_at = now() WHERE id = ANY(%s)", (sorted(set(document_ids)),)
    )


def _clean(value: str | None) -> str | None:
    """PostgreSQL text can't hold NUL, which PDF extraction sometimes leaves behind."""
    return value.replace("\x00", "") if value else value


class PostgresParsedTexts:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def texts_to_parse(self, parser_version: str, everything: bool = False) -> list[TextToParse]:
        rows = self.connection.execute(_TEXTS_TO_PARSE, {"everything": everything, "version": parser_version})
        return [TextToParse(*row) for row in rows]

    def save(self, parsed: ParsedText) -> None:
        text = parsed.text
        with self.connection.transaction():
            self._replace_provisions(parsed)
            self._replace_citations(parsed)
            self.connection.execute(
                """
                UPDATE registry.text_version SET parsed_with = %s, parsed_sha256 = %s, structure_problems = %s,
                    stated_enacted_on = %s, stated_promulgated_on = %s, stated_effective_on = %s
                WHERE id = %s
                """,
                (
                    parsed.parser_version,
                    text.sha256,
                    json.dumps(parsed.structure.problems),
                    parsed.dates.enacted,
                    parsed.dates.promulgated,
                    parsed.dates.effective,
                    text.text_version_id,
                ),
            )
            touch(self.connection, [text.document_id])

    def _replace_provisions(self, parsed: ParsedText) -> None:
        """A provision the source sent for the same address wins; the parser's goes in beside the rest."""
        text = parsed.text
        self.connection.execute(
            "DELETE FROM registry.provision WHERE text_version_id = %s AND origin = 'parsed'", (text.text_version_id,)
        )
        with self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO registry.provision (text_version_id, address, document_id, parent_address, kind, label,
                    heading, ordinal, char_start, char_end, page_start, page_end, origin, parser_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'parsed', %s)
                ON CONFLICT (text_version_id, address) DO NOTHING
                """,
                [
                    (text.text_version_id, node.address, text.document_id, node.parent, node.kind, _clean(node.label),
                     _clean(node.heading), node.ordinal, node.char_start, node.char_end, node.page_start, node.page_end,
                     parsed.parser_version)
                    for node in parsed.structure.nodes
                ],
            )  # fmt: skip

    def _replace_citations(self, parsed: ParsedText) -> None:
        """This text's citations, and none left from the document's texts that are no longer current."""
        text = parsed.text
        self.connection.execute(
            """
            DELETE FROM registry.citation c USING registry.text_version t
            WHERE c.origin = 'parsed' AND c.text_version_id = t.id AND t.document_id = %s
              AND (t.id = %s OR NOT t.is_current)
            """,
            (text.document_id, text.text_version_id),
        )
        with self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO registry.citation (document_id, relation, target_text, target_id, from_address, to_address,
                    evidence, found_in, confidence, origin, text_version_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'text', %s, 'parsed', %s)
                """,
                [
                    (text.document_id, citation.relation.value, _clean(citation.target_text), citation.target_id,
                     citation.from_address, citation.to_address, _clean(citation.evidence),
                     PARSED_CITATION_CONFIDENCE, text.text_version_id)
                    for citation in parsed.citations
                ],
            )  # fmt: skip


class PostgresCitationLinks:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def open_citations(self) -> list[OpenCitation]:
        rows = self.connection.execute(
            """
            SELECT id, document_id, relation, target_text, target_id, from_address, to_address, confidence
            FROM registry.citation WHERE link_id IS NULL ORDER BY id
            """
        )
        return [OpenCitation(*row) for row in rows]

    def document_ids(self) -> set[str]:
        return {row[0] for row in self.connection.execute("SELECT id FROM registry.document")}

    def unambiguous_aliases(self) -> dict[str, str]:
        rows = self.connection.execute(
            """
            SELECT alias_key, min(document_id) FROM registry.alias
            GROUP BY alias_key HAVING count(DISTINCT document_id) = 1
            """
        )
        return dict(rows.fetchall())

    def link(self, citation_id: int, link: NewLink) -> None:
        with self.connection.transaction():
            (link_id,) = self.connection.execute(
                """
                INSERT INTO registry.link (type, from_document, from_address, to_document, to_address, method,
                    confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (type, from_document, coalesce(from_address, ''), to_document, coalesce(to_address, ''))
                DO UPDATE SET type = EXCLUDED.type
                RETURNING id
                """,
                (link.type, link.from_document, link.from_address, link.to_document, link.to_address, link.method,
                 link.confidence),
            ).fetchone()  # fmt: skip
            self.connection.execute("UPDATE registry.citation SET link_id = %s WHERE id = %s", (link_id, citation_id))
            touch(self.connection, [link.from_document])

    def drop_unsupported_links(self) -> int:
        with self.connection.transaction():
            dropped = self.connection.execute(
                """
                DELETE FROM registry.link l
                WHERE l.method <> 'curated' AND NOT EXISTS (SELECT 1 FROM registry.citation c WHERE c.link_id = l.id)
                RETURNING from_document, to_document
                """
            ).fetchall()
            touch(self.connection, [document for row in dropped for document in row])
        return len(dropped)


# When the document a link (alias l) comes from takes effect: a source's date, else the one its own text states.
TAKING_EFFECT = """
JOIN registry.document changing ON changing.id = l.from_document
LEFT JOIN LATERAL (
    SELECT min(stated_effective_on) AS effective, min(stated_promulgated_on) AS promulgated,
           min(stated_enacted_on) AS enacted
    FROM registry.text_version t WHERE t.document_id = changing.id AND t.is_current
) stated ON true
"""
TAKES_EFFECT = (
    "coalesce(changing.effective_on, changing.promulgated_on, changing.enacted_on, "
    "stated.effective, stated.promulgated, stated.enacted)"
)


class PostgresValidity:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def dated_links(self) -> list[DatedLink]:
        rows = self.connection.execute(
            f"""
            SELECT l.id, l.type, l.from_document, l.to_document, l.to_address, {TAKES_EFFECT}
            FROM registry.link l {TAKING_EFFECT}
            WHERE l.type = ANY(%s)
            ORDER BY l.id
            """,
            (list(CHANGING_LINKS),),
        )
        return [DatedLink(*row) for row in rows]

    def apply(self, changes: list[StatusChange], expiries: list[ProvisionExpiry]) -> int:
        with self.connection.transaction():
            changed = self._apply_status_changes(changes) | self._apply_expiries(expiries)
            touch(self.connection, changed)
        return len(changed)

    def _apply_status_changes(self, changes: list[StatusChange]) -> set[str]:
        existing = {
            (row[1], row[2], row[3], row[4], row[5]): row[0]
            for row in self.connection.execute(
                "SELECT id, document_id, address, status, effective_from, link_id FROM registry.status_event "
                "WHERE source = %s",
                (LINKS,),
            )
        }
        wanted = {(c.document_id, c.address, c.status, c.effective_from, c.link_id) for c in changes}
        gone = [existing[key] for key in existing.keys() - wanted]
        if gone:
            self.connection.execute("DELETE FROM registry.status_event WHERE id = ANY(%s)", (gone,))
        with self.connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO registry.status_event (document_id, address, status, effective_from, source, link_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [(document, address, status, day, LINKS, link_id) for document, address, status, day, link_id
                 in sorted(wanted - existing.keys(), key=str)],
            )  # fmt: skip
        return {key[0] for key in existing.keys() ^ wanted}

    def _apply_expiries(self, expiries: list[ProvisionExpiry]) -> set[str]:
        """Each provision's valid_to: the earliest expiry of its address or of an address above it."""
        by_document: dict[str, list[ProvisionExpiry]] = {}
        for expiry in expiries:
            by_document.setdefault(expiry.document_id, []).append(expiry)
        rows = self.connection.execute(
            "SELECT text_version_id, address, document_id, valid_to FROM registry.provision "
            "WHERE valid_to IS NOT NULL OR document_id = ANY(%s)",
            (list(by_document),),
        ).fetchall()
        stale = [
            (document, version, address, wanted)
            for version, address, document, current in rows
            if (wanted := _valid_to(address, by_document.get(document, []))) != current
        ]
        with self.connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE registry.provision SET valid_to = %s WHERE text_version_id = %s AND address = %s",
                [(wanted, version, address) for _, version, address, wanted in stale],
            )
        return {document for document, *_ in stale}


def _valid_to(address: str, expiries: list[ProvisionExpiry]) -> date | None:
    matching = [e.valid_to for e in expiries if address == e.address or address.startswith(e.address + "/")]
    return min(matching, default=None)
