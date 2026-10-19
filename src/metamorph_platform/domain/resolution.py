"""Which document a citation means, among those the registry holds.

In order of strength: the ID the connector gave (exact_id), an ID the citation's text names
("Undang-Undang Nomor 21 Tahun 2011", also exact_id), and an alias of exactly that text (alias).
A citation whose target isn't held yet stays open and is tried again on every run, so it links as soon
as its target is loaded.
"""

from __future__ import annotations

from collections.abc import Container, Mapping
from dataclasses import dataclass

from metamorph_platform.domain.aliases import alias_key
from metamorph_platform.domain.references import references


@dataclass(frozen=True)
class Resolution:
    target_id: str
    method: str  # exact_id | alias (registry.link.method)


def resolve(
    target_id: str | None, target_text: str, *, known: Container[str], aliases: Mapping[str, str]
) -> Resolution | None:
    for candidate in named_targets(target_id, target_text):
        if candidate in known:
            return Resolution(candidate, "exact_id")
    aliased = aliases.get(alias_key(target_text))
    return Resolution(aliased, "alias") if aliased else None


def identifiable(target_id: str | None, target_text: str) -> bool:
    """False when nothing names the target: a person must link it by hand."""
    return bool(named_targets(target_id, target_text))


def named_targets(target_id: str | None, target_text: str) -> list[str]:
    """The IDs a citation names: the one its connector gave, then those its text names."""
    named = [ref.target_id for ref in references(target_text) if ref.target_id]
    return [*([target_id] if target_id else []), *named]
