import json
from dataclasses import replace

import pytest
from metamorph_contract import ContractViolation, Extraction, from_dict, from_json, to_json

EXTRACTION = Extraction("mineru", "4.0.12+t1", "standard", "txt", pages_ocrd=0, pages_fallen_back=2)


def with_extraction(document, extraction=EXTRACTION):
    (text,) = document.texts
    return replace(document, texts=(replace(text, extraction=extraction),))


def test_a_document_survives_a_json_round_trip(document) -> None:
    assert from_json(to_json(document)) == document


def test_how_a_text_was_read_survives_a_round_trip(document) -> None:
    read = with_extraction(document)

    assert from_json(to_json(read)).texts[0].extraction == EXTRACTION


def test_a_text_no_engine_read_has_no_extraction(document) -> None:
    assert json.loads(to_json(document))["texts"][0]["extraction"] is None


def test_a_contract_2_0_document_reads_as_it_did(document) -> None:
    data = json.loads(to_json(document))
    data["contract_version"] = "2.0"
    del data["texts"][0]["extraction"]

    parsed = from_dict(data)

    assert (parsed.contract_version, parsed.texts[0].extraction) == ("2.0", None)


@pytest.mark.parametrize(
    ("field", "value"),
    [("ocr_mode", "auto"), ("pages_ocrd", -1), ("engine", " "), ("tier", None)],
)
def test_a_malformed_extraction_is_refused(document, field, value) -> None:
    data = json.loads(to_json(with_extraction(document)))
    data["texts"][0]["extraction"][field] = value

    with pytest.raises(ContractViolation, match="extraction"):
        from_dict(data)


def test_optional_sections_may_be_left_out(document) -> None:
    data = json.loads(to_json(document))
    for optional in ("texts", "provisions", "citations", "source_fields"):
        del data[optional]

    parsed = from_dict(data)

    assert (parsed.texts, parsed.provisions, parsed.citations, parsed.source_fields) == ((), (), (), {})


@pytest.mark.parametrize(
    ("path", "value", "expected_problem"),
    [
        (("document", "kind"), "statute", "document.kind: 'statute' is not one of"),
        (("document", "year"), True, "document.year: True is not of type 'integer', 'null'"),
        (
            ("source", "fetched_at"),
            "2026-10-13T02:34:23",
            "source.fetched_at: '2026-10-13T02:34:23' is not a 'date-time'",
        ),
        (("files",), {}, "files: {} is not of type 'array'"),
    ],
)
def test_a_malformed_field_is_reported_with_its_path(document, path, value, expected_problem) -> None:
    data = json.loads(to_json(document))
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ContractViolation) as violation:
        from_dict(data)
    assert len(violation.value.problems) == 1
    assert violation.value.problems[0].startswith(expected_problem)


def test_every_problem_is_reported_at_once(document) -> None:
    data = json.loads(to_json(document))
    data["citations"][0]["relation"] = "cites"
    del data["source"]["connector"]
    data["unexpected"] = 1

    with pytest.raises(ContractViolation) as violation:
        from_dict(data)

    assert len(violation.value.problems) == 3
    assert any(p.startswith("citations[0].relation: 'cites' is not one of") for p in violation.value.problems)
    assert "source: 'connector' is a required property" in violation.value.problems
    assert any("'unexpected' was unexpected" in p for p in violation.value.problems)


def test_a_line_that_is_not_json_is_a_violation() -> None:
    with pytest.raises(ContractViolation, match="not JSON"):
        from_json("{broken")
