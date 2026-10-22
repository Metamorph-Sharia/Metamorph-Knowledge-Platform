from metamorph_pdf_text import BBox, BlockKind, render
from pdf_text_pages import block, page


def rendered(*blocks) -> str:
    return render([page(1, *blocks)])[0]


def test_a_block_is_one_paragraph_and_blocks_are_set_apart() -> None:
    text = rendered(block("Bank Indonesia berwenang menetapkan\nkebijakan moneter."), block("Pasal 3"))

    assert text == "Bank Indonesia berwenang menetapkan kebijakan moneter.\n\nPasal 3"


def test_a_heading_keeps_its_line_and_the_wording_after_it_starts_one() -> None:
    text = rendered(block("Pasal 5\nSetiap Pelaku Usaha wajib\nmemiliki izin."))

    assert text == "Pasal 5\nSetiap Pelaku Usaha wajib memiliki izin."


def test_each_item_opens_a_line() -> None:
    text = rendered(
        block("Menimbang :\na. bahwa untuk melaksanakan\nketentuan Pasal 5;\nb. bahwa berdasarkan\npertimbangan;")
    )

    assert text == "Menimbang :\na. bahwa untuk melaksanakan ketentuan Pasal 5;\nb. bahwa berdasarkan pertimbangan;"


def test_paragraphs_of_an_article_open_lines() -> None:
    text = rendered(block("(1) Setiap Orang wajib\nmendaftar.\n(2) Ketentuan lebih\nlanjut diatur."))

    assert text == "(1) Setiap Orang wajib mendaftar.\n(2) Ketentuan lebih lanjut diatur."


def test_a_number_running_on_from_the_line_before_does_not_open_one() -> None:
    text = rendered(block("dikenai denda paling banyak Rp\n1.000.000.000,00 (satu miliar rupiah)."))

    assert text == "dikenai denda paling banyak Rp 1.000.000.000,00 (satu miliar rupiah)."


def test_a_title_keeps_its_lines() -> None:
    text = rendered(block("BAB I\nKETENTUAN UMUM", kind=BlockKind.TITLE), block("Pasal 1"))

    assert text == "BAB I\nKETENTUAN UMUM\n\nPasal 1"


def test_headings_read_onto_one_line_stay_as_read_for_the_parser_to_cut() -> None:
    # The platform's domain/structure/run_together.py cuts them, knowing the article numbering (plan step 13)
    assert rendered(block("BAB I KETENTUAN UMUM Pasal 1", kind=BlockKind.TITLE)) == "BAB I KETENTUAN UMUM Pasal 1"
    assert rendered(block("Pasal 8 Ayat (1) Huruf a Cukup jelas.")) == "Pasal 8 Ayat (1) Huruf a Cukup jelas."


def test_articles_cited_in_a_list_a_line_ends_in_stay_wording() -> None:
    # PP 82/2012's Menimbang, as the text layer wraps it: the line starts with one article cited, ends with another
    lines = "Pasal 11 ayat (2), Pasal 13 ayat (6), Pasal 16 ayat (2), Pasal 17\nayat (3), dan Pasal 24 ayat (4)"

    assert rendered(block(lines)) == lines.replace("\n", " ")


def test_an_article_cited_on_a_wrapped_line_stays_wording() -> None:
    # PERMA 1/2016's Menimbang: "Pasal 154 Reglemen …" names the article of another law
    lines = "c. bahwa ketentuan hukum acara perdata yang berlaku,\nPasal 154 Reglemen Hukum Acara untuk Daerah Luar"

    assert rendered(block(lines)) == lines.replace("\n", " ")


def test_a_sentence_opening_with_an_article_it_amends_or_cites_stays_one_line() -> None:
    for sentence in (
        "Pasal 5 Undang-Undang Nomor 10 Tahun 1998 diubah sehingga berbunyi",
        "Pasal 5 UU Perbankan tetap berlaku.",
        "Pasal 5 Ayat (1), Pasal 21 Ayat (1), Pasal 27, dan Pasal 33 Undang-Undang Dasar 1945;",  # UU 8/1999, Mengingat
        "dimaksud pada ayat (1) huruf a. Ayat ini berlaku bagi Bank.",
    ):
        assert rendered(block(sentence)) == sentence


# A list marker a reader read as a block of its own, in a column apart


def test_a_lone_marker_joins_the_paragraph_level_with_it_wherever_it_was_read() -> None:
    # POJK 37/2019, page 15: "(4)" read before the end of ayat (2), its paragraph read after ayat (3)
    marker = block("(4)", BBox(0.12, 0.40, 0.15, 0.415), BlockKind.ASIDE)
    end_of_two = block("Bank sebagaimana dimaksud pada ayat (1) huruf a.", BBox(0.16, 0.10, 0.88, 0.14))
    three = block("(3) Bank wajib memelihara pengumuman.", BBox(0.12, 0.20, 0.88, 0.30))
    four = block("Tata cara dan batas waktu penyampaian.", BBox(0.165, 0.4005, 0.88, 0.45))

    text = rendered(marker, end_of_two, three, four)

    assert text == (
        "Bank sebagaimana dimaksud pada ayat (1) huruf a.\n\n(3) Bank wajib memelihara pengumuman.\n\n"
        "(4) Tata cara dan batas waktu penyampaian."
    )


def test_a_lone_marker_with_nothing_level_with_it_stays_where_it_was_read() -> None:
    marker = block("(4)", BBox(0.12, 0.40, 0.15, 0.415))
    text = rendered(marker, block("Tata cara dan batas waktu.", BBox(0.16, 0.50, 0.88, 0.55)))

    assert text == "(4)\n\nTata cara dan batas waktu."


def test_an_article_cited_in_a_sentence_is_not_a_heading() -> None:
    sentence = "Pasal 5 diubah dan Pasal 6 dihapus sehingga berbunyi"

    assert rendered(block(sentence)) == sentence


def test_the_decision_label_stands_alone() -> None:
    text = rendered(block("MEMUTUSKAN:\nMenetapkan : PERATURAN BANK INDONESIA\nTENTANG SISTEM PEMBAYARAN."))

    assert text == "MEMUTUSKAN:\nMenetapkan : PERATURAN BANK INDONESIA TENTANG SISTEM PEMBAYARAN."


def test_a_table_is_a_row_to_a_line() -> None:
    text = rendered(block("No.\tBidang Usaha\tKBLI\n21\tAngkutan penyeberangan perintis\t50217", kind=BlockKind.TABLE))

    assert text == "No. | Bidang Usaha | KBLI\n21 | Angkutan penyeberangan perintis | 50217"


def test_images_and_formulas_are_left_out_and_footnotes_kept() -> None:
    text = rendered(
        block("", kind=BlockKind.IMAGE),
        block("x^2", kind=BlockKind.FORMULA),
        block("Pasal 2"),
        block("1) Lembaran Negara Tahun 2011", kind=BlockKind.FOOTNOTE),
    )

    assert text == "Pasal 2\n\n1) Lembaran Negara Tahun 2011"


def test_the_readers_order_is_kept_on_a_two_column_page() -> None:
    left, right = BBox(50, 100, 290, 800), BBox(305, 100, 545, 800)

    text = rendered(block("Kolom kiri\nberlanjut.", left), block("Kolom kanan.", right))

    assert text == "Kolom kiri berlanjut.\n\nKolom kanan."


def test_each_page_is_rendered_apart() -> None:
    assert render([page(1, block("Pasal 1")), page(2), page(3, block("Pasal 2"))]) == ["Pasal 1", "", "Pasal 2"]
