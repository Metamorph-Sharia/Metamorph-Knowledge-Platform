"""Paged texts: one UTF-8 text, pages introduced by `<!-- page N -->` lines.

An HTML comment stays invisible when the text is rendered as Markdown and never appears in
legal text, so it can't be mistaken for content. Page numbers start at 1.
"""

from __future__ import annotations

import re

_MARKER = re.compile(r"^<!-- page (\d+) -->$", re.MULTILINE)


def page_marker(number: int) -> str:
    return f"<!-- page {number} -->"


def join_pages(pages: list[str]) -> str:
    return "\n\n".join(f"{page_marker(number)}\n{content.strip()}" for number, content in enumerate(pages, start=1))


def split_pages(text: str) -> list[tuple[int, str]]:
    """[(page number, page text)]; text before the first marker, if any, is ignored."""
    markers = list(_MARKER.finditer(text))
    pages = []
    for current, following in zip(markers, [*markers[1:], None], strict=True):
        end = following.start() if following else len(text)
        pages.append((int(current[1]), text[current.end() : end].strip()))
    return pages
