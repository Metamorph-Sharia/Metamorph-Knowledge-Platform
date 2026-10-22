"""The vocabulary of clean texts that page quality is measured against, shipped with the package.
Built by scripts/build_vocabulary.py."""

from __future__ import annotations

from functools import cache
from importlib.resources import files


@cache
def load_vocabulary() -> frozenset[str]:
    text = files(__package__).joinpath("vocabulary.txt").read_text(encoding="utf-8")
    return frozenset(text.split())
