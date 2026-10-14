from metamorph_contract import join_pages, page_marker, split_pages


def test_pages_survive_a_round_trip() -> None:
    pages = ["SALINAN\nPERATURAN BANK INDONESIA", "Pasal 1\n...", "LAMPIRAN"]

    assert split_pages(join_pages(pages)) == [(1, pages[0]), (2, pages[1]), (3, pages[2])]


def test_markers_are_html_comments_on_their_own_line() -> None:
    assert page_marker(12) == "<!-- page 12 -->"
    assert join_pages(["a", "b"]) == "<!-- page 1 -->\na\n\n<!-- page 2 -->\nb"


def test_text_before_the_first_marker_is_not_a_page() -> None:
    assert split_pages("preamble\n<!-- page 1 -->\nbody") == [(1, "body")]
