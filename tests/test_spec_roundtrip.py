"""The spec is the contract: the generated OpenAPI must stay in semantic parity."""

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def _load_spec_diff():
    spec = importlib.util.spec_from_file_location("spec_diff", REPO / "scripts" / "spec_diff.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["spec_diff"] = module
    spec.loader.exec_module(module)
    return module


def test_openapi_round_trips_against_spec():
    spec_diff = _load_spec_diff()
    spec_doc = yaml.safe_load((REPO / "docs" / "agent_os_openapi.yaml").read_text(encoding="utf-8"))

    from enos.api.app import app

    findings = spec_diff.compare(spec_doc, app.openapi())
    assert findings == [], "spec drift:\n" + "\n".join(findings)


def test_spec_has_all_operations():
    spec_diff = _load_spec_diff()
    spec_doc = yaml.safe_load((REPO / "docs" / "agent_os_openapi.yaml").read_text(encoding="utf-8"))
    ops = spec_diff.norm_doc(spec_doc)
    assert len(ops) == 45  # every /v1 operation in the Phase 0 contract
