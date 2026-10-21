import pytest
from metamorph_pdf_text import (
    BlockKind,
    CacheKey,
    ExtractionUnavailable,
    ExtractPdf,
    OcrMode,
    Reading,
    ReadRequest,
    Tier,
)
from pdf_text_pages import TOP, block, page

PDF = b"%PDF-1.7 a regulation"
WORDING = "Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin usaha."
VOCABULARY = {"pasal", "setiap", "pelaku", "usaha", "wajib", "memiliki", "izin", "bank", "indonesia"}


class FakeReader:
    def __init__(self, engine: str, *pages, ocr_mode: OcrMode = OcrMode.TXT, version: str = "1.0") -> None:
        self.engine, self.version = engine, version
        self.reading = Reading(tuple(pages), ocr_mode)
        self.requests: list[ReadRequest] = []

    def read(self, pdf: bytes, request: ReadRequest) -> Reading:
        self.requests.append(request)
        return self.reading


class MemoryCache:
    def __init__(self) -> None:
        self.readings: dict[CacheKey, Reading] = {}

    def get(self, key: CacheKey) -> Reading | None:
        return self.readings.get(key)

    def put(self, key: CacheKey, reading: Reading) -> None:
        self.readings[key] = reading


def text_layer(*texts: str) -> FakeReader:
    return FakeReader("pymupdf", *(page(number, block(text)) for number, text in enumerate(texts, start=1)))


def extract(reader: FakeReader, layer: FakeReader, role: str = "main", cache: MemoryCache | None = None):
    return ExtractPdf(reader, layer, cache or MemoryCache(), VOCABULARY).run(PDF, role)


# Pages the reader read from the PDF's characters


def test_a_page_holding_the_text_layers_words_keeps_the_readers_layout() -> None:
    reader = FakeReader(
        "mineru",
        page(1, block("Pasal 5", kind=BlockKind.TITLE), block("Setiap Pelaku Usaha wajib\nmemiliki izin usaha.")),
    )

    extracted = extract(reader, text_layer("Pasal 5 Setiap Pelaku\nUsaha wajib memiliki izin usaha."))

    assert extracted.pages == ("Pasal 5\n\nSetiap Pelaku Usaha wajib memiliki izin usaha.",)
    assert extracted.method == "text_layer"
    assert extracted.extraction.pages_fallen_back == 0


def test_furniture_one_reading_took_off_does_not_count_as_a_lost_word() -> None:
    reader = FakeReader("mineru", page(2, block("BANK INDONESIA", TOP, BlockKind.HEADER), block(WORDING)))

    extracted = extract(reader, FakeReader("pymupdf", page(2, block("BANK INDONESIA", TOP), block(WORDING))))

    assert extracted.pages == ("Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin usaha.",)
    assert [(removal.rule, removal.text) for removal in extracted.removals] == [("furniture", "BANK INDONESIA")]


def test_a_reworded_page_falls_back_to_the_text_layer() -> None:
    reader = FakeReader("mineru", page(1, block("Pasal 5\nSetiap Pelaku Usaha harus memiliki izin usaha.")))

    extracted = extract(reader, text_layer(WORDING))

    assert extracted.pages == ("Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin usaha.",)
    assert extracted.extraction.pages_fallen_back == 1


def test_a_page_the_reader_left_out_falls_back_to_the_text_layer() -> None:
    reader = FakeReader("mineru", page(1, block(WORDING)))

    extracted = extract(reader, text_layer(WORDING, "Pasal 6"))

    assert extracted.pages == ("Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin usaha.", "Pasal 6")
    assert extracted.extraction.pages_fallen_back == 1


# Pages the reader read from the image


def test_ocr_cleaner_than_a_noisy_text_layer_is_kept() -> None:
    reader = FakeReader("mineru", page(1, block(WORDING)), ocr_mode=OcrMode.OCR)

    extracted = extract(reader, text_layer("Pasa1 5\nSet1ap Pe1aku Usaba wajlb rnemiliki lzin usaba."))

    assert extracted.pages == ("Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin usaha.",)
    assert extracted.method == "ocr"
    assert extracted.extraction.pages_ocrd == 1


def test_a_scan_keeps_its_ocr() -> None:
    reader = FakeReader("mineru", page(1, block(WORDING)), ocr_mode=OcrMode.OCR)

    extracted = extract(reader, FakeReader("pymupdf", page(1)))

    assert extracted.pages == ("Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin usaha.",)
    assert extracted.method == "ocr"


def test_ocr_noisier_than_a_clean_text_layer_falls_back() -> None:
    reader = FakeReader("mineru", page(1, block("動物乃らθ Pasal 5")), ocr_mode=OcrMode.OCR)

    extracted = extract(reader, text_layer(WORDING))

    assert extracted.pages == ("Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin usaha.",)
    assert extracted.method == "text_layer"
    assert (extracted.extraction.pages_ocrd, extracted.extraction.pages_fallen_back) == (0, 1)


def test_ocr_that_lost_a_pages_text_falls_back() -> None:
    reader = FakeReader("mineru", page(1), ocr_mode=OcrMode.OCR)

    extracted = extract(reader, text_layer(WORDING))

    assert extracted.extraction.pages_fallen_back == 1


# The request, the cache and the record of how a text was read


def test_a_noisy_text_layer_asks_the_reader_for_ocr() -> None:
    reader = FakeReader("mineru", page(1, block(WORDING)), ocr_mode=OcrMode.OCR)

    extract(reader, text_layer("Dew an Syar iah Nas ional"), role="annex")

    assert reader.requests == [ReadRequest(Tier.BASIC, OcrMode.OCR)]


def test_what_was_read_is_kept_and_not_read_again() -> None:
    reader, cache = FakeReader("mineru", page(1, block(WORDING))), MemoryCache()

    first = extract(reader, text_layer(WORDING), cache=cache)
    second = extract(reader, text_layer(WORDING), cache=cache)

    assert first == second
    assert len(reader.requests) == 1


def test_another_engine_version_reads_again() -> None:
    cache = MemoryCache()
    extract(FakeReader("mineru", page(1, block(WORDING)), version="4.0.12"), text_layer(WORDING), cache=cache)

    newer = FakeReader("mineru", page(1, block(WORDING)), version="4.0.13")
    extract(newer, text_layer(WORDING), cache=cache)

    assert len(newer.requests) == 1


def test_the_extraction_records_the_engine_tier_and_mode() -> None:
    reader = FakeReader("mineru", page(1, block(WORDING)), version="4.0.12")

    extraction = extract(reader, text_layer(WORDING)).extraction

    assert (extraction.engine, extraction.engine_version, extraction.tier, extraction.ocr_mode) == (
        "mineru",
        "4.0.12",
        Tier.STANDARD,
        OcrMode.TXT,
    )


def test_a_reader_out_of_reach_fails_the_extraction_and_nothing_falls_back() -> None:
    class Unreachable(FakeReader):
        def read(self, pdf: bytes, request: ReadRequest) -> Reading:
            raise ExtractionUnavailable("connection refused")

    with pytest.raises(ExtractionUnavailable):
        extract(Unreachable("mineru"), text_layer(WORDING))
