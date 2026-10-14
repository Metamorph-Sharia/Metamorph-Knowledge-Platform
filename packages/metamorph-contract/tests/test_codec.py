import json

import pytest
from metamorph_contract import ContractViolation, from_dict, from_json, to_json


def test_a_document_survives_a_json_round_trip(document) -> None:
    assert from_json(to_json(document)) == document


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
