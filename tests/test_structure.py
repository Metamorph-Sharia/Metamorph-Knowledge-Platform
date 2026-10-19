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


def articles(text: str) -> list[str]:
    return [n.address for n in parse(text, "peraturan").nodes if n.kind == "pasal"]


def test_a_heading_whose_l_was_read_as_a_digit_is_the_next_article_not_a_far_one():
    """OCR of "Pasal 36" with the space lost reads "Pasa136"; taken as 136, it hid Pasal 37-135 (PMK 81/2024)."""
    misread = "Pasal 35\nLima.\nPasa136\nEnam.\nPasal 37\nTujuh.\n"

    assert articles(misread) == ["pasal-35", "pasal-36", "pasal-37"]
    assert "Pasal 100 missing" not in parse(misread, "peraturan").problems


def test_the_l_may_be_read_as_7_too():
    assert articles("Pasal 21\nSatu.\nPasa722\nDua.\nPasal 23\nTiga.\n") == ["pasal-21", "pasal-22", "pasal-23"]


def test_a_heading_whose_l_was_dropped_keeps_its_whole_number():
    assert articles("Pasal 121\nSatu.\nPasa122\nDua.\n") == ["pasal-121", "pasal-122"]


def test_digits_misread_as_letters_in_a_heading_are_read_as_digits():
    damaged = "Pasal 9\nA.\nPasal 1O\nB.\nPasal 1 1\nC.\nPasal 12\nD.\n"

    assert articles(damaged) == ["pasal-9", "pasal-10", "pasal-11", "pasal-12"]


def test_an_article_far_ahead_of_the_last_is_not_the_next_one():
    """An omnibus law quotes the articles it amends ("Pasal 228"); taken as its own, every later real article
    was refused for being lower (UU 11/2020: 1,546 problems)."""
    quoting = "Pasal 1\nSatu.\nPasal 2\nDua.\nPasal 228\nDikutip.\nPasal 3\nTiga.\n"

    assert articles(quoting) == ["pasal-1", "pasal-2", "pasal-3"]
    assert parse(quoting, "peraturan").problems == []


def test_a_short_run_of_lost_headings_is_still_a_gap():
    assert "Pasal 3 missing" in parse("Pasal 1\nA.\nPasal 2\nB.\nPasal 9\nC.\n", "peraturan").problems


def paragraphs(text: str) -> list[str]:
    return [n.address for n in parse(text, "peraturan").nodes if n.kind == "ayat"]


def test_ocr_damaged_paragraph_markers_are_read_as_the_next_paragraph():
    """BPK's scanned laws: "(I)" and "( 1)" for (1), "{2)" for (2), "(21" for (2): the bracket read as 1,
    and "l5l" for (5) in the KUHP: both brackets read as l."""
    damaged = "Pasal 4\n(I) Data Pribadi.\n{2) Data umum.\n( 3) Data spesifik.\n(41 Data lain.\nl5l Data baru.\n"

    assert paragraphs(damaged) == [
        "pasal-4/ayat-1", "pasal-4/ayat-2", "pasal-4/ayat-3", "pasal-4/ayat-4", "pasal-4/ayat-5",
    ]  # fmt: skip


def test_a_number_misread_with_an_l_at_the_start_of_a_line_is_not_a_paragraph():
    """ "l9 ayat (1)" is a wrapped "Pasal 19 ayat (1)", OCR'd: only "l9l" or "l9)" has both brackets."""
    assert paragraphs("Pasal 4\n(1) Satu, dimaksud dalam Pasal\nl9 ayat (1) dan\n(2) Dua.\n") == [
        "pasal-4/ayat-1", "pasal-4/ayat-2",
    ]  # fmt: skip


def test_a_two_digit_paragraph_missing_its_bracket_keeps_both_digits_when_that_is_next():
    numbered = "Pasal 4\n" + "".join(f"({n}) Isi.\n" for n in range(1, 21)) + "(21 Isi.\n"

    assert paragraphs(numbered)[-1] == "pasal-4/ayat-21"


def sections(text: str) -> list[str]:
    return [n.address for n in parse(text, "surat_edaran").nodes if n.kind == "romawi"]


def test_a_catchword_at_the_foot_of_a_page_is_not_a_section():
    """ "X. PENUTUP . . ." previews the next page; taken as section X it hid section IX (SEBI 22/2012)."""
    paged = "I. UMUM\nA.\nII. LAIN\nB.\nIV. PENUTUP . . .\nIII. LAGI\nC.\nIV. PENUTUP\nD.\n"

    assert sections(paged) == ["romawi-i", "romawi-ii", "romawi-iii", "romawi-iv"]
    assert parse(paged, "surat_edaran").problems == []


def test_a_reference_to_a_section_wrapped_onto_its_own_line_is_not_a_section():
    """ "… mengacu pada Lampiran\\nIX.2." opened section IX and hid III to VIII (SEOJK 52/2016)."""
    wrapped = "I. UMUM\nmengacu pada Lampiran\nIX.2.\nsebagaimana butir\nIII.D.\nII. LAIN\nB.\nIII. PENUTUP\nC.\n"

    assert sections(wrapped) == ["romawi-i", "romawi-ii", "romawi-iii"]


def test_a_mixed_case_or_bare_section_heading_counts_when_it_is_the_next_section():
    mixed = "I. KETENTUAN UMUM\nA.\nII. Spesifikasi Tanda Pengenal\nB.\nV.\nTeks.\nIII.\nSANKSI\nC.\n"

    assert sections(mixed) == ["romawi-i", "romawi-ii", "romawi-iii"]


def test_a_capitalised_section_far_ahead_is_a_quoted_one():
    assert sections("I. UMUM\nA.\nX. PENGEMBANGAN\nB.\nII. LAIN\nC.\n") == ["romawi-i", "romawi-ii"]


def test_an_older_law_ends_its_article_headings_with_a_full_stop():
    """UU 6/1968 writes "Pasal 1.", after a sentence or a chapter's title; a wrapped reference ("… dalam\\nPasal 4.")
    still isn't a heading."""
    old = (
        "BAB I.\nPENGERTIAN.\nPasal 1.\n(1) Yang dimaksud.\nPasal 2.\nDua.\nBAB II.\nIZIN USAHA\nPasal 3.\n"
        "Tiga sebagaimana dimaksud dalam\nPasal 4.\nPasal 4.\nEmpat.\n"
    )

    assert articles(old) == ["pasal-1", "pasal-2", "pasal-3", "pasal-4"]
    assert node(parse(old, "peraturan"), "pasal-4").char_start == old.rindex("Pasal 4.")


PARTIAL_AMENDMENT = """\
Pasal I
Beberapa ketentuan dalam Peraturan Bank Indonesia Nomor 7/33/PBI/2005 diubah sebagai berikut:
1. Ketentuan Pasal 2 ayat (4) diubah sehingga berbunyi sebagai berikut:
Pasal 2
(4) Maksimum suku bunga ditetapkan.
{paragraphs}
Pasal II
Peraturan ini mulai berlaku.
"""


def test_an_amendment_quoting_only_the_paragraphs_it_changes_is_not_missing_the_others():
    """PBI 11/2005 quotes Pasal 2 from ayat (4): (1) to (3) are unchanged, not lost."""
    structure = parse(PARTIAL_AMENDMENT.format(paragraphs="(5) Lain."), "peraturan")

    assert structure.problems == []


def test_a_gap_within_the_quoted_paragraphs_is_still_reported():
    structure = parse(PARTIAL_AMENDMENT.format(paragraphs="(6) Lain."), "peraturan")

    assert structure.problems == ["pasal-i/pasal-2: ayat (5) missing"]


def test_a_paragraph_catchword_at_the_foot_of_a_page_is_not_the_paragraph():
    """ "(7) Sidang . . ." previews the next page; taken as (7), the real "(71 Sidang" became (71) (UU 4/2026)."""
    paged = "Pasal 101B\n(6) Enam.\n(7) Sidang . . .\n(71 Sidang pemeriksaan.\n(8) Putusan.\n"

    assert paragraphs(paged) == ["pasal-101b/ayat-6", "pasal-101b/ayat-7", "pasal-101b/ayat-8"]
    assert node(parse(paged, "peraturan"), "pasal-101b/ayat-7").char_start == paged.index("(71")


def test_a_paragraph_far_ahead_of_the_last_is_a_misread_one():
    assert paragraphs("Pasal 20\n(1) Satu.\n(2) Dua.\n(3) Tiga.\n(29) Dua puluh sembilan.\n(4) Empat.\n") == [
        "pasal-20/ayat-1", "pasal-20/ayat-2", "pasal-20/ayat-3", "pasal-20/ayat-4",
    ]  # fmt: skip


AMENDING_BODY = """\
Menimbang : a. bahwa beberapa ketentuan dalam
Peraturan Otoritas Jasa Keuangan Nomor 69/POJK.05/2016 perlu diubah;
MEMUTUSKAN:
Menetapkan : PERATURAN OTORITAS JASA KEUANGAN TENTANG PERUBAHAN.
{heading}Beberapa ketentuan dalam Peraturan Otoritas Jasa Keuangan Nomor 69/POJK.05/2016 diubah sebagai berikut:
1. Ketentuan Pasal 1 diubah sehingga berbunyi sebagai berikut:
Pasal 1
Dalam Peraturan ini yang dimaksud dengan:
2. Ketentuan Pasal 3A diubah sehingga berbunyi sebagai berikut:
Pasal 3A
(1) Perusahaan wajib.
Pasal II
Peraturan ini mulai berlaku.
"""


def test_an_amendment_whose_pasal_i_heading_was_lost_is_still_the_amending_article():
    """POJK 36/2024 (no heading in OJK's text), PBI 19/2015 ("Pasal" / "I" on two lines) and PBI 50/2005
    ("Pasal I Passa"): the quoted Pasal 1 and Pasal 3A became the body, and Pasal 2 went missing."""
    for heading in ("", "Pasal\nI\n", "Pasal I Passa\n"):
        structure = parse(AMENDING_BODY.format(heading=heading), "peraturan")

        assert articles(AMENDING_BODY.format(heading=heading)) == [
            "pasal-i", "pasal-i/pasal-1", "pasal-i/pasal-3a", "pasal-ii",
        ], heading  # fmt: skip
        assert structure.problems == [], heading


def test_considerations_that_mention_amending_some_provisions_are_not_an_amendment():
    text = "Menimbang : a. bahwa\nBeberapa ketentuan dalam Peraturan perlu diubah;\nMEMUTUSKAN:\nPasal 1\nSatu.\n"

    assert articles(text) == ["pasal-1"]


AMENDING_CIRCULAR = """\
SURAT EDARAN OTORITAS JASA KEUANGAN
NOMOR 9/SEOJK.04/2023
I. Beberapa ketentuan dalam Surat Edaran Otoritas Jasa Keuangan Nomor 17/SEOJK.04/2016 tentang Tata Kelola
Manajer Investasi diubah sebagai berikut:
1. Ketentuan angka III angka 2 diubah, sehingga angka III berbunyi
sebagai berikut:
III. LAPORAN PENERAPAN TATA KELOLA
1. Manajer Investasi wajib menyusun laporan.
IV. TRANSPARANSI
Laporan dipublikasikan.
2. Ketentuan angka VII angka 1 diubah sehingga berbunyi sebagai berikut:
VII. TATA CARA PENYAMPAIAN LAPORAN
Laporan disampaikan secara daring.
II. Manajer Investasi Syariah wajib menyesuaikan diri.
III. Ketentuan dalam Surat Edaran Otoritas Jasa Keuangan ini mulai berlaku pada tanggal ditetapkan.
"""

INSTRUCTIONS_ONLY_CIRCULAR = """\
Sehubungan dengan perubahan ketentuan lelang, Surat Edaran Bank Indonesia Nomor 6/9/DPM diubah sebagai berikut:
1. Ketentuan BAB I angka 5 dihapus dan ditambah 1 (satu) angka baru, yakni
angka 6 sehingga berbunyi sebagai berikut:
I.
KETENTUAN UMUM
6. Lelang dilakukan secara elektronik.
2. Ketentuan BAB VII diubah, sehingga berbunyi sebagai berikut:
VII. SANKSI
Bank dikenakan sanksi.
Ketentuan dalam Surat Edaran ini mulai berlaku pada tanggal ditetapkan.
"""


def test_sections_an_amending_circular_quotes_are_text_of_its_own_sections():
    """SEOJK 9/2023 quotes sections III, IV and VII of the circular it amends; they hid its own section II."""
    structure = parse(AMENDING_CIRCULAR, "surat_edaran")

    assert sections(AMENDING_CIRCULAR) == ["romawi-i", "romawi-ii", "romawi-iii"]
    amending_section = node(structure, "romawi-i")
    assert "LAPORAN PENERAPAN" in AMENDING_CIRCULAR[amending_section.char_start : amending_section.char_end]
    assert structure.problems == []


def test_a_circular_made_only_of_amending_instructions_has_no_sections_of_its_own():
    """SEBI 28/2008: every section heading in it is one it quotes."""
    structure = parse(INSTRUCTIONS_ONLY_CIRCULAR, "surat_edaran")

    assert sections(INSTRUCTIONS_ONLY_CIRCULAR) == []
    assert structure.problems == []


def test_a_circular_that_introduces_its_first_section_with_a_colon_is_not_an_amendment():
    text = "Ketentuan ditetapkan sebagai berikut:\nI. KETENTUAN UMUM\nA.\nII. PENUTUP\nB.\n"

    assert sections(text) == ["romawi-i", "romawi-ii"]


OMNIBUS = """\
MEMUTUSKAN:
Menetapkan : UNDANG-UNDANG TENTANG CIPTA KERJA.
BAB I
KETENTUAN UMUM
Pasal 1
Dalam Undang-Undang ini yang dimaksud dengan:
BAB II
PENINGKATAN EKOSISTEM INVESTASI
Pasal 2
Beberapa ketentuan dalam Undang-Undang Nomor 26 Tahun 2007 tentang Penataan Ruang diubah sebagai berikut:
1. Ketentuan Pasal 3 diubah sehingga berbunyi sebagai berikut:
Pasal 3
Penataan ruang bertujuan.
2. Ketentuan Pasal 6 diubah sehingga berbunyi sebagai berikut:
Pasal 6
(1) Penataan ruang diselenggarakan.
Pasal 7
(1) Negara menyelenggarakan.
Pasal 3
Beberapa ketentuan dalam Undang-Undang Nomor 27 Tahun 2007 diubah sebagai berikut:
1. Ketentuan Pasal 228 diubah sehingga berbunyi sebagai berikut:
Pasal 228
Dikutip.
Pasal 4
Undang-Undang ini mulai berlaku pada tanggal diundangkan.
"""


def test_an_omnibus_law_nests_the_articles_it_quotes_under_its_own_amending_articles():
    """Cipta Kerja (UU 11/2020): each of its articles amends another law and quotes that law's articles.
    The quoted "Pasal 3" comes right after "berbunyi sebagai berikut:", so it isn't the law's own Pasal 3."""
    structure = parse(OMNIBUS, "peraturan")

    assert articles(OMNIBUS) == [
        "pasal-1", "pasal-2", "pasal-2/pasal-3", "pasal-2/pasal-6", "pasal-2/pasal-7",
        "pasal-3", "pasal-3/pasal-228", "pasal-4",
    ]  # fmt: skip
    assert structure.problems == []


def test_an_ordinary_article_that_cites_beberapa_ketentuan_later_is_not_an_amending_one():
    text = "Pasal 1\nSatu.\nPasal 2\nDiatur.\nBeberapa ketentuan dalam Undang-Undang ini diubah.\nPasal 3\nTiga.\n"

    assert articles(text) == ["pasal-1", "pasal-2", "pasal-3"]


def test_an_article_quoted_after_a_scrambled_instruction_is_still_quoted():
    """Cipta Kerja's OCR scrambles "10. Ketentuan Pasal 18 diubah sehingga berbunyi sebagai berikut:" over
    three lines; the quoted Pasal 18 that follows was taken as the law's own next article."""
    scrambled = OMNIBUS.replace(
        "Pasal 4\nUndang-Undang ini",
        "2. Ketentuan Pasal\nberikut:\n4 diubah sehingga berbunyi sebagai\n"
        "Pasal 4\nDikutip.\nPasal 4\nUndang-Undang ini",
    )

    assert articles(scrambled)[-3:] == ["pasal-3/pasal-228", "pasal-3/pasal-4", "pasal-4"]


def test_an_instruction_that_deletes_an_article_quotes_nothing():
    deleting = OMNIBUS.replace("Pasal 4\nUndang-Undang ini", "2. Pasal 30 dihapus.\nPasal 4\nUndang-Undang ini")

    assert articles(deleting)[-2:] == ["pasal-3/pasal-228", "pasal-4"]


def test_an_omnibus_article_that_opens_an_amendment_is_its_own_even_after_a_lost_heading():
    """OCR lost one of the law's own article headings; without its number to wait for, every later article
    was taken as quoted. An article whose first words amend another law is always the law's own."""
    lost = OMNIBUS.replace("Pasal 3\nBeberapa ketentuan", "Beberapa ketentuan")
    lost = lost.replace(
        "Pasal 4\nUndang-Undang ini",
        "Pasal 4\nBeberapa ketentuan dalam Undang-Undang Nomor 28 Tahun 2007 diubah sebagai berikut:\n"
        "1. Ketentuan Pasal 10 diubah sehingga berbunyi sebagai berikut:\nPasal 10\nDikutip.\n"
        "Pasal 5\nUndang-Undang ini",
    )

    assert [a for a in articles(lost) if "/" not in a] == ["pasal-1", "pasal-2", "pasal-4", "pasal-5"]
    assert parse(lost, "peraturan").problems == ["Pasal 3 missing"]


def test_an_amendment_opening_article_far_ahead_stays_quoted():
    far = OMNIBUS.replace("Pasal 228\nDikutip.", "Pasal 228\nBeberapa ketentuan dalam Undang-Undang yang dikutip.")

    assert articles(far)[-2:] == ["pasal-3/pasal-228", "pasal-4"]


def test_an_article_quoted_after_an_instruction_ocr_scattered_is_still_quoted():
    """Cipta Kerja: "10. Ketentuan Pasal / berikut: / 18 diubah sehingga berbunyi sebagai / Pasal 18": with its
    number stranded and its colon elsewhere, the instruction is unreadable, but its words still say a quote follows."""
    stranded = OMNIBUS.replace(
        "Pasal 4\nUndang-Undang ini",
        "2\nKetentuan Pasal\nberikut:\n4 diubah sehingga berbunyi sebagai\nPasal 4\nDikutip.\n"
        "Pasal 4\nUndang-Undang ini",
    ).replace("1. Ketentuan Pasal 228", "Ketentuan Pasal 228")

    assert articles(stranded)[-3:] == ["pasal-3/pasal-228", "pasal-3/pasal-4", "pasal-4"]


def test_a_roman_heading_inside_an_omnibus_amending_article_is_a_quoted_one():
    """P2SK and Perppu 2/2022 quote "Pasal 1" OCR'd as "Pasal I"; opened as a Roman amending article, it
    swallowed every later article of the law, since only a "Pasal II" ends one."""
    misread = OMNIBUS.replace(
        "1. Ketentuan Pasal 3 diubah sehingga berbunyi sebagai berikut:\nPasal 3\n",
        "1. Ketentuan Pasal 1 diubah sehingga berbunyi sebagai berikut:\nPasal I\n",
    )

    assert articles(misread) == [
        "pasal-1", "pasal-2", "pasal-2/pasal-i", "pasal-2/pasal-6", "pasal-2/pasal-7",
        "pasal-3", "pasal-3/pasal-228", "pasal-4",
    ]  # fmt: skip


def test_a_presidential_letterhead_and_damaged_page_numbers_are_page_furniture_not_content():
    """BPK's PDFs repeat "PRESIDEN / REPUBLIK INDONESIA / - 212 -" at every page top, OCR'd as "REPUBL|K" and
    "-2t2-". Between "Pasal 7" and its first words, it hid that P2SK's article amends another law."""
    from metamorph_platform.domain.structure.text import lines

    page = "Pasal 7\nPRESIDEN\nREPUBL|K INDONESIA\n-2t2-\nBeberapa ketentuan dalam\nPRESIDEN REPUBLIK INDONESIA,\n"

    assert [line.text for line in lines(page)] == [
        "Pasal 7", "Beberapa ketentuan dalam", "PRESIDEN REPUBLIK INDONESIA,",
    ]  # fmt: skip


def test_an_omnibus_amending_article_is_recognised_across_a_page_break():
    paged = OMNIBUS.replace("Pasal 3\nBeberapa", "Pasal 3\nFRESIDEN\nREPUBLTK INDONESIA\n- 12 -\nBeberapa")

    assert "pasal-3/pasal-228" in articles(paged)


def test_a_heading_whose_every_digit_was_misread_is_still_read_when_it_cannot_be_roman():
    """P2SK's "Pasal lO" is Pasal 10; "Pasal II" is still an amending regulation's second article."""
    assert articles("Pasal 9\nA.\nPasal lO\nB.\n") == ["pasal-9", "pasal-10"]
    assert articles(AMENDING)[-1] == "pasal-ii"


def test_an_inserted_article_quoted_by_an_omnibus_law_is_never_its_own():
    """An omnibus law is new: its own articles carry no inserted letter. P2SK quoted "Pasal 10B" while its own
    Pasal 10 was next; taken as its own, it hid the rest of the law."""
    inserted = OMNIBUS.replace(
        "Pasal 7\n(1) Negara menyelenggarakan.\n",
        "Pasal 7\n(1) Negara menyelenggarakan.\nPasal 3A\nDisisipkan.\n",
    )

    assert "pasal-2/pasal-3a" in articles(inserted)
