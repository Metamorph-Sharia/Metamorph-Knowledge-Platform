"""Read every current main text the parser hasn't read yet: its provisions, the citations in it, its own dates.

A text is parsed again only when it changes (a new text version) or the parser does (PARSER_VERSION).
A text whose structure fails the quality checks is still stored, and queued for a person to look at.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from metamorph_platform.application.ports import BlobReader, ParsedText, ParsedTexts, ReviewQueue, TextToParse
from metamorph_platform.domain.citations import text_citations
from metamorph_platform.domain.dates import text_dates
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.reviews import MAX_PROBLEMS_SHOWN
from metamorph_platform.domain.structure import PARSER_VERSION, grammar_for, parse


@dataclass
class ParseReport:
    texts: int = 0
    provisions: int = 0
    citations: int = 0
    suspect: int = 0

    def counts(self) -> dict[str, int]:
        return asdict(self)


class ParseTexts:
    def __init__(self, texts: ParsedTexts, blobs: BlobReader, reviews: ReviewQueue) -> None:
        self.texts = texts
        self.blobs = blobs
        self.reviews = reviews

    def run(self, *, everything: bool = False) -> ParseReport:
        report = ParseReport()
        for text in self.texts.texts_to_parse(PARSER_VERSION, everything):
            parsed = self._parse(text)
            self.texts.save(parsed)
            report.texts += 1
            report.provisions += len(parsed.structure.nodes)
            report.citations += len(parsed.citations)
            if parsed.structure.problems:
                report.suspect += 1
                self._queue(text, parsed.structure.problems)
        return report

    def _parse(self, text: TextToParse) -> ParsedText:
        content = self.blobs.read(text.storage_key).decode("utf-8")
        structure = parse(content, grammar_for(text.issuer, text.family))
        return ParsedText(
            text=text,
            parser_version=PARSER_VERSION,
            structure=structure,
            citations=text_citations(content, structure, document_id=text.document_id),
            dates=text_dates(content),
        )

    def _queue(self, text: TextToParse, problems: list[str]) -> None:
        subject = {
            "document_id": text.document_id,
            "text_sha256": text.sha256,
            "problems": problems[:MAX_PROBLEMS_SHOWN],
        }
        self.reviews.ensure_open(ReviewKind.STRUCTURE_SUSPECT, subject)
