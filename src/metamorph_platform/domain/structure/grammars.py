"""The three shapes of Indonesian legal instruments (docs: OJK-Source-Connector/docs/research/
ojk-publishing-and-storage/02-document-anatomy.md), as line-by-line heading recognisers.

  peraturan     UU, PP, Perpres, POJK, PADK, PBI, PADG, ministerial rules (the UU 12/2011 format):
                Menimbang/Mengingat, BAB › Bagian › Paragraf › Pasal › ayat, Penjelasan, Lampiran.
  surat_edaran  SEOJK, SEBI: Roman sections (I. KETENTUAN UMUM …), Lampiran.
  fatwa         DSN-MUI: Menimbang/Mengingat, then rulings Pertama, Kedua, …

A heading is accepted only when its number comes after the last one at its level. That keeps a
reference wrapped onto its own line ("…dimaksud pada ayat / (1) dilakukan") and a table of contents
from opening nodes, and leaves the gaps for the quality checks to report.
"""

from __future__ import annotations

import re

from metamorph_platform.domain.structure.builder import TreeBuilder
from metamorph_platform.domain.structure.text import Line, is_roman, roman_value

SECTION, CHAPTER, PART, GROUP, ARTICLE, PARAGRAPH, QUOTED_PARAGRAPH = range(7)
MAX_LABEL = 40

_PREAMBLE = re.compile(r"^(menimbang|mengingat|memperhatikan)\b", re.IGNORECASE)
_DECISION = re.compile(r"^MEMUTUSKAN\b")
_SIGNED = re.compile(r"^(ditetapkan|disahkan)\s+di\b", re.IGNORECASE)
# OCR of scanned laws: "Pasal12" and "Pasa12" are headings. "Pasal 12." ends a wrapped reference, and
# "Pasal 12..." is a catchword: neither is.
_PASAL = re.compile(r"^(?:(?:Pasal|PASAL|Pasa)\s*(\d+[A-Z]?)|(?:Pasal|PASAL)\s+([IVXLC]+))$")
_BAB = re.compile(r"^BAB\s+([IVXLC]+)\b\s*(.*)$")
_BAGIAN = re.compile(r"^(?:Bagian|BAGIAN)\s+(Ke\w+|KE\w+)$")
_PARAGRAF = re.compile(r"^(?:Paragraf|PARAGRAF)\s+(\d+)$")
_AYAT = re.compile(r"^\((\d+|l)\)(?:\s|$)")  # OCR reads "(1)" as "(l)"
_AMENDMENT_OPENING = re.compile(r"^Beberapa ketentuan\b", re.IGNORECASE)
# "2. Di antara Pasal 82 dan Pasal 83 disisipkan …", "3. Pasal 30 dihapus.": the amending article's next instruction
_INSTRUCTION = re.compile(
    r"^(\d+)\.\s+(?:Ketentuan|Di\s+antara|Pasal|BAB|Bab|Bagian|Paragraf|Judul|Penjelasan|Lampiran)\b"
)
_WRAPPED_REFERENCE = re.compile(r"\bayat$", re.IGNORECASE)  # "…dimaksud dalam Pasal 5 ayat" / "(3) huruf a"
_ELUCIDATION = re.compile(r"^PENJELASAN(?:\s+ATAS\b.*)?$")
_ELUCIDATION_GENERAL = re.compile(r"^(?:I\.\s*)?UMUM$")
_ARTICLE_BY_ARTICLE = re.compile(r"PASAL\s+DEMI\s+PASAL", re.IGNORECASE)
_ELUCIDATED_AYAT = re.compile(r"^Ayat\s*\((\d+)\)$", re.IGNORECASE)
_ANNEX = re.compile(r"^LAMPIRAN(?:\s+([IVXLC]+|\d+))?(?:\s+[A-Z0-9 ,.:/()-]*)?$")
_TABLE_OF_CONTENTS = re.compile(r"(\.{4,}|…{2,}|\s\d+$)")
_ROMAN_SECTION = re.compile(r"^([IVX]+)\.\s*(.*)$")
_RULING = re.compile(
    r"^(pertama|kedua|ketiga|keempat|kelima|keenam|ketujuh|kedelapan|kesembilan|kesepuluh)\s*(?::\s*(.*))?$",
    re.IGNORECASE,
)
_RULING_ORDER = ("pertama", "kedua", "ketiga", "keempat", "kelima", "keenam", "ketujuh", "kedelapan", "kesembilan",
                 "kesepuluh")  # fmt: skip


def article_key(number: str) -> tuple[int, str]:
    """ "82A" → (82, "a"): an inserted article sorts after the one it follows."""
    digits = re.match(r"\d+", number)[0]
    return int(digits), number[len(digits) :].lower()


class _Grammar:
    """What every shape shares: the preamble, the annexes, and the heading on the line after a bare one."""

    def __init__(self, builder: TreeBuilder) -> None:
        self.b = builder
        self.previous = ""  # the last content line
        self.decided = False  # past MEMUTUSKAN
        self.annex: str | None = None
        self.last_annex = 0
        self.last_annex_chapter = 0

    def feed(self, line: Line) -> None:
        if not self.step(line):
            self.b.take_heading(line)
        self.previous = line.text

    def step(self, line: Line) -> bool:
        raise NotImplementedError

    def preamble(self, line: Line) -> bool:
        if self.decided:
            return False
        found = _PREAMBLE.match(line.text)
        if found:
            name = found[1].lower()
            return self.b.open(CHAPTER, name, name, found[1].capitalize(), line)
        if _DECISION.match(line.text):
            self.decided = True
            return self.b.open(CHAPTER, "memutuskan", "memutuskan", "MEMUTUSKAN", line)
        return False

    def annexes(self, line: Line) -> bool:
        found = _ANNEX.match(line.text)
        if found:
            numeral = found[1]
            value = roman_value(numeral) if numeral and is_roman(numeral) else int(numeral or 1)
            address = f"lampiran-{numeral.lower()}" if numeral else "lampiran"
            if value < self.last_annex or (value == self.last_annex and self.b.has(address)):
                return True  # a running header repeating the annex we are in
            if self.b.open(SECTION, address, "lampiran", line.text[:MAX_LABEL], line):
                self.annex, self.last_annex, self.last_annex_chapter = address, value, 0
            return True
        if self.annex is None:
            return False
        chapter = _BAB.match(line.text)
        if chapter and not _TABLE_OF_CONTENTS.search(line.text) and roman_value(chapter[1]) > self.last_annex_chapter:
            self.last_annex_chapter = roman_value(chapter[1])
            address = f"{self.annex}/bab-{chapter[1].lower()}"
            return self.b.open(
                CHAPTER, address, "bab", f"BAB {chapter[1]}", line, heading=chapter[2], expects_heading=True
            )
        return False


class Peraturan(_Grammar):
    def __init__(self, builder: TreeBuilder) -> None:
        super().__init__(builder)
        self.section = "body"  # body | signed | elucidation | annex
        self.chapter: str | None = None
        self.part: str | None = None
        self.last_chapter = 0
        self.last_article: tuple[int, str] | None = None
        self.last_roman = 0
        self.amending: str | None = None  # the Roman article (Pasal I) quoting the articles it changes
        self.last_instruction = 0
        self.article: str | None = None
        self.last_ayat = 0
        self.last_explained: tuple[int, str] | None = None

    def step(self, line: Line) -> bool:
        if _ELUCIDATION.match(line.text) and self.section != "elucidation" and (self.started() or self.b.empty()):
            self.section, self.annex = "elucidation", None
            return self.b.open(SECTION, "penjelasan", "penjelasan", "PENJELASAN", line)
        if self.section != "body" and self.annexes(line):
            self.section = "annex" if self.annex else self.section
            return True
        if self.section == "body":
            return (not self.started() and self.preamble(line)) or self.body(line) or self.annexes_from_body(line)
        if self.section == "elucidation":
            return self.elucidation(line)
        if self.section == "annex":
            return self.annexes(line)
        return False

    def started(self) -> bool:
        """Past the first article: the preamble is over, and the signature or an elucidation may follow."""
        return self.last_article is not None or self.last_roman > 0

    def annexes_from_body(self, line: Line) -> bool:
        if self.started() and self.annexes(line):
            self.section = "annex"
            return True
        return False

    def body(self, line: Line) -> bool:
        if _SIGNED.match(line.text) and self.started():
            self.section = "signed"
            return self.b.open(CHAPTER, "pengesahan", "pengesahan", line.text[:MAX_LABEL], line)
        article = _PASAL.match(line.text)
        if article:
            return self.body_article(article[1] or article[2], line)
        if self.article == "pasal-1" and self.last_ayat == 0 and _AMENDMENT_OPENING.match(line.text):
            self.misread_amending_article()
            return False
        if self.amending and self.next_instruction(line):
            return False
        return self.ayat(line) or self.grouping(line)

    def next_instruction(self, line: Line) -> bool:
        """An amending article's numbered instruction ends the article quoted before it; it is the amending
        article's own text again."""
        found = _INSTRUCTION.match(line.text)
        if not found or int(found[1]) != self.last_instruction + 1:
            return False
        self.last_instruction += 1
        self.b.close(PARAGRAPH)
        self.article = self.amending
        return True

    def misread_amending_article(self) -> None:
        """Extraction often reads an amending regulation's "Pasal I" as "Pasal 1"; its first words tell."""
        self.b.rename_last("pasal-i", "Pasal I")
        self.last_article, self.last_roman, self.amending, self.article = None, 1, "pasal-i", "pasal-i"

    def grouping(self, line: Line) -> bool:
        if self.amending:
            return False  # chapters quoted in an amendment are text, not this regulation's chapters
        chapter = _BAB.match(line.text)
        if chapter and not _TABLE_OF_CONTENTS.search(line.text) and roman_value(chapter[1]) > self.last_chapter:
            self.last_chapter = roman_value(chapter[1])
            self.chapter, self.part, self.article = f"bab-{chapter[1].lower()}", None, None
            return self.b.open(
                CHAPTER, self.chapter, "bab", f"BAB {chapter[1]}", line, heading=chapter[2], expects_heading=True
            )
        part = _BAGIAN.match(line.text)
        if part and self.chapter:
            self.part, self.article = f"{self.chapter}/bagian-{part[1].lower()}", None
            return self.b.open(PART, self.part, "bagian", line.text, line, expects_heading=True)
        group = _PARAGRAF.match(line.text)
        if group and self.part:
            self.article = None
            return self.b.open(
                GROUP, f"{self.part}/paragraf-{group[1]}", "paragraf", line.text, line, expects_heading=True
            )
        return False

    def body_article(self, number: str, line: Line) -> bool:
        if is_roman(number):
            if roman_value(number) <= self.last_roman:
                return False
            self.last_roman = roman_value(number)
            self.amending = self.article = f"pasal-{number.lower()}"
            self.last_ayat = self.last_instruction = 0
            return self.b.open(ARTICLE, self.amending, "pasal", f"Pasal {number}", line)
        if self.amending:
            self.article, self.last_ayat = f"{self.amending}/pasal-{number.lower()}", 0
            return self.b.open(PARAGRAPH, self.article, "pasal", f"Pasal {number}", line)
        key = article_key(number)
        if self.last_article is not None and key <= self.last_article:
            return False
        self.last_article, self.article, self.last_ayat = key, f"pasal-{number.lower()}", 0
        return self.b.open(ARTICLE, self.article, "pasal", f"Pasal {number}", line)

    def ayat(self, line: Line) -> bool:
        found = _AYAT.match(line.text)
        number = 1 if found and found[1] == "l" else int(found[1]) if found else 0
        if not found or self.article is None or number <= self.last_ayat or _WRAPPED_REFERENCE.search(self.previous):
            return False
        self.last_ayat = number
        level = QUOTED_PARAGRAPH if self.amending and self.article != self.amending else PARAGRAPH
        return self.b.open(level, f"{self.article}/ayat-{number}", "ayat", f"({number})", line)

    def elucidation(self, line: Line) -> bool:
        if _ELUCIDATION_GENERAL.match(line.text):
            return self.b.open(CHAPTER, "penjelasan/umum", "penjelasan", "UMUM", line)
        if _ARTICLE_BY_ARTICLE.search(line.text):
            self.b.close(CHAPTER)
            return True
        article = _PASAL.match(line.text)
        if article:
            number = article[1] or article[2]
            key = (roman_value(number), "") if is_roman(number) else article_key(number)
            if self.last_explained is not None and key <= self.last_explained:
                return False
            self.last_explained, self.article, self.last_ayat = key, f"penjelasan/pasal-{number.lower()}", 0
            return self.b.open(ARTICLE, self.article, "penjelasan", f"Pasal {number}", line)
        explained = _ELUCIDATED_AYAT.match(line.text)
        if explained and self.article and int(explained[1]) > self.last_ayat:
            self.last_ayat = int(explained[1])
            address = f"{self.article}/ayat-{explained[1]}"
            return self.b.open(PARAGRAPH, address, "penjelasan", f"Ayat ({explained[1]})", line)
        return False


class SuratEdaran(_Grammar):
    def __init__(self, builder: TreeBuilder) -> None:
        super().__init__(builder)
        self.last_section = 0

    def step(self, line: Line) -> bool:
        if self.annexes(line):
            return True
        if self.annex:
            return False
        section = _ROMAN_SECTION.match(line.text)
        if not section or roman_value(section[1]) <= self.last_section or not _looks_like_heading(section[2]):
            return False
        self.last_section = roman_value(section[1])
        address = f"romawi-{section[1].lower()}"
        return self.b.open(CHAPTER, address, "romawi", f"{section[1]}.", line, heading=section[2], expects_heading=True)


class Fatwa(_Grammar):
    def __init__(self, builder: TreeBuilder) -> None:
        super().__init__(builder)
        self.last_ruling = 0

    def step(self, line: Line) -> bool:
        if self.preamble(line):
            return True
        ruling = _RULING.match(line.text)
        if not ruling or not self.decided:
            return False
        order = _RULING_ORDER.index(ruling[1].lower()) + 1
        if order <= self.last_ruling:
            return False
        self.last_ruling = order
        name = ruling[1].lower()
        return self.b.open(
            CHAPTER, f"diktum-{name}", "diktum", name.capitalize(), line, heading=ruling[2], expects_heading=True
        )


def _looks_like_heading(text: str) -> bool:
    """A Roman section heading is in capitals ("KETENTUAN UMUM"), or on the next line when this one is bare."""
    letters = [char for char in text if char.isalpha()]
    return not letters or sum(char.isupper() for char in letters) / len(letters) > 0.8


GRAMMARS = {"peraturan": Peraturan, "surat_edaran": SuratEdaran, "fatwa": Fatwa}
