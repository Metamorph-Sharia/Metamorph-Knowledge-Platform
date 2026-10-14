"""A realistic document (shaped like POJK 5/POJK.05/2014) that each test bends to break one rule."""

import hashlib
from dataclasses import replace

from metamorph_contract import (
    Citation,
    Confidence,
    Dates,
    DocumentInfo,
    ExtractionMethod,
    FileRef,
    FileRole,
    FoundIn,
    Kind,
    NormalizedDocument,
    Provision,
    Relation,
    Rights,
    SourceRef,
    Status,
    StatusClaim,
    TextOrigin,
    TextRef,
    join_pages,
)

PDF = b"%PDF-1.7 POJK 5/POJK.05/2014"
TEXT = join_pages(["PERATURAN OTORITAS JASA KEUANGAN NOMOR 5/POJK.05/2014", "Pasal 1\nDalam Peraturan ini ..."])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_document() -> NormalizedDocument:
    pdf_sha, text_sha = sha(PDF), sha(TEXT.encode())
    return NormalizedDocument(
        source=SourceRef(
            connector="ojk",
            connector_version="0.4.0",
            source_id="regalert:172f8b0a-507b-42c0-a5a7-ff70ccf8cfb3",
            url="https://www.ojk.go.id/id/regulasi/Pages/POJK-tentang-Perizinan-Usaha.aspx",
            fetched_at="2026-10-13T02:34:23+00:00",
        ),
        document=DocumentInfo(
            id="ojk:pojk:2014:5",
            id_confidence=Confidence.HIGH,
            id_evidence="text_header='PERATURAN OTORITAS JASA KEUANGAN NOMOR 5/POJK.05/2014'",
            issuer="ojk",
            family="pojk",
            number="5",
            year=2014,
            citation="POJK 5/POJK.05/2014",
            title="Perizinan Usaha dan Kelembagaan Lembaga Penjaminan",
            language="id",
            kind=Kind.REGULATION,
            status=StatusClaim(value=Status.IN_FORCE, source="regalert", as_of="2026-10-13"),
            dates=Dates(effective="2014-04-08"),
            aliases=("5/POJK.05/2014", "POJK 5/2014"),
        ),
        files=(
            FileRef(
                sha256=pdf_sha, role=FileRole.MAIN, media_type="application/pdf", source_url=None, rights=Rights.PUBLIC
            ),
        ),
        texts=(
            TextRef(
                sha256=text_sha,
                language="id",
                origin=TextOrigin.SELF_EXTRACTED,
                method=ExtractionMethod.TEXT_LAYER,
                rights=Rights.PUBLIC,
                paged=True,
                of_file=pdf_sha,
            ),
        ),
        provisions=(
            Provision(address="pasal-1", kind="pasal", label="Pasal 1", text=text_sha, char_start=80, char_end=120),
        ),
        citations=(
            Citation(
                relation=Relation.LEGAL_BASIS,
                target_text="Undang-Undang Nomor 21 Tahun 2011 tentang Otoritas Jasa Keuangan",
                evidence="Mengingat : 1. Undang-Undang Nomor 21 Tahun 2011 ...",
                found_in=FoundIn.TEXT,
                confidence=Confidence.HIGH,
                target_id="id:uu:2011:21",
                from_address="mengingat/angka-1",
            ),
        ),
        source_fields={"uid": "172f8b0a-507b-42c0-a5a7-ff70ccf8cfb3", "topics": "licensing capital"},
    )


def with_info(document: NormalizedDocument, **changes) -> NormalizedDocument:
    return replace(document, document=replace(document.document, **changes))
