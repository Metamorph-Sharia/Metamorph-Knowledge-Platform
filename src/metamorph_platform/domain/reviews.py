"""When an open citation item no longer needs a person: the cause it was opened for is gone.

The rule takes what the registry now holds and returns the reason to record for settling the item, or
None while a person is still needed. An item is only ever settled for a cause that went away by itself
(a newer text, a later load, a better reading); a conflict or a quarantined line always waits for a person.
Structure and identity are not review items: the publish gate holds those documents (domain/gate.py).
"""

from __future__ import annotations

from collections.abc import Sequence


def citation_settlement(*, still_unlinked: bool, named: Sequence[str], citing: str) -> str | None:
    """Queued because nothing named the target: settled once it's linked, or once its text is read as
    naming a document (a newer reading of references), which it then waits for like any other citation."""
    if not still_unlinked:
        return "the citation was linked, or the text no longer cites it"
    if citing in named:
        return "the citation names the citing document itself: there is nothing to link"
    if named:
        return "the citation now names its document: it links as soon as that document is loaded"
    return None
