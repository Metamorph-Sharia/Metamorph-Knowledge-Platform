"""Realistic bundles for platform tests, built with the contract package's own sample document."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from contract_samples import PDF, TEXT, build_document
from metamorph_contract import BundleWriter, Confidence, NormalizedDocument, unresolved_id


def document(source_id: str = "regalert:172f8b0a", **info_changes) -> NormalizedDocument:
    sample = build_document()
    return replace(
        sample,
        source=replace(sample.source, source_id=source_id),
        document=replace(sample.document, **info_changes),
    )


def unresolved(source_id: str = "regalert:0f2aa739") -> NormalizedDocument:
    return document(source_id, id=unresolved_id("ojk", source_id), id_confidence=Confidence.NONE)


def write_bundle(
    directory: Path, documents: list[NormalizedDocument], run_id: str = "run-1", extra_lines: list[str] = ()
) -> Path:
    with BundleWriter(directory, connector="ojk", connector_version="0.1.0", run_id=run_id) as bundle:
        bundle.put_blob(PDF)
        bundle.put_text(TEXT)
        for each in documents:
            bundle.add(each)
    if extra_lines:
        with (directory / "documents.jsonl").open("a", encoding="utf-8") as lines:
            lines.writelines(line + "\n" for line in extra_lines)
    return directory
