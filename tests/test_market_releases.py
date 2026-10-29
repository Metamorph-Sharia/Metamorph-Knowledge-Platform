"""Press releases cut into passages and cited by their number and date (market-data-layer-plan.md, Phase 5)."""

from __future__ import annotations

import hashlib

from market_platform_samples import RELEASE_BODY, release_record

from metamorph_platform.domain.market.releases import releases

BODY_KEY = "market/files/body"
KEYS = {hashlib.sha256(RELEASE_BODY).hexdigest(): BODY_KEY}


def words(count: int, word: str = "kata") -> str:
    return " ".join([word] * count)


def test_a_release_is_cut_into_passages_as_a_report_is_but_without_pages() -> None:
    record = release_record("\n\n".join([words(200), words(150), words(200)]))

    found = releases([record], KEYS)

    (release,) = found.releases
    assert [passage.words for passage in found.passages] == [350, 200]
    assert [passage.address for passage in found.passages] == ["p-1", "p-2"]
    assert {passage.release for passage in found.passages} == {release.id}
    assert release.passages == 2


def test_a_release_is_published_with_its_number_date_page_and_body() -> None:
    (release,) = releases([release_record("SIARAN PERS\n\nOJK mencabut izin usaha.")], KEYS).releases

    assert release.id == "ojk:siaran-pers:2026:ojk-cabut-izin-usaha-pt-porto-ventura-kapital"
    assert (release.number, release.published_on, release.language) == ("SP 188/DKPU/OJK/X/2026", "2026-10-08", "id")
    assert release.url.endswith("/siaran-pers/Pages/OJK-Cabut-Izin-Usaha-PT-Porto-Ventura-Kapital.aspx")
    assert release.storage_key == BODY_KEY


def test_a_release_is_cited_by_its_issuer_number_and_date() -> None:
    numbered, unnumbered = releases(
        [release_record("Teks."), release_record("Teks.", name="kssk", published_on="2021-10-27", number=None)], KEYS
    ).releases

    assert numbered.citation == "Siaran Pers OJK SP 188/DKPU/OJK/X/2026, 8 Oktober 2026"
    assert unnumbered.citation == "Siaran Pers OJK, 27 Oktober 2021"


def test_a_release_without_words_is_held_back() -> None:
    found = releases([release_record("  ")], KEYS)

    assert (found.releases, found.passages) == ((), ())
    assert found.held_back == ("ojk:siaran-pers:2026:ojk-cabut-izin-usaha-pt-porto-ventura-kapital",)


def test_releases_are_published_newest_first() -> None:
    older = release_record("Teks.", name="lama", published_on="2020-02-04")

    found = releases([older, release_record("Teks.")], KEYS)

    assert [release.published_on for release in found.releases] == ["2026-10-08", "2020-02-04"]
