"""Headings a reader ran onto one line with other text: where the line is cut, so that each heading starts a line of
its own, as the grammars read them. MinerU reads a centred heading stack as one block ("BAB I KETENTUAN UMUM Pasal
1"), and an elucidation's labels with their wording ("Pasal 8 Ayat (1) Huruf a Cukup jelas."). Extraction keeps the
reader's lines; legal structure is the parser's to find (plan step 13: it moved here from metamorph-pdf-text).

    a heading stack       "BAB I KETENTUAN UMUM Pasal 1", "Paragraf 1 Umum Pasal 2": "Bagian" and "Paragraf" stand
                          alone, and an article's heading ends the stack
    a title before one    "TRANSAKSI ELEKTRONIK Pasal 17", "PRESIDEN REPUBLIK INDONESIA - 36 - Paragraf 2 Kurator
                          Pasal 69": a title in capitals, then the stack
    a label before more   an elucidation's "Pasal 8", "Ayat (1)", "Huruf a" before another label or the wording it
                          labels; an article's heading before its first paragraph ("Pasal 9 (1) Bank …")
    a label after an end  "… Cukup jelas. Huruf b …", "… Pengguna. (3) Penunjukan …", "… Syariah; Mengingat : 1. …"

What looks like a heading but is wording stays: a sentence citing articles ("Pasal 5 diubah dan Pasal 6 dihapus",
"Pasal 5 Undang-Undang Nomor 10 …", "Pasal 154 Reglemen …"), a list of them a line wraps, a paragraph cited ("ayat
(3) Peraturan ini"). Which cut a grammar takes from the article numbering is the grammar's (grammars.py).
"""

from __future__ import annotations

import itertools
import re

STACK_WORDS = 20  # at most, in a line that is a stack of headings and not a sentence

_HEADING = re.compile(r"\b(?:BAB\s+[IVXLC]+\b|Bagian\s+Ke\w+|Paragraf\s+\d+\b|Pasal\s+(?:\d+[A-Z]?|[IVXLC]+)\b)")
_HEADING_LINE = re.compile(r"^(?:BAB\s+[IVXLC]+|Bagian\s+Ke\w+|Paragraf\s+\d+|Pasal\s+(?:\d+[A-Z]?|[IVXLC]+)\.?)$")
_ALONE = re.compile(r"^(?:Bagian|Paragraf)\b")  # the grammars read them only on a line of their own
# Text that shows a line is wording, not a stack of headings: punctuation, or a paragraph, item or number cited
_NOT_A_STACK = re.compile(r"[,;()]|\b(?:ayat|huruf|angka)\b")

_LABEL = r"(?:Pasal\s+\d+[A-Z]?|Ayat\s+\(\d+[a-z]?\)|Huruf\s+[a-z]{1,2}|Angka\s+\d+[a-z]?)"
_SUBLABEL = r"(?:Ayat\s+\(\d+[a-z]?\)|Huruf\s+[a-z]{1,2}|Angka\s+\d+[a-z]?)"
# A label opening a line, before another label or the wording it labels. An article's only before its first
# paragraph ("Pasal 9 (1) Bank …": a citation says "Pasal 9 ayat (1)") or what an elucidation says of it
# ("Pasal 1 Cukup jelas.", "Pasal 2 Yang dimaksud …"): before any other capital it is an article cited ("Pasal 154
# Reglemen …", "Pasal 5 Undang-Undang …"), as it is before a paragraph a list of citations runs on from ("Pasal 5
# Ayat (1), Pasal 21 …"). A paragraph's, item's or number's before another of them or a capital ("Huruf c Kriteria
# …"), but not before an article's ("Angka 58 Pasal 88": an omnibus law's change 58, to another law's article 88),
# nor before the name of a regulation.
_OPENING_LABEL = re.compile(
    rf"^(Pasal\s+\d+[A-Z]?)\s+(?={_SUBLABEL}(?![\w,;])|Cukup jelas|Yang dimaksud|\(1\)\s)"
    rf"|^({_SUBLABEL})\s+(?={_SUBLABEL}(?!\w)|(?!Pasal|Undang|Peraturan|Keputusan|Instruksi|Kitab|Lampiran|[A-Z]{{2}})[A-Z])"
)
# A label, a paragraph or an opening label after a sentence's end: "… Cukup jelas. Huruf b Cukup jelas.",
# "… Pengguna. (3) Penunjukan", "… Unit Usaha Syariah; Mengingat : 1. Peraturan"; not "… huruf a. Ayat ini
# berlaku", nor a paragraph cited, which follows "ayat". A sentence ends in a word, a number or a bracket ("… Maret
# 2021.", "… (Online Single Submission);"), not in an item's one-letter marker ("a. Angka 4 huruf a, …": a citation
# opening item a)
_LABEL_AFTER_SENTENCE = re.compile(
    rf"(?:(?<=[^\W_]{{2}}[.;:])|(?<=\)[.;:]))\s+(?=Ayat\s+\(|Huruf\s+[a-z]{{1,2}}\s|Angka\s+\d|Pasal\s+\d+[A-Z]?\s+(?:{_LABEL}|Cukup|\(1\)\s)"
    r"|\(\d{1,3}[a-z]?\)\s+[A-Z]|(?:Menimbang|Mengingat|Memperhatikan|Menetapkan|MEMUTUSKAN)\s*:)"
)


def cuts(line: str) -> list[int]:
    """Where in `line` (stripped) each heading run onto it starts: [] when the line is one heading, or wording."""
    starts, cursor = [], 0
    for piece in _pieces(line):
        start = line.index(piece, cursor)
        starts.append(start)
        cursor = start + len(piece)
    return starts[1:]


def _pieces(line: str) -> list[str]:
    return [labelled for piece in _heading_stack(line) for labelled in _labelled(piece)]


def _heading_stack(line: str) -> list[str]:
    """A line that is several headings, a heading a line. It starts with a heading, and either ends with an
    article's ("BAB I KETENTUAN UMUM Pasal 1") or starts with a part or section ("Bagian Keempat Pemeriksaan
    Pendahuluan")."""
    headings = list(_HEADING.finditer(line))
    if not headings or len(line.split()) > STACK_WORDS or _NOT_A_STACK.search(line):
        return [line]
    if headings[0].start() != 0:
        return _titled_stack(line, headings[0].start())
    found = {heading.end() for heading in headings if _ALONE.match(heading[0])}
    found |= {heading.start() for heading in headings[1:] if _ALONE.match(heading[0]) or heading.end() == len(line)}
    if not found - {0, len(line)}:
        return [line]
    bounds = [0, *sorted(found), len(line)]
    return [piece for start, end in itertools.pairwise(bounds) if (piece := line[start:end].strip())]


def _titled_stack(line: str, start: int) -> list[str]:
    """A title in capitals read as one line with the headings after it. A sentence isn't in capitals."""
    title, stack = line[:start].strip(), _heading_stack(line[start:])
    if title.isupper() and (len(stack) > 1 or _HEADING_LINE.match(stack[0])):
        return [title, *stack]
    return [line]


def _labelled(line: str) -> list[str]:
    """An elucidation's labels run together with their wording: a label a line, and its wording after. A chain of
    labels descends ("Ayat (1) Huruf a"); two of a kind ("Ayat (7) Ayat (6)") aren't one."""
    pieces = []
    for sentence in _LABEL_AFTER_SENTENCE.split(line):
        while (label := _OPENING_LABEL.match(sentence)) and not _same_kind(label[0], sentence[label.end() :]):
            pieces.append(label[1] or label[2])
            sentence = sentence[label.end() :]
        if sentence:
            pieces.append(sentence)
    return pieces


def _same_kind(label: str, after: str) -> bool:
    return after.split(" ", 1)[0] == label.split(" ", 1)[0]
