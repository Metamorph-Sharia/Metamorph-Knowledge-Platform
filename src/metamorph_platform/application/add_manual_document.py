"""A curator adds a document no connector holds. It goes through LoadBundle like every connector's
bundle, so there is one way into the registry: a one-document `manual` bundle that adds, never replaces.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from metamorph_contract import Bundle, BundleWriter

from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.ports import CurationActions, CurationRefused, Curator
from metamorph_platform.domain.manual import CONNECTOR, ManualDocument, manual_document, text_of


class AddManualDocument:
    def __init__(self, load: LoadBundle, actions: CurationActions, known: Callable[[str], bool]) -> None:
        """`known(document_id)`: whether the registry holds that document already."""
        self.load = load
        self.actions = actions
        self.known = known

    def run(self, curator: Curator, entry: ManualDocument) -> str:
        now = datetime.now(UTC)
        document = manual_document(
            entry, author=curator.username, fetched_at=now.isoformat(timespec="seconds"), version=_version()
        )
        document_id = document.document.id
        if self.known(document_id):
            raise CurationRefused(
                f"{document_id} is held already: correct its fields on its page instead of adding it again"
            )
        run_id = f"{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory(prefix="metamorph-manual-") as directory:
            bundle_dir = Path(directory) / "bundle"
            with BundleWriter(bundle_dir, connector=CONNECTOR, connector_version=_version(), run_id=run_id) as bundle:
                bundle.put_blob(entry.file_bytes)
                if (text := text_of(entry)) is not None:
                    bundle.put_text(text)
                bundle.add(document)
            self.load.run(Bundle(bundle_dir), uri=f"manual upload by {curator.username}", full_snapshot=False)
        self.actions.record(
            curator,
            "add_document",
            {"document_id": document_id},
            {"file": entry.file_name, "sha256": document.files[0].sha256, "run_id": run_id},
            entry.reason,
        )
        return document_id


def _version() -> str:
    return version("metamorph-knowledge-platform")
