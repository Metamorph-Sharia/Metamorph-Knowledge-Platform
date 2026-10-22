"""`ResultCache` in a directory: what a reader read, a JSON file a reading, so a file is never read twice alike.

    {directory}/{sha256[:2]}/{sha256}/{engine}-{version}-{tier}-{ocr_mode}.json

A file is written whole, then moved into place, so a crash leaves no half reading behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import astuple
from pathlib import Path
from typing import Any

from metamorph_pdf_text.application.ports import CacheKey
from metamorph_pdf_text.application.reading import OcrMode, Reading
from metamorph_pdf_text.domain.page import BBox, Block, BlockKind, Page

FORMAT = 1  # of the files: bump when they change, and the old ones are left unread


class FileResultCache:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def get(self, key: CacheKey) -> Reading | None:
        path = self._path(key)
        if not path.exists():
            return None
        return _reading(json.loads(path.read_text(encoding="utf-8")))

    def put(self, key: CacheKey, reading: Reading) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".part", delete=False) as out:
            json.dump(_json(reading), out, ensure_ascii=False)
        os.replace(out.name, path)

    def _path(self, key: CacheKey) -> Path:
        name = f"{key.engine}-{key.version}-{key.request.tier}-{key.request.ocr_mode}.v{FORMAT}.json"
        return self._directory / key.pdf_sha256[:2] / key.pdf_sha256 / name


def _json(reading: Reading) -> dict[str, Any]:
    return {
        "ocr_mode": str(reading.ocr_mode),
        "pages": [
            {
                "number": page.number,
                "width": page.width,
                "height": page.height,
                "blocks": [
                    {"kind": str(block.kind), "text": block.text, "bbox": list(astuple(block.bbox))}
                    for block in page.blocks
                ],
            }
            for page in reading.pages
        ],
    }


def _reading(data: dict[str, Any]) -> Reading:
    pages = tuple(
        Page(
            page["number"],
            page["width"],
            page["height"],
            tuple(Block(BlockKind(block["kind"]), block["text"], BBox(*block["bbox"])) for block in page["blocks"]),
        )
        for page in data["pages"]
    )
    return Reading(pages, OcrMode(data["ocr_mode"]))
