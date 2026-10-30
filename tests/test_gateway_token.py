"""The development endpoint's token check (deploy/aws/dev/retrieval.yaml): CloudFront's viewer-request function, the
template's own code, run in Node as CloudFront runs it."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

TEMPLATE = Path(__file__).parents[1] / "deploy/aws/dev/retrieval.yaml"
TOKEN = "a-development-token"
NODE = shutil.which("node")
UNAUTHORIZED = 401

pytestmark = pytest.mark.skipif(NODE is None, reason="CloudFront Functions are JavaScript: needs Node")


class _Template(yaml.SafeLoader):
    """Reads CloudFormation's short tags (!Sub, !Ref, …) as the plain values they wrap."""


def _untagged(loader: yaml.Loader, _tag: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_Template.add_multi_constructor("!", _untagged)


def function_code() -> str:
    template = yaml.load(TEMPLATE.read_text(), Loader=_Template)
    code = template["Resources"]["TokenCheck"]["Properties"]["FunctionCode"]
    return code.replace("${TokenSha256}", hashlib.sha256(TOKEN.encode()).hexdigest())


def viewer_request(headers: dict[str, str]) -> dict:
    event = {"request": {"method": "POST", "uri": "/mcp", "headers": {k: {"value": v} for k, v in headers.items()}}}
    script = f"{function_code()}\nconsole.log(JSON.stringify(handler({json.dumps(event)})));"
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)


def test_the_right_token_passes_and_stays_at_the_edge() -> None:
    request = viewer_request({"authorization": f"Bearer {TOKEN}"})
    assert request["uri"] == "/mcp"
    assert "authorization" not in request["headers"]


def test_the_scheme_is_read_in_any_case() -> None:
    assert viewer_request({"authorization": f"bearer {TOKEN}"})["uri"] == "/mcp"


def test_a_wrong_token_is_refused() -> None:
    assert viewer_request({"authorization": "Bearer a-guess"})["statusCode"] == UNAUTHORIZED


def test_no_token_is_refused() -> None:
    assert viewer_request({})["statusCode"] == UNAUTHORIZED
