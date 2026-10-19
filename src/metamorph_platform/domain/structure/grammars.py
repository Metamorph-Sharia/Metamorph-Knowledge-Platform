"""The three shapes of Indonesian legal instruments (docs: OJK-Source-Connector/docs/research/
ojk-publishing-and-storage/02-document-anatomy.md), as line-by-line heading recognisers.

  peraturan     UU, PP, Perpres, POJK, PADK, PBI, PADG, ministerial rules (the UU 12/2011 format):
                Menimbang/Mengingat, BAB › Bagian › Paragraf › Pasal › ayat, Penjelasan, Lampiran.
  surat_edaran  SEOJK, SEBI: Roman sections (I. KETENTUAN UMUM …), Lampiran.
  fatwa         DSN-MUI: Menimbang/Mengingat, then rulings Pertama, Kedua, …

An amendment quotes what it changes, and what it quotes is not its own:
  amending regulation  Pasal I quotes the articles it changes (pasal-i/pasal-115), Pasal II ends it
  omnibus law          each article that opens "Beberapa ketentuan dalam Undang-Undang …" quotes that law's
                       articles (pasal-17/pasal-18), until the omnibus law's own next article
  amending circular    the sections it quotes ("… angka III berbunyi sebagai berikut: / III. …") are text

A heading is accepted only when its number comes after the last one at its level, and not far after
it. That keeps a reference wrapped onto its own line ("…dimaksud pada ayat / (1) dilakukan"), a table
of contents and a misread number from opening nodes, and leaves the gaps for the quality checks to
report. A heading damaged by OCR has several readings (misreadings.py);
the one that continues the sequence is kept.
"""

from __future__ import annotations

import re

from metamorph_platform.domain.structure.builder import TreeBuilder
from metamorph_platform.domain.structure.misreadings import article_numbers, paragraph_numbers
from metamorph_platform.domain.structure.text import Line, is_roman, next_line, roman_value

SECTION, CHAPTER, PART, GROUP, ARTICLE, PARAGRAPH, QUOTED_PARAGRAPH = range(7)
MAX_LABEL = 40
# Headings lost at page breaks leave short gaps; a jump further than this is another instrument's article
# quoted in this one, or a misread number. Accepting it would refuse every real article below it.
MAX_ARTICLE_JUMP = 15
MAX_PARAGRAPH_JUMP = 5  # an article's paragraphs are few: "(29)" after (3) is a misread "(2)" or a reference
MAX_INSTRUCTION_JUMP = 3  # an amendment's instructions run 1, 2, 3 …; OCR drops the odd number
MAX_SECTION_JUMP = 3  # a circular has a handful of sections: a titled one further ahead is a quoted one

_PREAMBLE = re.compile(r"^(menimbang|mengingat|memperhatikan)\b", re.IGNORECASE)
_DECISION = re.compile(r"^MEMUTUSKAN\b")
_SIGNED = re.compile(r"^(ditetapkan|disahkan)\s+di\b", re.IGNORECASE)
_DOTTED_PASAL = re.compile(r"^(?:Pasal|PASAL)\s+(\d+)\.$")
_SENTENCE_END = re.compile(r"[.:;]$")
_BAB = re.compile(r"^BAB\s+([IVXLC]+)\b\s*(.*)$")
_BAGIAN = re.compile(r"^(?:Bagian|BAGIAN)\s+(Ke\w+|KE\w+)$")
_PARAGRAF = re.compile(r"^(?:Paragraf|PARAGRAF)\s+(\d+)$")
_AMENDMENT_OPENING = re.compile(r"^Beberapa ketentuan\b", re.IGNORECASE)
# "2. Di antara Pasal 82 dan Pasal 83 disisipkan …", "3. Pasal 30 dihapus.": the amending article's next instruction
_INSTRUCTION = re.compile(
    r"^(\d+)\.\s+(?:Ketentuan|Di\s+antara|Pasal|BAB|Bab|Bagian|Paragraf|Judul|Penjelasan|Lampiran)\b"
)
_DELETION = re.compile(r"\bdihapus\.?$")  # "3. Pasal 30 dihapus.": an instruction that quotes nothing
_WRAPPED_REFERENCE = re.compile(r"\bayat$", re.IGNORECASE)  # "…dimaksud dalam Pasal 5 ayat" / "(3) huruf a"
_ELUCIDATION = re.compile(r"^PENJELASAN(?:\s+ATAS\b.*)?$")
_ELUCIDATION_GENERAL = re.compile(r"^(?:I\.\s*)?UMUM$")
_ARTICLE_BY_ARTICLE = re.compile(r"PASAL\s+DEMI\s+PASAL", re.IGNORECASE)
_ELUCIDATED_AYAT = re.compile(r"^Ayat\s*\((\d+)\)$", re.IGNORECASE)
_ANNEX = re.compile(r"^LAMPIRAN(?:\s+([IVXLC]+|\d+))?(?:\s+[A-Z0-9 ,.:/()-]*)?$")
_TABLE_OF_CONTENTS = re.compile(r"(\.{4,}|…{2,}|\s\d+$)")
_ROMAN_SECTION = re.compile(r"^([IVX]+)\.\s*(.*)$")
_CATCHWORD = re.compile(r"(?:\.\s*){3}$|…$")  # "X. PENUTUP . . .": the next page's first words, at this one's foot
# "1. Ketentuan BAB I angka 5 dihapus", "Ketentuan butir III.A diubah", "Mengubah angka IV sehingga …",
# "I. Beberapa ketentuan dalam Surat Edaran … diubah": a circular that changes another one
_AMENDS_A_CIRCULAR = re.compile(
    r"^(?:[IVX]+\.|\d+\.)?\s*(?:beberapa\s+ketentuan\s+dalam\s+surat\s+edaran"
    r"|(?:ketentuan|mengubah|menghapus|di\s*antara)\s+(?:dalam\s+)?(?:bab|angka|butir|romawi)\s+[IVX]+\b)",
    re.IGNORECASE,
)
# "… sehingga berbunyi sebagai berikut:", "… yakni": the line before a quoted heading. Anywhere in the line, since
# OCR scatters an instruction's words over several ("10. Ketentuan Pasal / berikut: / 18 diubah sehingga berbunyi")
_INTRODUCES_A_QUOTE = re.compile(r"\b(?:berbunyi|berikut|yakni|yaitu)\b", re.IGNORECASE)
_RULING = re.compile(
    r"^(pertama|kedua|ketiga|keempat|kelima|keenam|ketujuh|kedelapan|kesembilan|kesepuluh)\s*(?::\s*(.*))?$",
    re.IGNORECASE,
)
_RULING_ORDER = ("pertama", "kedua", "ketiga", "keempat", "kelima", "keenam", "ketujuh", "kedelapan", "kesembilan",
                 "kesepuluh")  # fmt: skip


def _continuing(numbers: list[str], last: int) -> str:
    """Of a heading's readings, the one closest above the last number seen; the first when none is above."""
    above = [number for number in numbers if not is_roman(number) and article_key(number)[0] > last]
    return min(above, key=article_key, default=numbers[0])


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
        self.amending: str | None = None  # the article quoting the ones it changes: "pasal-i", or an omnibus "pasal-17"
        self.last_instruction = 0
        self.article: str | None = None
        self.last_ayat = 0
        self.last_explained: tuple[int, str] | None = None
        self.quote_pending = False  # an amending instruction was read: the next article heading is the one it quotes

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
        numbers = article_numbers(line.text) or self.dotted_heading(line.text)
        if numbers:
            return self.body_article(_continuing(numbers, self.last_number), line)
        if self.decided and not self.started() and _AMENDMENT_OPENING.match(line.text):
            return self.unheaded_amending_article(line)
        if self.article == "pasal-1" and self.last_ayat == 0 and _AMENDMENT_OPENING.match(line.text):
            self.misread_amending_article()
            return False
        if self.opens_amending_article(line):
            self.amending, self.last_instruction = self.article, 0
            return False
        if self.amending and self.next_instruction(line):
            return False
        return self.ayat(line) or self.grouping(line)

    def dotted_heading(self, text: str) -> list[str]:
        """Older laws write "Pasal 1.". So does a reference wrapped onto its own line ("… dalam\nPasal 3."),
        so it is a heading only after a finished sentence or a chapter's title, not mid-phrase."""
        found = _DOTTED_PASAL.match(text)
        if found and (_SENTENCE_END.search(self.previous) or _in_capitals(self.previous)):
            return [found[1]]
        return []

    def next_instruction(self, line: Line) -> bool:
        """An amending article's next numbered instruction ends the article quoted before it; it is the
        amending article's own text again. OCR loses the odd instruction, so the number may skip a little."""
        found = _INSTRUCTION.match(line.text)
        if not found or not self.last_instruction < int(found[1]) <= self.last_instruction + MAX_INSTRUCTION_JUMP:
            return False
        self.last_instruction = int(found[1])
        self.b.close(PARAGRAPH)
        self.article, self.quote_pending = self.amending, not _DELETION.search(line.text)
        return True

    def opens_amending_article(self, line: Line) -> bool:
        """An omnibus law's article whose first words amend another law ("Pasal 17 / Beberapa ketentuan dalam
        Undang-Undang Nomor 26 Tahun 2007 … diubah"): the articles it quotes nest under it."""
        return (
            not self.amending
            and self.article is not None
            and bool(article_numbers(self.previous))
            and bool(_AMENDMENT_OPENING.match(line.text))
        )

    def resumes_body(self, number: str, line: Line) -> bool:
        """The omnibus law's own article ends the amending one before it. One whose first words amend another
        law is the law's own at any number near the last, so a lost heading costs one article, not the rest. Any
        other is its own only as the next number, and not right after an instruction introduced it ("10.
        Ketentuan Pasal 18 diubah sehingga berbunyi sebagai berikut:"): a quoted article may carry any number.
        A Roman amending article (Pasal I) ends only at the next Roman one."""
        if not self.in_omnibus_amendment or is_roman(number):  # an omnibus law has no Roman articles of its own
            return False
        if _AMENDMENT_OPENING.match(next_line(self.b.text, line.end)):
            return self.follows(article_key(number))
        if self.quote_pending:
            return False
        own_next = article_key(number) == (self.last_number + 1, "")  # new law: no inserted article of its own
        return own_next and not _INTRODUCES_A_QUOTE.search(self.previous)

    def unheaded_amending_article(self, line: Line) -> bool:
        """An amendment that opens the body ("Beberapa ketentuan dalam … diubah") is its Pasal I, whatever
        became of the heading: dropped from the text, split over two lines, or glued to stray glyphs."""
        return self.body_article("I", line)

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
        if is_roman(number) and not self.in_omnibus_amendment:
            if roman_value(number) <= self.last_roman:
                return False
            self.last_roman = roman_value(number)
            self.amending = self.article = f"pasal-{number.lower()}"
            self.last_ayat = self.last_instruction = 0
            return self.b.open(ARTICLE, self.amending, "pasal", f"Pasal {number}", line)
        if self.amending and not self.resumes_body(number, line):
            self.article, self.last_ayat, self.quote_pending = f"{self.amending}/pasal-{number.lower()}", 0, False
            return self.b.open(PARAGRAPH, self.article, "pasal", f"Pasal {number}", line)
        self.amending = None
        key = article_key(number)
        if not self.follows(key):
            return False
        self.last_article, self.article, self.last_ayat = key, f"pasal-{number.lower()}", 0
        return self.b.open(ARTICLE, self.article, "pasal", f"Pasal {number}", line)

    @property
    def in_omnibus_amendment(self) -> bool:
        """Inside an omnibus law's amending article ("pasal-17"), not an amending regulation's "pasal-i"."""
        return self.amending is not None and not is_roman(self.amending.removeprefix("pasal-"))

    @property
    def last_number(self) -> int:
        return self.last_article[0] if self.last_article else 0

    def follows(self, key: tuple[int, str]) -> bool:
        """After the body's last article, and near it: a heading far ahead is a quoted or misread one.
        The first may be any number: a text can begin part-way through an instrument."""
        if self.last_article is None:
            return True
        return key > self.last_article and key[0] - self.last_article[0] <= MAX_ARTICLE_JUMP

    def ayat(self, line: Line) -> bool:
        if self.article is None or _CATCHWORD.search(line.text) or _WRAPPED_REFERENCE.search(self.previous):
            return False
        number = min((n for n in paragraph_numbers(line.text) if self.follows_paragraph(n)), default=None)
        if number is None:
            return False
        self.last_ayat = number
        level = QUOTED_PARAGRAPH if self.amending and self.article != self.amending else PARAGRAPH
        return self.b.open(level, f"{self.article}/ayat-{number}", "ayat", f"({number})", line)

    def follows_paragraph(self, number: int) -> bool:
        """After the article's last paragraph, and near it. The first may be any: an amendment may quote
        an article from the paragraph it changes."""
        if self.last_ayat == 0:
            return True
        return self.last_ayat < number <= self.last_ayat + MAX_PARAGRAPH_JUMP

    def elucidation(self, line: Line) -> bool:
        if _ELUCIDATION_GENERAL.match(line.text):
            return self.b.open(CHAPTER, "penjelasan/umum", "penjelasan", "UMUM", line)
        if _ARTICLE_BY_ARTICLE.search(line.text):
            self.b.close(CHAPTER)
            return True
        numbers = article_numbers(line.text)
        if numbers:
            number = _continuing(numbers, self.last_explained[0] if self.last_explained else 0)
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
    """An amending circular quotes the sections it replaces ("… sehingga angka III berbunyi sebagai
    berikut:\nIII. LAPORAN …"). Like the chapters an amending regulation quotes, they are text of the
    circular's own sections, which in an amendment follow one another without gaps."""

    def __init__(self, builder: TreeBuilder) -> None:
        super().__init__(builder)
        self.last_section = 0
        self.is_amendment = False

    def step(self, line: Line) -> bool:
        if self.annexes(line):
            return True
        if self.annex:
            return False
        quoted = self.is_amendment and _INTRODUCES_A_QUOTE.search(self.previous)
        self.is_amendment = self.is_amendment or bool(_AMENDS_A_CIRCULAR.match(line.text))
        section = _ROMAN_SECTION.match(line.text)
        if not section or quoted or not self.opens_section(roman_value(section[1]), section[2]):
            return False
        self.last_section = roman_value(section[1])
        address = f"romawi-{section[1].lower()}"
        return self.b.open(CHAPTER, address, "romawi", f"{section[1]}.", line, heading=section[2], expects_heading=True)

    def opens_section(self, number: int, title: str) -> bool:
        """A section heading comes after the last one. A titled one in capitals may skip a few lost at page
        breaks; a bare one ("II." named on the next line) or a mixed-case one must be the very next."""
        if number <= self.last_section or _CATCHWORD.search(title) or _is_reference(title):
            return False
        if self.is_amendment:
            return number == self.last_section + 1
        if _in_capitals(title):
            return number - self.last_section <= MAX_SECTION_JUMP
        return number == self.last_section + 1


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


def _in_capitals(text: str) -> bool:
    """ "KETENTUAN UMUM", not "Spesifikasi Tanda Pengenal"; a bare numeral has no title to be in capitals."""
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and sum(char.isupper() for char in letters) / len(letters) > 0.8


def _is_reference(title: str) -> bool:
    """ "IX.2." or "III.D.": a reference to a section wrapped onto its own line has no word in its title."""
    return bool(title.strip()) and not re.search(r"[A-Za-z]{3}", title)


GRAMMARS = {"peraturan": Peraturan, "surat_edaran": SuratEdaran, "fatwa": Fatwa}
