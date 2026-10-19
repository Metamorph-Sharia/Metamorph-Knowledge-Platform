"""PostgreSQL side of curation: the team's actions (audited), and the loader's view of corrections.

Every action runs in one transaction: the change, its audit_log row (with the state before it), and a
touch of the documents it affects so the next publish picks them up.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from metamorph_platform.adapters.postgres.derived import MAIN_TEXT, touch
from metamorph_platform.application.ports import CorrectableText, CurationRefused, Curator
from metamorph_platform.domain.curation import ActiveOverride, id_parts
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.publishing import OVERRIDABLE_FIELDS

# A current main text of the document, with its effective content: a curator's active correction, or its own.
_CURRENT_MAIN_TEXT = f"""
SELECT coalesce(c.sha256, t.sha256) AS effective_sha256, coalesce(c.storage_key, b.storage_key) AS storage_key,
       t.paged, t.parsed_sha256, coalesce(t.structure_problems, '[]'::jsonb) AS problems
FROM registry.text_version t JOIN registry.blob b ON b.sha256 = t.sha256
LEFT JOIN curation.text_correction c ON c.document_id = t.document_id AND c.corrects_sha256 = t.sha256 AND c.active
WHERE t.document_id = %s AND t.sha256 = %s AND t.is_current AND {MAIN_TEXT}
"""


def _json(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


class PostgresCurationActions:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # --- corrections ---------------------------------------------------------------------------

    def correct(self, curator: Curator, document_id: str, field: str, value: Any, reason: str) -> None:
        column = _overridable(field)
        with self.connection.transaction():
            self._begin(curator)
            (source_value,) = self._one(
                sql.SQL("SELECT {} FROM registry.document WHERE id = %s").format(column),
                document_id,
                missing=f"no document {document_id}",
            )
            before = self._withdraw(document_id, field)
            self.connection.execute(
                "INSERT INTO curation.override (document_id, field, value, source_value, reason, author) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (document_id, field, Jsonb(value), Jsonb(_json(source_value)), reason, curator.username),
            )
            self._audit(
                curator, "correct", {"document_id": document_id, "field": field}, before, {"value": value}, reason
            )
            touch(self.connection, [document_id])

    def withdraw_correction(self, curator: Curator, document_id: str, field: str, reason: str) -> None:
        with self.connection.transaction():
            self._begin(curator)
            before = self._withdraw(document_id, field)
            if before is None:
                raise CurationRefused(f"{field} of {document_id} has no correction to withdraw")
            self._audit(
                curator, "withdraw_correction", {"document_id": document_id, "field": field}, before, None, reason
            )
            touch(self.connection, [document_id])

    def _withdraw(self, document_id: str, field: str) -> dict | None:
        row = self.connection.execute(
            "UPDATE curation.override SET active = false WHERE document_id = %s AND field = %s AND active "
            "RETURNING value, author, reason",
            (document_id, field),
        ).fetchone()
        return {"value": row[0], "author": row[1], "reason": row[2]} if row else None

    # --- approvals -----------------------------------------------------------------------------

    def approve(self, curator: Curator, document_id: str, text_sha256: str, reason: str) -> None:
        """The problems approved are the ones stored for the text now, read in this transaction: the ones the
        curator was shown. They belong to its effective content (a correction's, once parsed), which is what
        the approval names; any other problems, after a re-parse, lapse it (domain/gate.py)."""
        target = {"document_id": document_id, "text_sha256": text_sha256}
        with self.connection.transaction():
            self._begin(curator)
            effective_sha256, _, _, parsed_sha256, problems = self._current_main_text(document_id, text_sha256)
            if parsed_sha256 != effective_sha256:
                raise CurationRefused(f"{text_sha256[:12]} isn't parsed since it changed: approve it once it is")
            if not problems:
                raise CurationRefused(f"{text_sha256[:12]} has no structure problems to approve")
            before = self._withdraw_approval(document_id, effective_sha256)
            self.connection.execute(
                "INSERT INTO curation.approval (document_id, text_sha256, problems, reason, author) "
                "VALUES (%s, %s, %s, %s, %s)",
                (document_id, effective_sha256, Jsonb(problems), reason, curator.username),
            )
            self._audit(curator, "approve", target, before, {"problems": problems}, reason)
            touch(self.connection, [document_id])

    def withdraw_approval(self, curator: Curator, document_id: str, text_sha256: str, reason: str) -> None:
        target = {"document_id": document_id, "text_sha256": text_sha256}
        with self.connection.transaction():
            self._begin(curator)
            effective_sha256, *_ = self._current_main_text(document_id, text_sha256)
            before = self._withdraw_approval(document_id, effective_sha256)
            if before is None:
                raise CurationRefused(f"{text_sha256[:12]} of {document_id} has no approval to withdraw")
            self._audit(curator, "withdraw_approval", target, before, None, reason)
            touch(self.connection, [document_id])

    def _withdraw_approval(self, document_id: str, text_sha256: str) -> dict | None:
        row = self.connection.execute(
            "UPDATE curation.approval SET active = false WHERE document_id = %s AND text_sha256 = %s AND active "
            "RETURNING problems, author, reason",
            (document_id, text_sha256),
        ).fetchone()
        return {"problems": row[0], "author": row[1], "reason": row[2]} if row else None

    # --- text corrections ------------------------------------------------------------------------

    def effective(self, document_id: str, text_sha256: str) -> CorrectableText | None:
        row = self.connection.execute(_CURRENT_MAIN_TEXT, (document_id, text_sha256)).fetchone()
        return CorrectableText(storage_key=row[1], paged=row[2]) if row else None

    def correct_text(
        self, curator: Curator, document_id: str, text_sha256: str, sha256: str, storage_key: str, reason: str
    ) -> None:
        target = {"document_id": document_id, "text_sha256": text_sha256}
        with self.connection.transaction():
            self._begin(curator)
            self._current_main_text(document_id, text_sha256)
            before = self._withdraw_text_correction(document_id, text_sha256)
            self.connection.execute(
                "INSERT INTO curation.text_correction (document_id, corrects_sha256, sha256, storage_key, reason, "
                "author) VALUES (%s, %s, %s, %s, %s, %s)",
                (document_id, text_sha256, sha256, storage_key, reason, curator.username),
            )
            self._audit(curator, "correct_text", target, before, {"sha256": sha256}, reason)
            touch(self.connection, [document_id])

    def withdraw_text_correction(self, curator: Curator, document_id: str, text_sha256: str, reason: str) -> None:
        target = {"document_id": document_id, "text_sha256": text_sha256}
        with self.connection.transaction():
            self._begin(curator)
            before = self._withdraw_text_correction(document_id, text_sha256)
            if before is None:
                raise CurationRefused(f"{text_sha256[:12]} of {document_id} has no correction to withdraw")
            self._audit(curator, "withdraw_text_correction", target, before, None, reason)
            touch(self.connection, [document_id])

    def _current_main_text(self, document_id: str, text_sha256: str) -> tuple:
        return self._one(
            _CURRENT_MAIN_TEXT,
            document_id,
            text_sha256,
            missing=f"{text_sha256[:12]} isn't a current main text of {document_id}",
        )

    def _withdraw_text_correction(self, document_id: str, text_sha256: str) -> dict | None:
        row = self.connection.execute(
            "UPDATE curation.text_correction SET active = false "
            "WHERE document_id = %s AND corrects_sha256 = %s AND active RETURNING sha256, author, reason",
            (document_id, text_sha256),
        ).fetchone()
        return {"sha256": row[0], "author": row[1], "reason": row[2]} if row else None

    # --- suppression ---------------------------------------------------------------------------

    def suppress(self, curator: Curator, document_id: str, reason: str) -> None:
        with self.connection.transaction():
            self._begin(curator)
            self._require_document(document_id)
            added = self.connection.execute(
                "INSERT INTO curation.suppression (document_id, reason, author) VALUES (%s, %s, %s) "
                "ON CONFLICT (document_id) DO NOTHING RETURNING document_id",
                (document_id, reason, curator.username),
            ).fetchone()
            if added is None:
                raise CurationRefused(f"{document_id} is suppressed already")
            self._audit(
                curator, "suppress", {"document_id": document_id}, {"suppressed": False}, {"suppressed": True}, reason
            )
            touch(self.connection, [document_id])

    def restore(self, curator: Curator, document_id: str, reason: str) -> None:
        with self.connection.transaction():
            self._begin(curator)
            removed = self.connection.execute(
                "DELETE FROM curation.suppression WHERE document_id = %s RETURNING reason, author", (document_id,)
            ).fetchone()
            if removed is None:
                raise CurationRefused(f"{document_id} isn't suppressed")
            self._audit(
                curator,
                "restore",
                {"document_id": document_id},
                {"suppressed": True, "reason": removed[0], "author": removed[1]},
                {"suppressed": False},
                reason,
            )
            touch(self.connection, [document_id])

    # --- review items, IDs, citations, conflicts -------------------------------------------------

    def decide_review(self, curator: Curator, item_id: int, state: str, note: str) -> None:
        with self.connection.transaction():
            self._begin(curator)
            decided = self.connection.execute(
                "UPDATE curation.review_item SET state = %s, decided_by = %s, decided_at = now(), note = %s "
                "WHERE id = %s AND state = 'open' RETURNING kind, subject",
                (state, curator.username, note, item_id),
            ).fetchone()
            if decided is None:
                raise CurationRefused(f"review item {item_id} isn't open (decided already, or no such item)")
            self._audit(
                curator,
                "decide_review",
                {"review_item_id": item_id},
                {"state": "open", "kind": decided[0], "subject": decided[1]},
                {"state": state},
                note,
            )

    def assign_id(self, curator: Curator, document_id: str, new_id: str, reason: str) -> None:
        issuer, family, year, number = id_parts(new_id)
        with self.connection.transaction():
            self._begin(curator)
            before = self._require_document(document_id)
            if self.connection.execute("SELECT 1 FROM registry.document WHERE id = %s", (new_id,)).fetchone():
                raise CurationRefused(
                    f"{new_id} is another document already; if this one duplicates it, suppress this one instead"
                )
            self.connection.execute(
                "UPDATE registry.document SET id = %s, issuer = %s, family = %s, number = %s, "
                "year = coalesce(%s, year), id_confidence = 'high', updated_at = now() WHERE id = %s",
                (new_id, issuer, family, number, year, document_id),
            )  # every row about the document follows (ON UPDATE CASCADE)
            self.connection.execute(
                "INSERT INTO curation.id_assignment (connector, source_id, document_id, author) "
                "SELECT connector, source_id, %s, %s FROM registry.document_source WHERE document_id = %s "
                "ON CONFLICT (connector, source_id) DO UPDATE SET document_id = EXCLUDED.document_id, "
                "author = EXCLUDED.author, created_at = now()",
                (new_id, curator.username, new_id),
            )
            self._audit(curator, "assign_id", {"document_id": document_id}, before, {"document_id": new_id}, reason)

    def link_citation(self, curator: Curator, citation_id: int, target_id: str, reason: str) -> None:
        with self.connection.transaction():
            self._begin(curator)
            relation, document_id, from_address, to_address, target_text, link_id = self._one(
                "SELECT relation, document_id, from_address, to_address, target_text, link_id "
                "FROM registry.citation WHERE id = %s",
                citation_id,
                missing=f"no citation {citation_id}",
            )
            self._require_document(target_id)
            (new_link,) = self.connection.execute(
                """
                INSERT INTO registry.link (type, from_document, from_address, to_document, to_address, method,
                    confidence)
                VALUES (%s, %s, %s, %s, %s, 'curated', 'high')
                ON CONFLICT (type, from_document, coalesce(from_address, ''), to_document, coalesce(to_address, ''))
                DO UPDATE SET method = 'curated', confidence = 'high'
                RETURNING id
                """,
                (relation, document_id, from_address, target_id, to_address),
            ).fetchone()
            self.connection.execute("UPDATE registry.citation SET link_id = %s WHERE id = %s", (new_link, citation_id))
            self._close_reviews(
                curator,
                ReviewKind.UNRESOLVED_CITATION,
                {"document_id": document_id, "target_text": target_text},
                reason,
            )
            self._audit(
                curator,
                "link_citation",
                {"citation_id": citation_id},
                {"link_id": link_id},
                {"to_document": target_id},
                reason,
            )
            touch(self.connection, [document_id])

    def resolve_conflict(self, curator: Curator, conflict_id: int, state: str, note: str) -> None:
        with self.connection.transaction():
            self._begin(curator)
            override_id, source_value = self._one(
                "UPDATE curation.conflict SET state = %s WHERE id = %s AND state = 'open' "
                "RETURNING override_id, source_value",
                state,
                conflict_id,
                missing=f"conflict {conflict_id} isn't open (resolved already, or no such conflict)",
            )
            document_id, field, value = self._one(
                "SELECT document_id, field, value FROM curation.override WHERE id = %s", override_id, missing="?"
            )
            if state == "accepted_source":
                self.connection.execute("UPDATE curation.override SET active = false WHERE id = %s", (override_id,))
            self._close_reviews(curator, ReviewKind.CONFLICT, {"override_id": override_id}, note)
            self._audit(
                curator,
                "resolve_conflict",
                {"conflict_id": conflict_id, "document_id": document_id, "field": field},
                {"correction": value, "source": source_value},
                {"state": state},
                note,
            )
            touch(self.connection, [document_id])

    def record(self, curator: Curator, action: str, target: Mapping[str, Any], after: Any, reason: str) -> None:
        with self.connection.transaction():
            self._begin(curator)
            self._audit(curator, action, dict(target), None, after, reason)

    # --- shared ----------------------------------------------------------------------------------

    def _begin(self, curator: Curator) -> None:
        """Team accounts come from the environment; the database learns each one at its first action."""
        self.connection.execute(
            "INSERT INTO curation.curator (username, display_name) VALUES (%s, %s) "
            "ON CONFLICT (username) DO UPDATE SET display_name = EXCLUDED.display_name",
            (curator.username, curator.display_name),
        )

    def _require_document(self, document_id: str) -> dict:
        row = self._one(
            "SELECT id, citation, title FROM registry.document WHERE id = %s",
            document_id,
            missing=f"no document {document_id}",
        )
        return {"document_id": row[0], "citation": row[1], "title": row[2]}

    def _one(self, query: Any, *params: Any, missing: str) -> tuple:
        row = self.connection.execute(query, params).fetchone()
        if row is None:
            raise CurationRefused(missing)
        return row

    def _close_reviews(self, curator: Curator, kind: ReviewKind, subject: Mapping[str, Any], note: str) -> None:
        self.connection.execute(
            "UPDATE curation.review_item SET state = 'resolved', decided_by = %s, decided_at = now(), note = %s "
            "WHERE kind = %s AND state = 'open' AND subject @> %s",
            (curator.username, note, kind.value, Jsonb(dict(subject))),
        )

    def _audit(self, curator: Curator, action: str, target: dict, before: Any, after: Any, reason: str) -> None:
        self.connection.execute(
            "INSERT INTO curation.audit_log (author, action, target, before, after, reason) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (curator.username, action, Jsonb(target), _jsonb(before), _jsonb(after), reason),
        )


class PostgresOverrides:
    """The loader's view of curation."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def active(self, document_id: str) -> list[ActiveOverride]:
        rows = self.connection.execute(
            "SELECT id, field, value, source_value FROM curation.override WHERE document_id = %s AND active",
            (document_id,),
        )
        return [ActiveOverride(*row) for row in rows]

    def raise_conflict(self, override_id: int, source_value: Any) -> None:
        self.connection.execute(
            "INSERT INTO curation.conflict (override_id, source_value) VALUES (%s, %s) "
            "ON CONFLICT (override_id) WHERE state = 'open' "
            "DO UPDATE SET source_value = EXCLUDED.source_value, detected_at = now()",
            (override_id, Jsonb(source_value)),
        )


def _overridable(field: str) -> sql.Identifier:
    if field not in OVERRIDABLE_FIELDS:  # also keeps the column name out of an injection's reach
        raise CurationRefused(f"{field} can't be corrected")
    return sql.Identifier(field)


def _jsonb(value: Any) -> Jsonb | None:
    return None if value is None else Jsonb(json.loads(json.dumps(value, default=_json)))
