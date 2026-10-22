"""References inside a document: "Pasal 19 ayat (2)" pointing at this document's own provision."""

from __future__ import annotations

from metamorph_platform.domain.cross_references import CrossReference, cross_references

ADDRESSES = {"pasal-3", "pasal-3/ayat-1", "pasal-3/ayat-2", "pasal-4", "pasal-19", "pasal-19/ayat-2", "pasal-19/ayat-3",
             "pasal-20", "pasal-22", "penjelasan/pasal-3"}  # fmt: skip


def found(text: str, within: str | None = "pasal-4", extra: set[str] = frozenset()) -> list[tuple[str, str]]:
    references = cross_references(text, within=within, addresses=ADDRESSES | extra)
    return [(text[r.start : r.end], r.address) for r in references]


def test_an_article_and_its_paragraph_are_found_where_the_text_names_them() -> None:
    text = "dikenai sanksi sebagaimana dimaksud dalam Pasal 19 ayat (2) dan Pasal 20."

    assert found(text) == [("Pasal 19 ayat (2)", "pasal-19/ayat-2"), ("Pasal 20", "pasal-20")]
    assert cross_references(text, within="pasal-4", addresses=ADDRESSES)[0] == CrossReference(42, 59, "pasal-19/ayat-2")


def test_a_paragraph_named_alone_is_one_of_the_article_it_is_in_or_of_the_article_just_named() -> None:
    assert found("sebagaimana dimaksud pada ayat (1)", within="pasal-3/ayat-2") == [("ayat (1)", "pasal-3/ayat-1")]
    assert found("Pasal 19 ayat (2) dan ayat (3)") == [
        ("Pasal 19 ayat (2)", "pasal-19/ayat-2"),
        ("ayat (3)", "pasal-19/ayat-3"),
    ]
    assert found("Penjelasan ayat (2): cukup jelas.", within="penjelasan/pasal-3") == [("ayat (2)", "pasal-3/ayat-2")]
    assert found("Pasal 19 ayat (2) dan/atau ayat (3)")[1] == ("ayat (3)", "pasal-19/ayat-3")


def test_a_range_links_both_ends() -> None:
    assert found("Pasal 19 sampai dengan Pasal 22") == [("Pasal 19", "pasal-19"), ("Pasal 22", "pasal-22")]


def test_an_item_links_the_item_or_the_nearest_provision_up_the_text_has() -> None:
    assert found("Pasal 3 huruf a") == [("Pasal 3 huruf a", "pasal-3")]  # the text has no such item
    assert found("Pasal 3 huruf a", extra={"pasal-3/huruf-a"}) == [("Pasal 3 huruf a", "pasal-3/huruf-a")]
    assert found("Pasal 1 angka 2", extra={"pasal-1", "pasal-1/angka-2"}) == [("Pasal 1 angka 2", "pasal-1/angka-2")]
    assert found("ayat (2) huruf c", within="pasal-19/ayat-1", extra={"pasal-19/ayat-2/huruf-c"}) == [
        ("ayat (2) huruf c", "pasal-19/ayat-2/huruf-c")
    ]


def test_an_article_of_another_instrument_is_not_this_documents() -> None:
    assert found("sebagaimana dimaksud dalam Pasal 8 dan Pasal 19 Undang-Undang Nomor 21 Tahun 2011") == []
    assert found("Pasal 20 Peraturan Pemerintah Nomor 5 Tahun 2015") == []
    assert found("Pasal 20 POJK 10/POJK.05/2019") == []


def test_an_article_of_this_regulation_named_by_its_kind_is_this_documents() -> None:
    text = "sebagaimana dimaksud dalam Pasal 20 Peraturan Otoritas Jasa Keuangan ini"

    assert found(text) == [("Pasal 20", "pasal-20")]


def test_a_provision_the_text_doesnt_have_is_not_linked_but_its_article_is_when_held() -> None:
    assert found("Pasal 99 ayat (1)") == []
    assert found("Pasal 20 ayat (7)") == [("Pasal 20 ayat (7)", "pasal-20")]


def test_an_amending_regulations_quoted_articles_refer_to_the_amended_regulation() -> None:
    assert found("sebagaimana dimaksud dalam Pasal 20", within="pasal-i/pasal-115") == []
