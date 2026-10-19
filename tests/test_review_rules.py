"""When an open citation item no longer needs a person: the cause it was opened for is gone."""

from __future__ import annotations

from metamorph_platform.domain.reviews import citation_settlement

CITING = "ojk:pojk:2017:40"


def test_a_citation_item_is_settled_once_no_unlinked_citation_with_that_text_remains():
    assert citation_settlement(still_unlinked=True, named=(), citing=CITING) is None
    assert "linked" in citation_settlement(still_unlinked=False, named=(), citing=CITING)


def test_a_citation_item_is_settled_once_its_text_is_read_as_naming_a_document():
    """It was queued because nothing named the target; once the text is read as naming one, the citation
    links as soon as that document is loaded, like any other."""
    reason = citation_settlement(still_unlinked=True, named=("ojk:pojk:2013:3",), citing=CITING)

    assert "names" in reason and "loaded" in reason


def test_a_citation_item_naming_the_citing_document_itself_is_settled():
    """JDIH OJK lists some circulars among their own legal bases: there is nothing to link."""
    reason = citation_settlement(still_unlinked=True, named=(CITING,), citing=CITING)

    assert "itself" in reason
