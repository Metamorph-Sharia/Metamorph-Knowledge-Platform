from metamorph_pdf_text import BlockKind, CacheKey, OcrMode, Reading, ReadRequest, Tier
from metamorph_pdf_text.adapters.file_cache import FileResultCache
from pdf_text_pages import FOOT, block, page

KEY = CacheKey("ab" + "0" * 62, "mineru", "4.0.12+t1", ReadRequest(Tier.STANDARD, OcrMode.AUTO))
READING = Reading((page(1, block("Pasal 1")), page(2, block("SK No 054949 C", FOOT, BlockKind.FOOTER))), OcrMode.OCR)


def test_a_reading_put_is_got_back_as_it_was(tmp_path) -> None:
    cache = FileResultCache(tmp_path)

    cache.put(KEY, READING)

    assert cache.get(KEY) == READING


def test_a_reading_never_put_is_not_there(tmp_path) -> None:
    assert FileResultCache(tmp_path).get(KEY) is None


def test_another_version_or_request_is_another_reading(tmp_path) -> None:
    cache = FileResultCache(tmp_path)
    cache.put(KEY, READING)

    assert cache.get(CacheKey(KEY.pdf_sha256, "mineru", "4.0.13+t1", KEY.request)) is None
    assert cache.get(CacheKey(KEY.pdf_sha256, "mineru", KEY.version, ReadRequest(Tier.BASIC, OcrMode.AUTO))) is None


def test_readings_are_kept_by_file_and_nothing_half_written_is_left(tmp_path) -> None:
    FileResultCache(tmp_path).put(KEY, READING)

    (written,) = tmp_path.rglob("*.json")
    assert written.relative_to(tmp_path).parts[:2] == ("ab", KEY.pdf_sha256)
    assert not list(tmp_path.rglob("*.part"))
