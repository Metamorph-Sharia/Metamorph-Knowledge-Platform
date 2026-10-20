"""Two OJK regulations, one amending the other, built as the registry builds them: for tests that need lineage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from contract_samples import PDF, build_document
from metamorph_contract import Bundle, BundleWriter, NormalizedDocument

from metamorph_platform.adapters.postgres.curation import PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresCitationLinks, PostgresParsedTexts, PostgresValidity
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.application.compute_validity import ComputeValidity
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.publish import Publish
from metamorph_platform.application.resolve_citations import ResolveCitations
from metamorph_platform.domain.structure import grammar_for, parse

TARGET = "ojk:pojk:2018:35"
AMENDING = "ojk:pojk:2022:7"

TARGET_TEXT = """\
PERATURAN OTORITAS JASA KEUANGAN
NOMOR 35/POJK.05/2018
Pasal 110
Dihapus nanti.
Pasal 115
(1) Perusahaan wajib melapor.
(2) Laporan disampaikan.
"""
AMENDING_TEXT = """\
PERATURAN OTORITAS JASA KEUANGAN
NOMOR 7/POJK.05/2022
Mengingat : Undang-Undang Nomor 21 Tahun 2011 tentang Otoritas Jasa Keuangan;
MEMUTUSKAN:
Pasal I
Beberapa ketentuan dalam Peraturan Otoritas Jasa Keuangan Nomor 35/POJK.05/2018 diubah sebagai berikut:
1. Ketentuan Pasal 115 diubah sehingga berbunyi sebagai berikut:
Pasal 115
(1) Perusahaan wajib melapor setiap bulan.
2. Pasal 110 dihapus.
Pasal II
Peraturan Otoritas Jasa Keuangan ini mulai berlaku pada tanggal diundangkan.
Ditetapkan di Jakarta
pada tanggal 25 Februari 2022
Diundangkan di Jakarta
pada tanggal 27 Februari 2022
"""


def regulation(source_id: str, document_id: str, text: str) -> NormalizedDocument:
    sample = build_document()
    number, year = document_id.split(":")[3], int(document_id.split(":")[2])
    text_ref = replace(sample.texts[0], sha256=hashlib.sha256(text.encode()).hexdigest(), paged=False)
    return replace(
        sample,
        source=replace(sample.source, source_id=source_id),
        document=replace(sample.document, id=document_id, number=number, year=year, citation=f"POJK {number}/{year}",
                         aliases=(), dates=replace(sample.document.dates, effective=None)),
        texts=(text_ref,),
        provisions=(),
    )  # fmt: skip


def load(db, blobs, tmp_path) -> None:
    with BundleWriter(tmp_path / "bundle", connector="ojk", connector_version="0.1.0", run_id="r1") as bundle:
        bundle.put_blob(PDF)
        for source_id, document_id, text in (
            ("regalert:target", "ojk:pojk:2018:35", TARGET_TEXT),
            ("regalert:amending", "ojk:pojk:2022:7", AMENDING_TEXT),
        ):
            bundle.put_text(text)
            bundle.add(regulation(source_id, document_id, text))
    reviews = PostgresReviewQueue(db)
    LoadBundle(PostgresIngestLedger(db), PostgresRegistry(db), blobs, reviews, PostgresOverrides(db)).run(
        Bundle(tmp_path / "bundle"), uri="x"
    )
    approve_as_is(db, "ojk:pojk:2018:35", TARGET_TEXT)


def approve_as_is(db, document_id: str, text: str) -> None:
    """TARGET_TEXT is an excerpt (Pasal 110 and 115 only): a curator approved its gaps, so it is published."""
    problems = parse(text, grammar_for("ojk", "pojk")).problems
    db.execute("INSERT INTO curation.curator (username, display_name) VALUES ('ana', 'Ana') ON CONFLICT DO NOTHING")
    db.execute(
        "INSERT INTO curation.approval (document_id, text_sha256, problems, reason, author) "
        "VALUES (%s, %s, %s, 'an excerpt', 'ana')",
        (document_id, hashlib.sha256(text.encode()).hexdigest(), json.dumps(problems)),
    )


def build(db, blobs) -> dict[str, dict[str, int]]:
    reviews = PostgresReviewQueue(db)
    publication = PostgresPublication(db)
    return {
        "parse": ParseTexts(PostgresParsedTexts(db), blobs).run().counts(),
        "resolve": ResolveCitations(PostgresCitationLinks(db), reviews).run().counts(),
        "validity": ComputeValidity(PostgresValidity(db)).run().counts(),
        "publish": Publish(publication, publication, blobs, holds=publication).run().counts(),
    }
