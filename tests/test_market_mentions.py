"""What a passage names: regulations, by the regulation layer's one reference grammar, and companies, by their full
legal names. A mention says "names", never "revokes" or "issues" (market-data-layer-plan.md, Phase 5: Mentions)."""

from __future__ import annotations

from datetime import date

from metamorph_platform.domain.market.mentions import Mention, Passage, mentions
from metamorph_platform.domain.market.publication import PublishedCompany

PORTO = "ojk:siaran-pers:2026:ojk-cabut-izin-usaha-pt-porto-ventura-kapital"


def company(id_: str, legal_name: str) -> PublishedCompany:
    return PublishedCompany(id_, "ojk:lpbbti", legal_name, (), "conventional", "licensed", date(2021, 1, 1), None)


COMPANIES = [company("ojk:lpbbti:investree", "PT Investree Radhika Jaya"), company("ojk:lpbbti:tdf", "PT Tri Digi Fin")]


def test_a_regulation_named_is_a_mention_with_its_id_and_words() -> None:
    text = ("mencabut izin berdasarkan Pasal 38 Peraturan Otoritas Jasa Keuangan Nomor 49 Tahun 2024 sebagaimana telah "
            "diubah dengan Peraturan Otoritas Jasa Keuangan Nomor 25 Tahun 2025, dan POJK Nomor 49 Tahun 2024.")

    found = mentions([Passage("release", PORTO, "p-1", text)], [])

    assert found == [
        Mention("release", PORTO, "p-1", "regulation", "ojk:pojk:2024:49",
                "Peraturan Otoritas Jasa Keuangan Nomor 49 Tahun 2024"),
        Mention("release", PORTO, "p-1", "regulation", "ojk:pojk:2025:25",
                "Peraturan Otoritas Jasa Keuangan Nomor 25 Tahun 2025"),
    ]  # each target once a passage, as first written


def test_a_reference_that_names_no_instrument_is_not_a_mention() -> None:
    assert mentions([Passage("report", "ojk:lpksi:2025", "p-3", "Peraturan Menteri tentang hal itu.")], []) == []


def test_a_company_named_by_its_legal_name_is_a_mention_whatever_its_case_or_punctuation() -> None:
    text = "OJK mencabut izin usaha PT. INVESTREE RADHIKA JAYA (Investree) pada 21 Oktober 2024."

    (found,) = mentions([Passage("release", PORTO, "p-2", text)], COMPANIES)

    assert (found.target_kind, found.target, found.words) == ("company", "ojk:lpbbti:investree",
                                                              "PT. INVESTREE RADHIKA JAYA")


def test_a_legal_name_inside_a_longer_name_is_not_a_mention() -> None:
    text = "PT Tri Digi Finansial dan PT Investree saja."

    assert mentions([Passage("release", PORTO, "p-1", text)], COMPANIES) == []


def test_mentions_are_found_in_every_passage_of_every_document() -> None:
    passages = [Passage("report", "ojk:lpksi:2025", "p-1", "PT Tri Digi Fin tumbuh."),
                Passage("release", PORTO, "p-1", "Menurut POJK Nomor 10 Tahun 2022, PT Tri Digi Fin wajib.")]

    found = mentions(passages, COMPANIES)

    assert [(m.document, m.target) for m in found] == [
        ("ojk:lpksi:2025", "ojk:lpbbti:tdf"),
        (PORTO, "ojk:pojk:2022:10"),
        (PORTO, "ojk:lpbbti:tdf"),
    ]
