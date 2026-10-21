"""Builds the vocabulary of clean texts that `page_quality` measures unknown words against.

The words are those of born-digital texts that passed the platform's structure checks: OJK's own website text
and BI's text layers. BPK is left out so its OCR is never judged by itself, and DSN-MUI because its text layers
are letter-spaced ("Dew an Syar iah"). A word is kept when at least MIN_TEXTS texts use it, so a typo in one
text doesn't become vocabulary.

    uv run --with pandas --with pyarrow python packages/metamorph-pdf-text/scripts/build_vocabulary.py \
        ../Metamorph-EDA/2026-10-16-registry-failure-rca/data

reads `texts.parquet` and `texts/<sha256>.md` from that snapshot and writes the package's `vocabulary.txt`.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

CLEAN_SOURCES = {("ojk", "source"), ("bi-website", "text_layer")}
MIN_TEXTS = 3
WORD = re.compile(r"[A-Za-z]{3,}")  # as domain/quality.py counts words
OUT = Path(__file__).resolve().parents[1] / "src" / "metamorph_pdf_text" / "adapters" / "vocabulary.txt"


def main(snapshot: Path) -> None:
    texts = pd.read_parquet(snapshot / "texts.parquet")
    clean = texts[[(c, m) in CLEAN_SOURCES for c, m in zip(texts.connector, texts.method, strict=True)]]
    clean = clean[~clean.is_suspect].drop_duplicates("sha256")
    used_by: Counter[str] = Counter()
    for sha256 in clean.sha256:
        body = (snapshot / "texts" / f"{sha256}.md").read_text("utf-8", errors="replace")
        used_by.update({word.lower() for word in WORD.findall(body)})
    words = sorted(word for word, count in used_by.items() if count >= MIN_TEXTS)
    OUT.write_text("".join(f"{word}\n" for word in words), encoding="utf-8")
    print(f"{len(words):,} words from {len(clean):,} texts → {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
