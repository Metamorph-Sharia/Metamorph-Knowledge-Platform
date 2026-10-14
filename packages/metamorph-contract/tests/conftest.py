import pytest
from contract_samples import build_document
from metamorph_contract import NormalizedDocument


@pytest.fixture
def document() -> NormalizedDocument:
    return build_document()
