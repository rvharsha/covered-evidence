"""The documented end-to-end workflow runs as written, so the quickstart cannot rot."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from covered_evidence.bundle.schema import Bundle
from covered_evidence.bundle.signing import PublicKeyVerifier, verify_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_the_workflow_example_signs_verifies_renders_diffs_and_amends(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = importlib.util.spec_from_file_location("workflow", ROOT / "examples" / "workflow.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main(tmp_path)

    key = PublicKeyVerifier((tmp_path / "issuer-public-key.pem").read_text())
    amended = Bundle.from_json((tmp_path / "build-1.amended.json").read_text())
    assert verify_bundle(amended, key)
    assert amended.amendments[-1].changes == [
        f"findings[{amended.findings[0].finding_id}].excerpt_redacted"
    ]
    assert (
        amended.amendments[-1].supersedes_sha256 in (tmp_path / "build-1.amended.html").read_text()
    )
    assert "->" in capsys.readouterr().out
