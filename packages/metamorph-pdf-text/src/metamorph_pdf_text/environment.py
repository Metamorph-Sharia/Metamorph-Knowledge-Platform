"""The composition root: which engine reads a connector's PDFs, from its environment.

    METAMORPH_PDF_ENGINE      pymupdf (the default): the connector's own extraction, unchanged, as before
                              mineru: ExtractPdf, MinerU checked against the text layer
    METAMORPH_MINERU_URL      the MinerU service, e.g. http://host.docker.internal:8010
    METAMORPH_MINERU_API_KEY  its API key, if it was started with one
    METAMORPH_MINERU_CACHE    the directory MinerU's readings are kept in

`pymupdf` is the rollback: cleaning and rendering change a text, so going back means not running them at all.
A connector asks `wants_mineru(environ)` and builds `from_environment(environ)` only when it does.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from metamorph_pdf_text.adapters.file_cache import FileResultCache
from metamorph_pdf_text.adapters.mineru_reader import MinerUReader
from metamorph_pdf_text.adapters.pymupdf_reader import PyMuPdfReader
from metamorph_pdf_text.adapters.vocabulary import load_vocabulary
from metamorph_pdf_text.application.extract_pdf import ExtractPdf

ENGINE_SETTING = "METAMORPH_PDF_ENGINE"
URL_SETTING = "METAMORPH_MINERU_URL"
API_KEY_SETTING = "METAMORPH_MINERU_API_KEY"
CACHE_SETTING = "METAMORPH_MINERU_CACHE"
SETTINGS = (ENGINE_SETTING, URL_SETTING, API_KEY_SETTING, CACHE_SETTING)  # what an orchestrator passes on
PYMUPDF, MINERU = "pymupdf", "mineru"


def wants_mineru(environment: Mapping[str, str]) -> bool:
    value = environment.get(ENGINE_SETTING, PYMUPDF)
    if value not in (PYMUPDF, MINERU):
        raise ValueError(f"{ENGINE_SETTING} must be {PYMUPDF!r} or {MINERU!r}, not {value!r}")
    return value == MINERU


def from_environment(environment: Mapping[str, str]) -> ExtractPdf:
    missing = [name for name in (URL_SETTING, CACHE_SETTING) if not environment.get(name)]
    if missing:
        raise ValueError(f"{ENGINE_SETTING}={MINERU} needs {' and '.join(missing)}")
    reader = MinerUReader(environment[URL_SETTING], environment.get(API_KEY_SETTING) or None)
    cache = FileResultCache(Path(environment[CACHE_SETTING]))
    return ExtractPdf(reader, PyMuPdfReader(), cache, load_vocabulary())
