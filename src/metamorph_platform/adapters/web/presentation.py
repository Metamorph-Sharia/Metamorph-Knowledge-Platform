"""How values read on the curation pages: labels, choices, dates and numbers. One place, so pages agree."""

from __future__ import annotations

import difflib
import re
from datetime import UTC, date, datetime
from typing import Any

from jinja2 import Environment
from markupsafe import Markup
from metamorph_contract import Kind, Status

# The add-document form's text fields, in ManualDocument's names.
MANUAL_FIELDS = (
    "document_id",
    "citation",
    "title",
    "kind",
    "status",
    "language",
    "source_url",
    "reason",
    "text",
    "rights",
    "enacted_on",
    "promulgated_on",
    "effective_on",
)

FIELD_LABELS = {
    "citation": "Citation",
    "title": "Title",
    "kind": "Kind",
    "status": "Status",
    "status_as_of": "Status As Of",
    "year": "Year",
    "enacted_on": "Enacted",
    "promulgated_on": "Promulgated",
    "effective_on": "Effective",
}
FIELD_HINTS = {
    "status_as_of": "YYYY-MM-DD…",
    "enacted_on": "YYYY-MM-DD…",
    "promulgated_on": "YYYY-MM-DD…",
    "effective_on": "YYYY-MM-DD…",
    "year": "2019…",
}

# (tab label, what a curator does with an item, why items land here)
REVIEW_QUEUES = {
    "conflict": (
        "Conflicts",
        "Keep the correction or accept the source’s new value.",
        "A source changed a field that a curator had corrected.",
    ),
    "unresolved_citation": (
        "Unlinked Citations",
        "Link the citation to the document it means.",
        "The document cites something that names no document the registry can find.",
    ),
    "quarantine": (
        "Quarantine",
        "Ask the connector’s owner to fix the export, then dismiss.",
        "A bundle line broke the contract and wasn’t loaded.",
    ),
}

# (label, what a curator does about it) for each check of the publish gate (domain/gate.py)
HOLD_CHECKS = {
    "identity": ("Unidentified", "Assign the document’s canonical ID."),
    "text": ("No Main Text", "Ask the connector’s owner to acquire the regulation’s own text."),
    "parsed": ("Not Parsed Yet", "Nothing to do: the next build parses it."),
    "structure": ("Structure", "Fix it at its source or in the parser, or approve the problems as they are."),
}

KINDS = tuple(kind.value for kind in Kind)
STATUSES = tuple(status.value for status in Status)
RIGHTS = ("public", "licensed")

DONE = {
    "corrected": "Correction saved and published.",
    "withdrawn": "Correction withdrawn. The source’s value is back.",
    "suppressed": "Document suppressed. The assistant can’t cite it any more.",
    "restored": "Document restored. The assistant can cite it again.",
    "renamed": "ID assigned. Later loads of this record keep it.",
    "linked": "Citation linked.",
    "conflict": "Conflict resolved.",
    "resolved": "Review item resolved.",
    "dismissed": "Review item dismissed.",
    "added": "Document added and published.",
    "approved": "Approved. The document is checked again and published if it passes.",
    "unapproved": "Approval withdrawn. The document is checked again.",
    "text_corrected": "Text corrected, parsed again and checked. Published if it passes.",
    "text_restored": "Correction withdrawn. The source’s text is back, parsed again and checked.",
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # a source’s date, as its document states it
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def text_diff(before: str, after: str) -> list[str]:
    """A unified diff of a correction (source → corrected), with a few lines of context."""
    return list(difflib.unified_diff(before.splitlines(), after.splitlines(), "source", "correction", lineterm=""))


def day(value: Any) -> Markup:
    """<time datetime="2026-10-15">15 Oct 2026</time>: written out, so 05/06 never reads as two dates."""
    parsed = _as_date(value)
    if parsed is None:
        return Markup("")
    return Markup('<time datetime="{}">{}</time>').format(
        parsed.isoformat(), f"{parsed.day} {MONTHS[parsed.month - 1]} {parsed.year}"
    )


def moment(value: Any) -> Markup:
    if not isinstance(value, datetime):
        return day(value)
    utc = value.astimezone(UTC)
    shown_as = f"{utc.day} {MONTHS[utc.month - 1]} {utc.year}, {utc:%H:%M} UTC"
    return Markup('<time datetime="{}">{}</time>').format(utc.isoformat(timespec="minutes"), shown_as)


def count(value: int | None) -> str:
    return f"{value or 0:,}"


def shown(value: Any) -> str | Markup:
    """A field's value as text; an absent one says so instead of leaving a blank cell."""
    if value is None or value == "":
        return "Not set"
    if isinstance(value, date | datetime) or (isinstance(value, str) and _ISO_DATE.match(value)):
        return day(value)
    return str(value)


def sentence(value: str) -> str:
    """A message as a sentence: its first letter raised, the rest (IDs, YYYY-MM-DD) left as written."""
    text = str(value)
    return text[:1].upper() + text[1:]


def words(value: str) -> str:
    """in_force → in force."""
    return value.replace("_", " ")


def install(environment: Environment) -> None:
    environment.filters |= {
        "day": day,
        "moment": moment,
        "count": count,
        "shown": shown,
        "words": words,
        "sentence": sentence,
    }
    environment.globals |= {
        "FIELD_LABELS": FIELD_LABELS,
        "FIELD_HINTS": FIELD_HINTS,
        "REVIEW_QUEUES": REVIEW_QUEUES,
        "HOLD_CHECKS": HOLD_CHECKS,
        "KINDS": KINDS,
        "STATUSES": STATUSES,
        "RIGHTS": RIGHTS,
        "DONE": DONE,
    }


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None
