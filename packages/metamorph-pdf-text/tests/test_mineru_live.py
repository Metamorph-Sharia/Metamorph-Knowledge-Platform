"""Against a running MinerU service: set METAMORPH_TEST_MINERU_URL (and METAMORPH_TEST_MINERU_API_KEY if it has
one), e.g. METAMORPH_TEST_MINERU_URL=http://127.0.0.1:8010 uv run pytest -m mineru. Skipped otherwise."""

import os

import pytest
from metamorph_pdf_text import OcrMode, ReadRequest, Tier
from metamorph_pdf_text.adapters.mineru_reader import MINERU_VERSION, MinerUReader
from pdf_text_files import regulation_pdf

URL = os.environ.get("METAMORPH_TEST_MINERU_URL")

pytestmark = [pytest.mark.mineru, pytest.mark.skipif(not URL, reason="METAMORPH_TEST_MINERU_URL is not set")]


def test_the_service_reads_a_pdf() -> None:
    reader = MinerUReader(URL, os.environ.get("METAMORPH_TEST_MINERU_API_KEY"))

    reading = reader.read(regulation_pdf(), ReadRequest(Tier.BASIC, OcrMode.AUTO))

    assert reader.version.startswith(MINERU_VERSION)
    assert "Pelaku Usaha" in " ".join(block.text for block in reading.pages[0].blocks)
