"""The review queue's open items, the registry facts that decide them, and settling one as the platform.

Settling goes through the curators' own path (decide_review): only an open item can be decided, the
decision carries its reason, and it is written to curation.audit_log in the same transaction. The
platform is a curator of its own, so every decision still has an author.
"""

from __future__ import annotations

import psycopg

from metamorph_platform.adapters.postgres.curation import PostgresCurationActions
from metamorph_platform.adapters.postgres.derived import MAIN_TEXT
from metamorph_platform.application.ports import Curator, OpenReview
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.reviews import TextStanding

PLATFORM = Curator("metamorph-platform", "Metamorph platform (automatic)")

_OPEN = "SELECT id, kind, subject FROM curation.review_item WHERE state = 'open' ORDER BY id"
_STANDING = f"""
SELECT t.is_current, {MAIN_TEXT} AS main, t.parsed_with, coalesce(t.structure_problems, '[]'::jsonb)
FROM registry.text_version t
WHERE t.document_id = %s AND t.sha256 = %s
"""
# A citation still waiting: the source sent it, or the document's current text makes it (a replaced text's
# citations stay behind with it).
_UNLINKED = """
SELECT EXISTS (
    SELECT 1 FROM registry.citation c
    WHERE c.document_id = %s AND c.target_text = %s AND c.link_id IS NULL
      AND (c.origin = 'source' OR EXISTS (
            SELECT 1 FROM registry.text_version t WHERE t.id = c.text_version_id AND t.is_current)))
"""


class PostgresOpenReviews:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection
        self.decisions = PostgresCurationActions(connection)

    def open_items(self) -> list[OpenReview]:
        return [OpenReview(id, ReviewKind(kind), subject) for id, kind, subject in self.connection.execute(_OPEN)]

    def text_standing(self, document_id: str, text_sha256: str) -> TextStanding | None:
        row = self.connection.execute(_STANDING, (document_id, text_sha256)).fetchone()
        if row is None:
            return None
        current, main, parsed_with, problems = row
        return TextStanding(current=current, main=main, parsed_with=parsed_with, problems=tuple(problems))

    def still_unlinked(self, document_id: str, target_text: str) -> bool:
        return self.connection.execute(_UNLINKED, (document_id, target_text)).fetchone()[0]

    def document_exists(self, document_id: str) -> bool:
        query = "SELECT EXISTS (SELECT 1 FROM registry.document WHERE id = %s)"
        return self.connection.execute(query, (document_id,)).fetchone()[0]

    def settle(self, item_id: int, reason: str) -> None:
        self.decisions.decide_review(PLATFORM, item_id, "resolved", reason)
