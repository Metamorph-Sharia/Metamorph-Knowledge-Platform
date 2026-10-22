"""Counts the pages a re-extraction will send to MinerU, and how many it will OCR, from the PDFs' text layers
alone: no MinerU is called. The request is the one `ExtractPdf` makes (`request_for` over the cleaned, rendered
text layer), so the count is what a run will ask for. It prices a run before it starts (docs/aws-step9-guide.md).

    uv run python packages/metamorph-pdf-text/scripts/ocr_census.py NAME=DIR [NAME=DIR ...]

e.g. BPK=../BPK-Source-Connector/data/raw. Every PDF under DIR counts once, however many copies there are.
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter
from pathlib import Path

from metamorph_pdf_text import ExtractionFailed, OcrMode, ReadRequest, Tier, clean, page_quality, render, request_for
from metamorph_pdf_text.adapters.pymupdf_reader import PyMuPdfReader
from metamorph_pdf_text.adapters.vocabulary import load_vocabulary

PDF_MAGIC = b"%PDF-"
TEXT_LAYER = ReadRequest(Tier.BASIC, OcrMode.TXT)
MAIN = "main"  # the role doesn't change the OCR decision, only the tier
COLUMNS = ("files", "pages", "ocr_forced", "no_text", "unreadable")


def main(arguments: list[str]) -> None:
    reader, vocabulary, seen = PyMuPdfReader(), load_vocabulary(), set()
    totals: Counter[str] = Counter()
    print(f"{'':<10}" + "".join(f"{column:>12}" for column in COLUMNS))
    for argument in arguments:
        name, directory = argument.split("=", 1)
        counts = Counter()
        for path in sorted(Path(directory).rglob("*")):
            pdf = path.read_bytes() if path.is_file() and _is_pdf(path) else None
            if pdf is None or (digest := hashlib.sha256(pdf).hexdigest()) in seen:
                continue
            seen.add(digest)
            counts.update(_census(pdf, reader, vocabulary))
        totals.update(counts)
        _row(name, counts)
    _row("all", totals)


def _census(pdf: bytes, reader: PyMuPdfReader, vocabulary) -> Counter[str]:
    """`ocr_forced`: pages of a file whose text layer is too noisy to trust; `no_text`: pages, in the other files,
    with no text layer at all, which MinerU's `auto` mode OCRs too."""
    try:
        texts = render(clean(reader.read(pdf, TEXT_LAYER).pages).pages)
    except ExtractionFailed:
        return Counter(unreadable=1)
    request = request_for(MAIN, [page_quality(text, vocabulary) for text in texts])
    forced = request.ocr_mode is OcrMode.OCR
    no_text = 0 if forced else sum(not text.strip() for text in texts)
    return Counter(files=1, pages=len(texts), ocr_forced=len(texts) if forced else 0, no_text=no_text)


def _is_pdf(path: Path) -> bool:
    with path.open("rb") as file:
        return file.read(len(PDF_MAGIC)) == PDF_MAGIC


def _row(name: str, counts: Counter[str]) -> None:
    print(f"{name:<10}" + "".join(f"{counts[column]:>12,}" for column in COLUMNS))


if __name__ == "__main__":
    main(sys.argv[1:])
