"""`problems(document)`: every way a document breaks contract v2.

The JSON Schema checks each value on its own. The rules here compare values with each other,
which a schema can't express: an ID against its issuer, references between files, texts and
provisions, and duplicates.
"""

from __future__ import annotations

import json

from metamorph_contract.codec import to_json
from metamorph_contract.document import Confidence, NormalizedDocument
from metamorph_contract.identity import is_unresolved, issuer_of
from metamorph_contract.schema import schema_problems

_UNSURE = {Confidence.NONE, Confidence.CONFLICT}


def problems(document: NormalizedDocument) -> list[str]:
    try:
        data = json.loads(to_json(document))  # exactly what a bundle line will hold
    except (TypeError, ValueError) as exc:
        return [f"not representable as JSON: {exc}"]
    return [
        *schema_problems(data),
        *_identity_problems(document),
        *_duplicate_blob_problems(document),
        *_text_reference_problems(document),
        *_provision_problems(document),
    ]


def _identity_problems(document: NormalizedDocument) -> list[str]:
    info = document.document
    if is_unresolved(info.id):
        unsure = info.id_confidence in _UNSURE
        return [] if unsure else [f"document.id: unresolved ID with id_confidence {info.id_confidence.value!r}"]
    found = []
    if issuer_of(info.id) != info.issuer:
        found.append(f"document.issuer: {info.issuer!r} does not match the ID's issuer")
    if info.id_confidence in _UNSURE:
        found.append(f"document.id_confidence: {info.id_confidence.value!r} needs an unresolved ID")
    return found


def _duplicate_blob_problems(document: NormalizedDocument) -> list[str]:
    found = []
    for path, shas in (("files", [f.sha256 for f in document.files]), ("texts", [t.sha256 for t in document.texts])):
        found += [f"{path}[{i}].sha256: listed twice" for i, sha in enumerate(shas) if sha in shas[:i]]
    return found


def _text_reference_problems(document: NormalizedDocument) -> list[str]:
    file_shas = {f.sha256 for f in document.files}
    return [
        f"texts[{index}].of_file: {text.of_file[:12]}… is not one of this document's files"
        for index, text in enumerate(document.texts)
        if text.of_file is not None and text.of_file not in file_shas
    ]


def _provision_problems(document: NormalizedDocument) -> list[str]:
    found = []
    addresses = [p.address for p in document.provisions]
    text_shas = {t.sha256 for t in document.texts}
    for index, provision in enumerate(document.provisions):
        where = f"provisions[{index}]"
        if addresses.count(provision.address) > 1:
            found.append(f"{where}.address: {provision.address!r} is not unique")
        if provision.parent is not None and provision.parent not in addresses:
            found.append(f"{where}.parent: {provision.parent!r} is not a provision of this document")
        if provision.text not in text_shas:
            found.append(f"{where}.text: not one of this document's texts")
        if provision.char_start > provision.char_end:
            found.append(f"{where}: char range {provision.char_start}–{provision.char_end} is reversed")
    return found
