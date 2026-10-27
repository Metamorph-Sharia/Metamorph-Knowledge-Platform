"""A market bundle: one connector run's full snapshot, as files a loader can read without the connector.

    {bundle}/manifest.json           written last, only when the run succeeded
    {bundle}/records.jsonl           one record per line
    {bundle}/blobs/{sha[:2]}/{sha}   every file the records reference

The same guarantees as contract v2's bundle (metamorph_contract.bundle): a bundle without a complete manifest is
never loaded, so a crashed export can't look like "these licenses disappeared from the register".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from metamorph_market.codec import ContractViolation, from_json, to_json
from metamorph_market.record import MARKET_CONTRACT_VERSION, LicensedEntityRecord
from metamorph_market.schema import MANIFEST_SCHEMA, schema_problems
from metamorph_market.validate import problems

MANIFEST = "manifest.json"
RECORDS = "records.jsonl"
BLOBS = "blobs"


class UnloadableBundle(Exception):
    """No complete manifest (the run didn't finish) or another contract: never load it."""


@dataclass(frozen=True)
class Manifest:
    connector: str
    connector_version: str
    run_id: str
    created_at: str
    records: int
    blobs: int
    complete: bool
    snapshot: str = "full"  # every record the connector holds, so absence means "gone from the source"
    contract_version: str = MARKET_CONTRACT_VERSION


@dataclass(frozen=True)
class BundleEntry:
    line: int
    record: LicensedEntityRecord | None
    problems: list[str] = field(default_factory=list)
    raw: str = ""  # the line as written, so a rejected one can be quarantined exactly as received

    @property
    def is_valid(self) -> bool:
        return self.record is not None and not self.problems


def blob_path(root: Path, sha256: str) -> Path:
    return root / BLOBS / sha256[:2] / sha256


class BundleWriter:
    """Use as a context manager; the manifest is written on a clean exit only."""

    def __init__(self, directory: Path, *, connector: str, connector_version: str, run_id: str) -> None:
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError(f"{directory} is not empty: one bundle per directory")
        self.directory = directory
        self.connector = connector
        self.connector_version = connector_version
        self.run_id = run_id
        self._blobs: set[str] = set()
        self._source_ids: set[str] = set()
        (directory / BLOBS).mkdir(parents=True, exist_ok=True)
        self._records = (directory / RECORDS).open("w", encoding="utf-8")

    def put_blob(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        if sha not in self._blobs:
            path = blob_path(self.directory, sha)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self._blobs.add(sha)
        return sha

    def add(self, record: LicensedEntityRecord) -> None:
        found = problems(record) + self._bundle_problems(record)
        if found:
            raise ContractViolation(found)
        self._records.write(to_json(record) + "\n")
        self._source_ids.add(record.source.source_id)

    def _bundle_problems(self, record: LicensedEntityRecord) -> list[str]:
        found = []
        if record.source.connector != self.connector:
            found.append(f"source.connector: {record.source.connector!r} in a {self.connector!r} bundle")
        if record.source.source_id in self._source_ids:
            found.append(f"source.source_id: {record.source.source_id!r} is already in this bundle")
        found += [f"blob {sha[:12]}… was not put into this bundle" for sha in _referenced_blobs(record) - self._blobs]
        return found

    def __enter__(self) -> BundleWriter:
        return self

    def __exit__(
        self, error_type: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._records.close()
        if error_type is None:
            self._write_manifest()

    def _write_manifest(self) -> None:
        manifest = Manifest(
            connector=self.connector,
            connector_version=self.connector_version,
            run_id=self.run_id,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            records=len(self._source_ids),
            blobs=len(self._blobs),
            complete=True,
        )
        (self.directory / MANIFEST).write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")


class Bundle:
    """A finished bundle, read back. Each entry carries its record or the reasons it was rejected."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.manifest = _read_manifest(directory)

    def entries(self) -> Iterator[BundleEntry]:
        with (self.directory / RECORDS).open(encoding="utf-8") as lines:
            for number, line in enumerate(lines, start=1):
                yield self._entry(number, line)

    def blob_path(self, sha256: str) -> Path:
        return blob_path(self.directory, sha256)

    def _entry(self, number: int, line: str) -> BundleEntry:
        raw = line.rstrip("\n")
        try:
            record = from_json(line)
        except ContractViolation as violation:
            return BundleEntry(line=number, record=None, problems=violation.problems, raw=raw)
        referenced = sorted(_referenced_blobs(record))
        missing = [f"blob {sha[:12]}… is missing" for sha in referenced if not self.blob_path(sha).is_file()]
        return BundleEntry(line=number, record=record, problems=problems(record) + missing, raw=raw)


def _read_manifest(directory: Path) -> Manifest:
    path = directory / MANIFEST
    if not path.is_file():
        raise UnloadableBundle(f"{directory}: no manifest, the export did not finish")
    data = json.loads(path.read_text(encoding="utf-8"))
    found = schema_problems(data, MANIFEST_SCHEMA)
    if found:
        raise UnloadableBundle(f"{directory}: manifest breaks the contract: {'; '.join(found)}")
    return Manifest(**data)


def _referenced_blobs(record: LicensedEntityRecord) -> set[str]:
    return {file.sha256 for file in record.files} | {listing.file for listing in record.listings}
