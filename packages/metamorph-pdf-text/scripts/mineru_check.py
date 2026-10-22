"""Checks a MinerU service before connectors are pointed at it: it runs the pinned version, serves the tiers
`request_for` asks for, and each tier's models read a page, from its text and from its image. Given PDFs, it
also times them per tier and mode, so the pages per minute of a re-extraction are known.

    uv run python packages/metamorph-pdf-text/scripts/mineru_check.py [--url URL] [PDF ...]

The URL and API key are METAMORPH_MINERU_URL and METAMORPH_MINERU_API_KEY, as for a connector (the URL defaults
to the service on this Mac). It reads through the service, never through the cache. Exits 1 when a check fails.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pymupdf
from metamorph_pdf_text import ExtractionFailed, ExtractionUnavailable, OcrMode, Reading, ReadRequest, Tier
from metamorph_pdf_text.adapters.mineru_reader import MINERU_VERSION, MinerUReader
from metamorph_pdf_text.environment import API_KEY_SETTING, URL_SETTING

ON_THIS_MAC = "http://127.0.0.1:8010"
SAMPLE = "Setiap Pelaku Usaha wajib memiliki izin usaha."
MODES = (OcrMode.AUTO, OcrMode.OCR)  # the text layer where it can be used, and the page images
SECONDS_PER_MINUTE = 60


def main() -> int:
    arguments = _arguments()
    reader = MinerUReader(arguments.url, os.environ.get(API_KEY_SETTING) or None)
    try:
        print(f"{'version':<8} MinerU {reader.version} at {arguments.url} (pinned: {MINERU_VERSION})")
        missing = sorted(set(Tier) - reader.tiers())
        if missing:
            print(f"{'FAIL':<8} tiers not served: {', '.join(missing)} (start it with --tier standard)")
            return 1
        print(f"{'tiers':<8} {', '.join(sorted(Tier))}")
        models_read = all(_reads_the_sample(reader, tier, mode) for tier in Tier for mode in MODES)
        for tier in Tier:
            for mode in MODES:
                _time(reader, arguments.pdfs, tier, mode)
    except (ExtractionFailed, ExtractionUnavailable) as error:
        print(f"{'FAIL':<8} {error}")
        return 1
    return 0 if models_read else 1


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=os.environ.get(URL_SETTING) or ON_THIS_MAC)
    parser.add_argument("pdfs", nargs="*", type=Path, help="PDFs to time each tier and mode with")
    return parser.parse_args()


def _reads_the_sample(reader: MinerUReader, tier: Tier, mode: OcrMode) -> bool:
    """A tier's models load on its first read, so this also keeps that load out of the timings."""
    started = time.monotonic()
    reading = reader.read(_sample_pdf(), ReadRequest(tier, mode))
    read = "Pelaku Usaha" in _text(reading)
    _row("models" if read else "FAIL", tier, mode, reading, time.monotonic() - started, repr(_text(reading)))
    return read


def _time(reader: MinerUReader, pdfs: list[Path], tier: Tier, mode: OcrMode) -> None:
    pages, seconds = 0, 0.0
    for path in pdfs:
        started = time.monotonic()
        reading = reader.read(path.read_bytes(), ReadRequest(tier, mode))
        elapsed = time.monotonic() - started
        pages, seconds = pages + len(reading.pages), seconds + elapsed
        _row("timed", tier, mode, reading, elapsed, f"{len(reading.pages):4} pages  {path.name}")
    if pdfs:
        rate = pages * SECONDS_PER_MINUTE / seconds
        print(f"{'rate':<8} {tier:<8} {mode:<4}   {rate:6.1f} pages a minute over {pages} pages")


def _row(label: str, tier: Tier, mode: OcrMode, reading: Reading, seconds: float, what: str) -> None:
    print(f"{label:<8} {tier:<8} {mode:<4} → {reading.ocr_mode:<3} {seconds:6.1f} s  {what}")


def _sample_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), "Pasal 1", fontsize=12)
    page.insert_text((72, 130), SAMPLE, fontsize=12)
    return document.tobytes()


def _text(reading: Reading) -> str:
    return " ".join(block.text for page in reading.pages for block in page.blocks)


if __name__ == "__main__":
    sys.exit(main())
