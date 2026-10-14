import json
from dataclasses import replace
from pathlib import Path

import pytest
from contract_samples import PDF, TEXT
from metamorph_contract import Bundle, BundleWriter, ContractViolation, UnloadableBundle


def write_bundle(directory: Path, documents) -> None:
    with BundleWriter(directory, connector="ojk", connector_version="0.4.0", run_id="run-1") as bundle:
        bundle.put_blob(PDF)
        bundle.put_text(TEXT)
        for document in documents:
            bundle.add(document)


def test_a_bundle_reads_back_what_was_written(tmp_path, document) -> None:
    write_bundle(tmp_path / "b", [document])

    bundle = Bundle(tmp_path / "b")
    entries = list(bundle.entries())

    assert (bundle.manifest.documents, bundle.manifest.blobs, bundle.manifest.complete) == (1, 2, True)
    assert [e.document for e in entries] == [document]
    assert entries[0].is_valid
    assert bundle.blob_path(document.files[0].sha256).read_bytes() == PDF


def test_a_failed_export_leaves_no_manifest_and_cannot_be_loaded(tmp_path, document) -> None:
    with (
        pytest.raises(RuntimeError),
        BundleWriter(tmp_path / "b", connector="ojk", connector_version="0.4.0", run_id="r"),
    ):
        raise RuntimeError("source went down mid-export")

    with pytest.raises(UnloadableBundle, match="did not finish"):
        Bundle(tmp_path / "b")


def test_a_document_must_bring_its_blobs(tmp_path, document) -> None:
    with (
        BundleWriter(tmp_path / "b", connector="ojk", connector_version="0.4.0", run_id="r") as bundle,
        pytest.raises(ContractViolation, match="was not put into this bundle"),
    ):
        bundle.add(document)


def test_a_source_document_appears_once_per_bundle(tmp_path, document) -> None:
    with pytest.raises(ContractViolation, match="already in this bundle"):
        write_bundle(tmp_path / "b", [document, document])


def test_a_bundle_holds_one_connector(tmp_path, document) -> None:
    foreign = replace(document, source=replace(document.source, connector="bpk"))

    with pytest.raises(ContractViolation, match="in a 'ojk' bundle"):
        write_bundle(tmp_path / "b", [foreign])


def test_a_bundle_directory_is_never_reused(tmp_path, document) -> None:
    write_bundle(tmp_path / "b", [document])

    with pytest.raises(FileExistsError):
        BundleWriter(tmp_path / "b", connector="ojk", connector_version="0.4.0", run_id="run-2")


def test_the_reader_reports_bad_lines_and_missing_blobs_instead_of_failing(tmp_path, document) -> None:
    write_bundle(tmp_path / "b", [document])
    with (tmp_path / "b" / "documents.jsonl").open("a", encoding="utf-8") as lines:
        lines.write("{not json\n")
    Bundle(tmp_path / "b").blob_path(document.files[0].sha256).unlink()

    first, second = Bundle(tmp_path / "b").entries()

    assert first.problems == [f"blob {document.files[0].sha256[:12]}… is missing"]
    assert second.document is None
    assert second.problems[0].startswith("not JSON")


def test_a_manifest_that_breaks_its_schema_is_refused(tmp_path, document) -> None:
    write_bundle(tmp_path / "b", [document])
    manifest_path = tmp_path / "b" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["contract_version"] = "3.0"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(UnloadableBundle, match="manifest breaks the contract: contract_version"):
        Bundle(tmp_path / "b")
