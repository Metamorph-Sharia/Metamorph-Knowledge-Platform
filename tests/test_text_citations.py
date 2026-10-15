"""Citations found in a document's own text: what it rests on, adopts, implements, amends and revokes."""

from __future__ import annotations

from metamorph_contract import Relation

from metamorph_platform.domain.citations import text_citations
from metamorph_platform.domain.structure import parse

OWN_ID = "ojk:pojk:2019:10"

REGULATION = """\
PERATURAN OTORITAS JASA KEUANGAN
NOMOR 10/POJK.05/2019
Menimbang : a. bahwa untuk melaksanakan ketentuan Pasal 20 ayat (4) dan Pasal 21 Peraturan Otoritas Jasa
Keuangan Nomor 28/POJK.05/2016 tentang Pembiayaan, perlu menetapkan peraturan;
Mengingat : 1. Undang-Undang Nomor 21 Tahun 2011 tentang Otoritas Jasa Keuangan;
2. Peraturan Pemerintah Nomor 9 Tahun 2009 tentang Lembaga Pembiayaan;
MEMUTUSKAN:
Pasal 1
Akad wajib sesuai Fatwa DSN-MUI Nomor 111/DSN-MUI/IX/2017 tentang Murabahah.
Pasal 2
Pada saat Peraturan Otoritas Jasa Keuangan ini mulai berlaku, Peraturan Otoritas Jasa Keuangan Nomor
31/POJK.05/2014 tentang Pembiayaan Syariah dicabut dan dinyatakan tidak berlaku.
Pasal 3
Pasal 5 dan Pasal 6 Peraturan Otoritas Jasa Keuangan Nomor 29/POJK.05/2014 dicabut dan dinyatakan tidak
berlaku.
Pasal 4
Peraturan Otoritas Jasa Keuangan ini mulai berlaku pada tanggal diundangkan.
PENJELASAN
Pasal 1
Peraturan Otoritas Jasa Keuangan Nomor 1/POJK.05/2010 dicabut dan dinyatakan tidak berlaku.
"""


def cited(text: str, own_id: str = OWN_ID, grammar: str = "peraturan"):
    return [
        (c.relation, c.target_id, c.from_address, c.to_address)
        for c in text_citations(text, parse(text, grammar), document_id=own_id)
    ]


def test_mengingat_names_the_legal_basis():
    found = cited(REGULATION)

    assert (Relation.LEGAL_BASIS, "id:uu:2011:21", None, None) in found
    assert (Relation.LEGAL_BASIS, "id:pp:2009:9", None, None) in found


def test_a_numbered_fatwa_is_adopted_where_it_is_cited():
    assert (Relation.ADOPTS_FATWA, "dsnmui:fatwa:111", "pasal-1", None) in cited(REGULATION)


def test_a_fatwa_citing_an_earlier_fatwa_refers_to_it():
    fatwa = "MEMUTUSKAN\nPertama : Ketentuan Umum\nSebagaimana Fatwa Nomor 04/DSN-MUI/IV/2000.\n"

    assert cited(fatwa, "dsnmui:fatwa:111", "fatwa") == [(Relation.REFERS_TO, "dsnmui:fatwa:4", "diktum-pertama", None)]


def test_revocations_in_the_body_are_whole_or_of_named_articles():
    found = cited(REGULATION)

    assert (Relation.REVOKES, "ojk:pojk:2014:31", "pasal-2", None) in found
    assert (Relation.PARTLY_REVOKES, "ojk:pojk:2014:29", "pasal-3", "pasal-5") in found
    assert (Relation.PARTLY_REVOKES, "ojk:pojk:2014:29", "pasal-3", "pasal-6") in found
    assert not [c for c in found if c[1] == "ojk:pojk:2010:1"]  # the elucidation only explains


def test_the_articles_a_regulation_implements_are_named_in_its_considerations():
    found = cited(REGULATION)

    assert (Relation.IMPLEMENTS, "ojk:pojk:2016:28", None, "pasal-20/ayat-4") in found
    assert (Relation.IMPLEMENTS, "ojk:pojk:2016:28", None, "pasal-21") in found


def test_a_circular_names_what_it_implements_in_its_opening():
    circular = (
        "SURAT EDARAN OTORITAS JASA KEUANGAN\nNOMOR 1/SEOJK.04/2020\n"
        "Dalam rangka pelaksanaan amanat ketentuan Pasal 20 ayat (4) Peraturan Otoritas Jasa Keuangan\n"
        "Nomor 28/POJK.04/2016 tentang Reksa Dana, perlu diatur.\nI. KETENTUAN UMUM\nIsi.\n"
    )

    assert cited(circular, "ojk:seojk:2020:1", "surat_edaran") == [
        (Relation.IMPLEMENTS, "ojk:pojk:2016:28", None, "pasal-20/ayat-4")
    ]


def test_an_amending_regulation_amends_its_target_article_by_article():
    amending = """\
Pasal I
Beberapa ketentuan dalam Peraturan Otoritas Jasa Keuangan Nomor 35/POJK.05/2018 tentang Perusahaan
Pembiayaan diubah sebagai berikut:
1. Ketentuan ayat (1) Pasal 115 diubah sehingga berbunyi sebagai berikut:
Pasal 115
(1) Perusahaan wajib melapor.
2. Di antara Pasal 82 dan Pasal 83 disisipkan 1 (satu) pasal, yakni Pasal 82A sehingga berbunyi:
Pasal 82A
Isi baru.
3. Pasal 30 dihapus.
Pasal II
Peraturan ini mulai berlaku pada tanggal diundangkan.
"""
    found = cited(amending, "ojk:pojk:2022:7")

    assert found == [
        (Relation.AMENDS, "ojk:pojk:2018:35", "pasal-i", None),
        (Relation.AMENDS, "ojk:pojk:2018:35", "pasal-i", "pasal-115"),
        (Relation.AMENDS, "ojk:pojk:2018:35", "pasal-i", "pasal-82a"),
        (Relation.PARTLY_REVOKES, "ojk:pojk:2018:35", "pasal-i", "pasal-30"),
    ]


def test_a_document_never_cites_itself():
    assert not [c for c in cited(REGULATION) if c[1] == OWN_ID]


def test_a_revocation_in_a_numbered_paragraph_is_read_from_the_paragraph_itself():
    text = "Pasal 9\n(1) Peraturan Otoritas Jasa Keuangan Nomor 3/POJK.05/2013 dicabut dan dinyatakan tidak berlaku.\n"

    assert cited(text) == [(Relation.REVOKES, "ojk:pojk:2013:3", "pasal-9/ayat-1", None)]
