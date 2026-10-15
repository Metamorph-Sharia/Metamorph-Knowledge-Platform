"""The shared structure parser: a legal text → addressable provisions, located by character offsets."""

from __future__ import annotations

from metamorph_platform.domain.structure import grammar_for, parse

POJK = """\
PERATURAN OTORITAS JASA KEUANGAN
NOMOR 10 /POJK.05/2019
TENTANG
PEMBIAYAAN SYARIAH
Menimbang : a. bahwa untuk melaksanakan tugas;
Mengingat : Undang-Undang Nomor 21 Tahun 2011 tentang Otoritas Jasa
Keuangan;
MEMUTUSKAN:
Menetapkan : PERATURAN OTORITAS JASA KEUANGAN TENTANG PEMBIAYAAN SYARIAH.
BAB I
KETENTUAN UMUM
Pasal 1
Dalam Peraturan ini yang dimaksud dengan:
1. Perusahaan Syariah adalah perusahaan.
BAB II
KEGIATAN USAHA
Bagian Kesatu
Jenis Kegiatan
Pasal 2
(1) Pembiayaan Jual Beli sebagaimana dimaksud dalam
Pasal 1 dilakukan dengan akad.
(2) Pembiayaan Investasi sebagaimana dimaksud pada ayat
(1) dilakukan dengan akad.
Pasal 3 . . .
Pasal 3
Kegiatan usaha dapat dilakukan.
Ditetapkan di Jakarta
pada tanggal 26 Februari 2019
PENJELASAN
ATAS
PERATURAN OTORITAS JASA KEUANGAN
I. UMUM
Peraturan ini merupakan penyempurnaan.
II. PASAL DEMI PASAL
Pasal 1
Cukup jelas.
Pasal 2
Ayat (1)
Cukup jelas.
Ayat (2)
Akad investasi.
Pasal 3
Cukup jelas.
"""


def addresses(structure) -> list[str]:
    return [node.address for node in structure.nodes]


def node(structure, address):
    return next(n for n in structure.nodes if n.address == address)


def test_a_regulation_parses_into_its_preamble_body_and_elucidation():
    structure = parse(POJK, "peraturan")

    assert addresses(structure) == [
        "menimbang", "mengingat", "memutuskan",
        "bab-i", "pasal-1",
        "bab-ii", "bab-ii/bagian-kesatu", "pasal-2", "pasal-2/ayat-1", "pasal-2/ayat-2", "pasal-3",
        "pengesahan",
        "penjelasan", "penjelasan/umum",
        "penjelasan/pasal-1", "penjelasan/pasal-2", "penjelasan/pasal-2/ayat-1", "penjelasan/pasal-2/ayat-2",
        "penjelasan/pasal-3",
    ]  # fmt: skip
    assert structure.problems == []


def test_each_node_knows_its_parent_heading_and_span():
    structure = parse(POJK, "peraturan")

    bab = node(structure, "bab-ii")
    assert (bab.kind, bab.label, bab.heading) == ("bab", "BAB II", "KEGIATAN USAHA")
    assert node(structure, "bab-ii/bagian-kesatu").heading == "Jenis Kegiatan"
    pasal = node(structure, "pasal-2")
    assert (pasal.parent, pasal.kind, pasal.label) == ("bab-ii/bagian-kesatu", "pasal", "Pasal 2")
    assert POJK[pasal.char_start : pasal.char_end].startswith("Pasal 2\n(1) Pembiayaan Jual Beli")
    assert POJK[pasal.char_start : pasal.char_end].rstrip().endswith("Pasal 3 . . .")
    ayat = node(structure, "pasal-2/ayat-1")
    assert (ayat.parent, ayat.label) == ("pasal-2", "(1)")
    assert (
        POJK[ayat.char_start : ayat.char_end]
        == "(1) Pembiayaan Jual Beli sebagaimana dimaksud dalam\nPasal 1 dilakukan dengan akad.\n"
    )


def test_a_reference_wrapped_onto_its_own_line_is_not_a_heading():
    """ "…dimaksud pada ayat\\n(1) dilakukan" and "dimaksud dalam\\nPasal 1 dilakukan" stay text."""
    structure = parse(POJK, "peraturan")

    assert "pasal-2/ayat-1" in addresses(structure)
    assert addresses(structure).count("pasal-1") == 1


def test_the_signature_block_ends_the_last_article():
    structure = parse(POJK, "peraturan")

    assert "Ditetapkan" not in POJK[node(structure, "pasal-3").char_start : node(structure, "pasal-3").char_end]


PAGED = """\
<!-- page 1 -->
- 1 -
PERATURAN BANK INDONESIA
NOMOR 23/6/PBI/2021
BAB I
KETENTUAN UMUM
Pasal 1
Dalam Peraturan Bank Indonesia ini yang dimaksud dengan:

<!-- page 2 -->
- 2 -
Pasal 2
(1)
Penyedia jasa pembayaran.
(2)
Penyelenggara infrastruktur.
"""


def test_page_numbers_come_from_the_page_markers():
    structure = parse(PAGED, "peraturan")

    assert (node(structure, "pasal-1").page_start, node(structure, "pasal-1").page_end) == (1, 1)
    assert (node(structure, "pasal-2").page_start, node(structure, "pasal-2/ayat-2").page_end) == (2, 2)
    assert node(structure, "bab-i").page_end == 2


AMENDING = """\
Pasal I
Beberapa ketentuan dalam Peraturan Otoritas Jasa Keuangan Nomor 35/POJK.05/2018 diubah sebagai berikut:
1. Ketentuan Pasal 115 diubah sehingga berbunyi sebagai berikut:
Pasal 115
(1) Perusahaan wajib melapor.
(2) Laporan disampaikan.
2. Pasal 30 dihapus.
Pasal II
Peraturan ini mulai berlaku pada tanggal diundangkan.
"""


def test_articles_quoted_in_an_amending_regulation_nest_under_its_roman_article():
    structure = parse(AMENDING, "peraturan")

    assert addresses(structure) == [
        "pasal-i", "pasal-i/pasal-115", "pasal-i/pasal-115/ayat-1", "pasal-i/pasal-115/ayat-2", "pasal-ii",
    ]  # fmt: skip
    assert structure.problems == []


ANNEX = """\
Pasal 1
Ketentuan sebagaimana tercantum dalam Lampiran.
LAMPIRAN I
PERATURAN ANGGOTA DEWAN KOMISIONER
DAFTAR ISI
BAB I PENDAHULUAN ........................ 3
BAB II TATA KELOLA ....................... 7
BAB I
PENDAHULUAN
Latar belakang.
LAMPIRAN I
BAB II
TATA KELOLA
Bank wajib.
LAMPIRAN II
FORMULIR
"""


def test_annexes_have_their_own_chapters_and_a_table_of_contents_is_skipped():
    structure = parse(ANNEX, "peraturan")

    assert addresses(structure) == ["pasal-1", "lampiran-i", "lampiran-i/bab-i", "lampiran-i/bab-ii", "lampiran-ii"]
    assert node(structure, "lampiran-i/bab-ii").heading == "TATA KELOLA"


def test_missing_articles_and_paragraphs_are_reported():
    gappy = "Pasal 1\n(1) Satu.\n(3) Tiga.\nPasal 2\nDua.\nPasal 4\nEmpat.\n"

    problems = parse(gappy, "peraturan").problems

    assert "pasal-1: ayat (2) missing" in problems
    assert "Pasal 3 missing" in problems


def test_an_elucidation_of_an_article_the_body_lacks_is_reported():
    problems = parse(
        "Pasal 1\nSatu.\nPENJELASAN\nII. PASAL DEMI PASAL\nPasal 1\nCukup jelas.\nPasal 2\nX.\n", "peraturan"
    )

    assert problems.problems == ["penjelasan/pasal-2 explains an article the body lacks"]


def test_a_regulation_without_any_article_is_reported():
    assert parse("PERATURAN\nTENTANG SESUATU\nIsi tanpa pasal.\n", "peraturan").problems == ["no Pasal found"]


CIRCULAR = """\
SURAT EDARAN OTORITAS JASA KEUANGAN
NOMOR 1/SEOJK.04/2020
I. KETENTUAN UMUM
1. Dalam Surat Edaran ini yang dimaksud dengan:
II.
PENGGUNAAN S-INVEST
A. Penyampaian surat.
III. PENUTUP
Ketentuan berlaku.
LAMPIRAN
FORMULIR
"""


def test_a_circular_parses_into_roman_sections():
    structure = parse(CIRCULAR, "surat_edaran")

    assert addresses(structure) == ["romawi-i", "romawi-ii", "romawi-iii", "lampiran"]
    assert node(structure, "romawi-ii").heading == "PENGGUNAAN S-INVEST"
    assert node(structure, "romawi-i").heading == "KETENTUAN UMUM"
    assert structure.problems == []


FATWA = """\
FATWA DEWAN SYARIAH NASIONAL
NO: 117/DSN-MUI/II/2018
Menimbang : a. bahwa layanan pembiayaan;
Mengingat : 1. Firman Allah SWT;
MEMUTUSKAN
Menetapkan : FATWA TENTANG LAYANAN PEMBIAYAAN
Pertama : Ketentuan Umum
Dalam fatwa ini yang dimaksud dengan:
Kedua : Ketentuan Hukum
Layanan pembiayaan boleh dilakukan.
Ketiga : Ketentuan Penutup
Fatwa ini berlaku.
"""


def test_a_fatwa_parses_into_its_numbered_rulings():
    structure = parse(FATWA, "fatwa")

    assert addresses(structure) == [
        "menimbang", "mengingat", "memutuskan", "diktum-pertama", "diktum-kedua", "diktum-ketiga",
    ]  # fmt: skip
    assert node(structure, "diktum-kedua").heading == "Ketentuan Hukum"


def test_the_grammar_follows_the_kind_of_instrument():
    assert grammar_for("ojk", "pojk") == "peraturan"
    assert grammar_for("bi", "padg") == "peraturan"
    assert grammar_for("id", "uu") == "peraturan"
    assert grammar_for("ojk", "seojk") == "surat_edaran"
    assert grammar_for("bi", "sebi") == "surat_edaran"
    assert grammar_for("dsnmui", "fatwa") == "fatwa"


def test_a_paragraph_reference_wrapped_after_the_word_ayat_is_text():
    wrapped = """\
Pasal 12
(1) Penempatan sebagaimana dimaksud dalam Pasal 5 ayat
(3) huruf a harus memenuhi ketentuan.
(2) Penempatan berupa saham.
"""
    structure = parse(wrapped, "peraturan")

    assert addresses(structure) == ["pasal-12", "pasal-12/ayat-1", "pasal-12/ayat-2"]


def test_a_chapter_ends_the_article_before_it():
    structure = parse("Pasal 1\nSatu.\nBAB II\nLAIN\n(1) bukan ayat Pasal 1\nPasal 2\nDua.\n", "peraturan")

    assert addresses(structure) == ["pasal-1", "bab-ii", "pasal-2"]


def test_an_elucidation_published_as_its_own_file_is_still_an_elucidation():
    structure = parse(
        "PENJELASAN\nATAS\nPERATURAN BANK INDONESIA\nI. UMUM\nUmum.\nII. PASAL DEMI PASAL\nPasal 1\nCukup jelas.\n",
        "peraturan",
    )

    assert addresses(structure) == ["penjelasan", "penjelasan/umum", "penjelasan/pasal-1"]
    assert structure.problems == []  # the body is in the regulation's other file


def test_an_amending_article_whose_numeral_was_misread_as_1_is_still_the_amending_article():
    """Text extraction often reads "Pasal I" as "Pasal 1"; its first words say what it is."""
    misread = AMENDING.replace("Pasal I\n", "Pasal 1\n", 1)

    assert addresses(parse(misread, "peraturan"))[:2] == ["pasal-i", "pasal-i/pasal-115"]


def test_common_ocr_misreadings_of_headings_are_tolerated_but_catchwords_are_not():
    ocr = "Pasal1\n(l) Satu.\n(2) Dua.\nPasa2\ndimaksud dalam\nPasal 3.\nPasal 3...\nPasal 3\nTiga.\n"

    assert addresses(parse(ocr, "peraturan")) == ["pasal-1", "pasal-1/ayat-1", "pasal-1/ayat-2", "pasal-2", "pasal-3"]


def test_the_next_amending_instruction_ends_the_article_quoted_before_it():
    structure = parse(AMENDING, "peraturan")

    quoted = node(structure, "pasal-i/pasal-115")
    assert "Pasal 30 dihapus" not in AMENDING[quoted.char_start : quoted.char_end]
    assert "Pasal 30 dihapus" in AMENDING[node(structure, "pasal-i").char_start : node(structure, "pasal-i").char_end]
