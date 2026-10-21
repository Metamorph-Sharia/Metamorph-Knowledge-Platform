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


# Headings a reader set on one line (MinerU's title block for a centred heading stack)


def test_a_chapter_and_its_first_article_read_as_one_line_are_set_apart() -> None:
    # UU 24/1999
    assert rendered(block("BAB I KETENTUAN UMUM Pasal 1", kind=BlockKind.TITLE)) == "BAB I KETENTUAN UMUM\nPasal 1"


def test_a_part_or_section_stands_alone_above_its_name() -> None:
    # Perka PPATK 2012, PERMA 2/2015: the parser reads "Paragraf 1" and "Bagian Keempat" only on lines of their own
    assert rendered(block("Paragraf 1 Umum Pasal 2")) == "Paragraf 1\nUmum\nPasal 2"
    assert rendered(block("Bagian Keempat Pemeriksaan Pendahuluan", kind=BlockKind.TITLE)) == (
        "Bagian Keempat\nPemeriksaan Pendahuluan"
    )


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
