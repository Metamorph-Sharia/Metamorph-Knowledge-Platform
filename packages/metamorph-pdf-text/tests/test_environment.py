"""The engine setting, and the whole extraction composed: MinerU (a scripted service) checked against a real
PDF's text layer, its reading kept on disk."""

import httpx
import pytest
from metamorph_pdf_text import ExtractPdf, from_environment, wants_mineru
from metamorph_pdf_text.adapters.file_cache import FileResultCache
from metamorph_pdf_text.adapters.mineru_reader import MinerUReader
from metamorph_pdf_text.adapters.pymupdf_reader import PyMuPdfReader
from metamorph_pdf_text.adapters.vocabulary import load_vocabulary
from pdf_text_files import regulation_pdf
from test_mineru_reader import URL, FakeMinerU


def test_the_connectors_own_extraction_is_the_default() -> None:
    assert not wants_mineru({})
    assert not wants_mineru({"METAMORPH_PDF_ENGINE": "pymupdf"})
    assert wants_mineru({"METAMORPH_PDF_ENGINE": "mineru"})


def test_an_unknown_engine_is_refused() -> None:
    with pytest.raises(ValueError, match="METAMORPH_PDF_ENGINE"):
        wants_mineru({"METAMORPH_PDF_ENGINE": "tesseract"})


def test_mineru_needs_its_url_and_a_cache() -> None:
    with pytest.raises(ValueError, match="METAMORPH_MINERU_URL and METAMORPH_MINERU_CACHE"):
        from_environment({"METAMORPH_PDF_ENGINE": "mineru"})


def test_the_extraction_is_composed_from_the_environment(tmp_path) -> None:
    environment = {"METAMORPH_MINERU_URL": URL, "METAMORPH_MINERU_CACHE": str(tmp_path)}

    assert isinstance(from_environment(environment), ExtractPdf)


def test_the_vocabulary_ships_with_the_package() -> None:
    assert {"pasal", "ayat", "bahwa", "peraturan", "syariah"} <= load_vocabulary()


def test_minerus_reading_of_a_born_digital_page_is_checked_against_its_text_layer(tmp_path) -> None:
    service = FakeMinerU()
    page = {"page_idx": 0, "blocks": []}
    for index, (kind, text, box) in enumerate(
        [
            ("header", "BANK INDONESIA", [0.42, 0.04, 0.58, 0.06]),
            ("paragraph_title", "Pasal 5", [0.1, 0.22, 0.2, 0.24]),
            ("text", "Setiap Pelaku Usaha wajib memiliki izin.", [0.1, 0.26, 0.9, 0.3]),
            ("footer", "SK No 054949 C", [0.1, 0.94, 0.3, 0.96]),
        ]
    ):
        page["blocks"].append(
            {"type": kind, "index": index, "bbox": box, "content": [{"type": "text", "content": text}]}
        )
    document = {
        "schema": "docvortex.middle",
        "schema_version": "2.0",
        "metadata": {"file_suffix": "pdf", "producer": {"name": "mineru", "version": "4.0.12"}},
        "extensions": {"mineru": {"tier": "standard", "parse_mode": "txt"}},
        "is_full_document": True,
        "pages": [page],
    }
    service.answers[("GET", "/v1/files/file-middle/content")] = httpx.Response(200, json=document)
    reader = MinerUReader(URL, transport=httpx.MockTransport(service), sleep=lambda seconds: None)
    extract = ExtractPdf(reader, PyMuPdfReader(), FileResultCache(tmp_path), load_vocabulary())

    extracted = extract.run(regulation_pdf(), "main")

    # the first page's head names the issuer, so it stays; the serial goes
    assert extracted.pages == ("BANK INDONESIA\n\nPasal 5\n\nSetiap Pelaku Usaha wajib memiliki izin.",)
    assert (extracted.method, extracted.extraction.pages_fallen_back) == ("text_layer", 0)
    assert extracted.extraction.engine_version == "4.0.12+t1"
    assert [(removal.rule, removal.text) for removal in extracted.removals] == [("furniture", "SK No 054949 C")]


def test_an_extraction_is_recorded_as_the_contract_records_it() -> None:
    from metamorph_contract import Extraction, ExtractionMethod
    from metamorph_pdf_text import ExtractedPdf, OcrMode, Tier, text_extraction, text_method
    from metamorph_pdf_text import Extraction as Read

    extracted = ExtractedPdf(("Pasal 1",), "ocr", Read("mineru", "4.0.12+t1", Tier.BASIC, OcrMode.OCR, 1, 0), ())

    assert text_method(extracted) is ExtractionMethod.OCR
    assert text_extraction(extracted) == Extraction("mineru", "4.0.12+t1", "basic", "ocr", 1, 0)
