"""Fourth pass: findings from the review of the stacked PRs (#7, #9, #12)."""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from covered_evidence.bundle.amend import amend
from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle, Severity
from covered_evidence.bundle.signing import HmacSigner, canonical_bytes, sign_bundle
from tests.bundle.factories import bundle_from, finding_dict, minimal_bundle_dict

SIGNER = HmacSigner(b"k1")
ROW = {
    "finding_id": "F-BR-001",
    "against_build": "pip-2026.09.02",
    "mode": "exact_replay",
    "attempts": 10,
    "reproductions": 7,
    "withheld": 0,
}


def _amend(bundle: Bundle, change):  # type: ignore[no-untyped-def]
    return amend(
        bundle, amendment_id="amd-1", issued_at="t", description="d", change=change, signer=SIGNER
    )


def _issued(**over):  # type: ignore[no-untyped-def]
    return sign_bundle(
        bundle_from({**minimal_bundle_dict(), "findings": [finding_dict()], **over}), SIGNER
    )


# --- the callback is handed a bundle it can reach into ------------------------------------------
def test_a_callback_that_lowers_a_finding_in_place_is_still_refused() -> None:
    """Frozen dataclasses hold mutable lists. The adversarial callback swaps the issued finding
    for a lowered copy inside the very bundle it was handed, then returns one allowed change."""
    before = _issued()

    def change(b: Bundle) -> Bundle:
        b.findings[0] = dataclasses.replace(b.findings[0], severity=Severity.LOW)
        return dataclasses.replace(b, open_risks=[*b.open_risks])

    with pytest.raises(ValueError, match="severity"):
        _amend(before, change)


def test_an_amendment_supersedes_the_bytes_that_were_verified_not_what_the_callback_left() -> None:
    before = _issued()
    signed = hashlib.sha256(canonical_bytes(before)).hexdigest()

    def change(b: Bundle) -> Bundle:
        b.findings[0] = dataclasses.replace(b.findings[0], excerpt_redacted="[target] corrected")
        return dataclasses.replace(b, findings=list(b.findings))

    after = _amend(before, change)
    assert after.amendments[-1].supersedes_sha256 == signed
    assert after.amendments[-1].changes == ["findings[F-BR-001].excerpt_redacted"]


# --- verification rows ---------------------------------------------------------------------------
def test_an_amendment_may_not_rewrite_the_counts_in_a_verification_row() -> None:
    before = _issued(verification=[ROW])
    emptied = dataclasses.replace(before.verification[0], attempts=1, reproductions=0)
    with pytest.raises(ValueError, match="verification"):
        _amend(before, lambda b: dataclasses.replace(b, verification=[emptied]))


def test_a_verification_row_must_name_a_finding_in_the_bundle() -> None:
    d = {**minimal_bundle_dict(), "findings": [finding_dict()]}
    d["verification"] = [{**ROW, "finding_id": "F-GHOST"}]
    with pytest.raises(ValueError, match="unknown finding"):
        bundle_from(d)


def test_two_verification_rows_for_one_finding_build_and_mode_are_refused() -> None:
    d = {**minimal_bundle_dict(), "findings": [finding_dict()]}
    d["verification"] = [ROW, {**ROW, "reproductions": 0}]
    with pytest.raises(ValueError, match="duplicate verification"):
        bundle_from(d)


# --- a future format is named as such ------------------------------------------------------------
@pytest.mark.parametrize("version", ["2", 2, None])
def test_a_document_in_another_schema_version_is_refused_by_version_not_by_shape(
    version: object,
) -> None:
    text = json.dumps({"schema_version": version, "records": []})
    with pytest.raises(ValueError, match="unsupported bundle schema version"):
        Bundle.from_json(text)


# --- what scope is missing, and why, is on the page a person reads -------------------------------
def test_the_render_gives_the_reason_for_a_cell_that_was_not_assessed() -> None:
    d = minimal_bundle_dict()
    d["coverage"]["outcomes"][1] = {
        "cell_id": "SN:13:direct:single",
        "terminal_state": "not_assessed",
        "reason": "operator withdrew the persona band before the run",
    }
    html = render_html(bundle_from(d))
    assert "operator withdrew the persona band before the run" in html
    assert "not assessed" in html
