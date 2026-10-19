"""What the Metamorph team may change, and how a correction meets the sources' later values.

Curation is an overlay: source records are never edited. A correction (override) replaces one field's
effective value; an assigned ID renames a document its connector couldn't identify, and keeps
applying on every later load of the same source record.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from metamorph_contract import Confidence, Kind, NormalizedDocument, Status, is_canonical, is_unresolved, split_pages

from metamorph_platform.domain.publishing import OVERRIDABLE_FIELDS

FIRST_YEAR, LAST_YEAR = 1945, 2100  # the Republic's laws, and some margin
PARTS_WITH_YEAR = 4  # issuer:family:year:number; a series that never repeats leaves the year out
DATE_FIELDS = frozenset({"status_as_of", "enacted_on", "promulgated_on", "effective_on"})
CHOICES = {"kind": tuple(k.value for k in Kind), "status": tuple(s.value for s in Status)}


class InvalidCorrection(ValueError):
    """What a curator entered can't be applied; the message says what is expected."""


@dataclass(frozen=True)
class ActiveOverride:
    id: int
    field: str
    value: Any
    source_value: Any  # what the sources said when the curator made the correction


def parse_correction(field: str, raw: str) -> Any:
    """The value to store for `field`, from what the curator typed."""
    if field not in OVERRIDABLE_FIELDS:
        raise InvalidCorrection(f"{field} can't be corrected; choose one of {', '.join(sorted(OVERRIDABLE_FIELDS))}")
    text = raw.strip()
    if not text:
        raise InvalidCorrection(f"{field} can't be empty")
    if field in CHOICES:
        if text not in CHOICES[field]:
            raise InvalidCorrection(f"{field} must be one of {', '.join(CHOICES[field])}")
        return text
    if field in DATE_FIELDS:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise InvalidCorrection(f"{field} must be a date written YYYY-MM-DD, e.g. 2019-02-27") from None
    if field == "year":
        if not text.isdigit() or not FIRST_YEAR <= int(text) <= LAST_YEAR:
            raise InvalidCorrection(f"year must be a year between {FIRST_YEAR} and {LAST_YEAR}")
        return int(text)
    return text


def source_values(document: NormalizedDocument) -> dict[str, Any]:
    """The overridable fields as this source record states them (JSON-ready, like stored overrides)."""
    info = document.document
    return {
        "citation": info.citation,
        "title": info.title,
        "kind": info.kind.value,
        "status": info.status.value.value,
        "status_as_of": info.status.as_of,
        "enacted_on": info.dates.enacted,
        "promulgated_on": info.dates.promulgated,
        "effective_on": info.dates.effective,
        "year": info.year,
    }


def conflicts(overrides: list[ActiveOverride], values: dict[str, Any]) -> list[tuple[ActiveOverride, Any]]:
    """Overrides whose field the source changed since the correction, to something the curator didn't choose."""
    return [
        (override, values[override.field])
        for override in overrides
        if override.field in values
        and values[override.field] != override.source_value
        and values[override.field] != override.value
    ]


def validate_assigned_id(raw: str) -> str:
    candidate = raw.strip().lower()
    if not is_canonical(candidate) or is_unresolved(candidate):
        raise InvalidCorrection(
            "the ID must be canonical: issuer:family:year:number, e.g. ojk:pojk:2019:10 or dsnmui:fatwa:117"
        )
    return candidate


def id_parts(canonical: str) -> tuple[str, str, int | None, str]:
    """(issuer, family, year, number) of `issuer:family[:year]:number`."""
    parts = canonical.split(":")
    year = int(parts[2]) if len(parts) == PARTS_WITH_YEAR else None
    return parts[0], parts[1], year, parts[-1]


def with_assigned_id(document: NormalizedDocument, assigned_id: str) -> NormalizedDocument:
    """The source record as the curator identified it: the ID, and the issuer, family, year and number it names."""
    issuer, family, year, number = id_parts(assigned_id)
    info = replace(
        document.document,
        id=assigned_id,
        issuer=issuer,
        family=family,
        number=number,
        year=year if year is not None else document.document.year,
        id_confidence=Confidence.HIGH,
        id_evidence=f"assigned by a curator (the connector said {document.document.id})",
    )
    return replace(document, document=info)


def checked_text_correction(current: str, corrected: str, *, paged: bool) -> str:
    """The corrected wording of a text, as it will be stored: `\\n` line endings and a final newline.

    A paged text keeps every page marker (`<!-- page N -->`) in order: page numbers come from them, so a
    lost or moved one would misplace every provision after it.
    """
    text = _normalised(corrected)
    if not text.strip():
        raise InvalidCorrection("the text can't be empty")
    if text == _normalised(current):
        raise InvalidCorrection("the text is unchanged: there is nothing to correct")
    if paged:
        _check_pages(_page_numbers(current), _page_numbers(text))
    return text


def _normalised(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def _page_numbers(text: str) -> list[int]:
    return [number for number, _ in split_pages(text)]


def _check_pages(before: list[int], after: list[int]) -> None:
    lost = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    if lost:
        raise InvalidCorrection(f"keep every page marker: the one for page {lost[0]} (<!-- page {lost[0]} -->) is gone")
    if added:
        raise InvalidCorrection(f"don't add page markers: page {added[0]} isn't in the source's text")
    if before != after:
        raise InvalidCorrection("keep the page markers in their order")
