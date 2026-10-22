"""Which tier and OCR mode a file is read with."""

from __future__ import annotations

from collections.abc import Sequence

from metamorph_pdf_text.application.reading import OcrMode, ReadRequest, Tier
from metamorph_pdf_text.domain.quality import PageQuality

MAIN = "main"  # the regulation itself (contract v2's file role); annexes, FAQs and guides are the rest
FORCED_OCR_SHARE = 0.2  # of the text layer's pages noisy, above which the layer is not trusted


def request_for(role: str, text_layer: Sequence[PageQuality]) -> ReadRequest:
    """The regulation gets the vision model, the rest the small models. OCR is forced when the PDF's own text is
    noisy: a publisher's OCR layer over a scan, which a reader's own check can take for born-digital text."""
    tier = Tier.STANDARD if role == MAIN else Tier.BASIC
    noisy = sum(page.is_noisy for page in text_layer)
    untrusted = bool(text_layer) and noisy / len(text_layer) > FORCED_OCR_SHARE
    return ReadRequest(tier, OcrMode.OCR if untrusted else OcrMode.AUTO)
