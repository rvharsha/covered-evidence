"""Fifth pass: an outside review of the extracted open repo. Each test is one of its findings:
what the record claims and what it measured must agree, and a correction is visible."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from covered_evidence.bundle.amend import amend
from covered_evidence.bundle.diff import attribute_changes, diff_bundles
from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle, ChangeCause, Severity
from covered_evidence.bundle.signing import HmacSigner, sign_bundle, verify_bundle
from tests.bundle.factories import bundle_from, finding_dict, minimal_bundle_dict

SIGNER = HmacSigner(b"k1")
MODES = ("exact_replay", "adaptive_replay", "held_out_variation")


def _rows(attempts: int, reproductions: int, withheld: int) -> list[dict[str, Any]]:
    return [
        {
            "finding_id": "F-BR-001",
            "against_build": "pip-2026.09.01",
            "mode": m,
            "attempts": attempts,
            "reproductions": reproductions,
            "withheld": withheld,
        }
        for m in MODES
    ]


def _two_builds(rows: list[dict[str, Any]], **issuance: Any) -> tuple[Bundle, Bundle]:
    prev = minimal_bundle_dict()
    prev["findings"] = [finding_dict()]
    curr = minimal_bundle_dict()
    curr["build"]["build_id"] = "pip-2026.09.20"
    curr["findings"] = [finding_dict(status="not_observed_in_verification")]
    curr["verification"] = rows
    curr["issuance"].update(issuance)
    return bundle_from(prev), bundle_from(curr)


# --- 1: "not observed" needs graded attempts behind it -------------------------------------------
def test_a_finding_that_reproduced_cannot_be_recorded_as_not_observed() -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(status="not_observed_in_verification")]
    d["verification"] = _rows(5, 5, 0)
    with pytest.raises(ValueError, match="reproduced"):
        bundle_from(d)


# --- 4: counts and rates that cannot be -----------------------------------------------------------
@pytest.mark.parametrize(
    "row",
    [
        {"attempts": -1},
        {"reproductions": 42},
        {"withheld": -3},
        {"attempts": 5, "reproductions": 3, "withheld": 3},
    ],
)
def test_a_verification_row_with_impossible_counts_is_refused(row: dict[str, int]) -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict()]
    d["verification"] = [{**_rows(5, 0, 0)[0], **row}]
    with pytest.raises(ValueError, match="verification of F-BR-001"):
        bundle_from(d)


@pytest.mark.parametrize(
    "reproduction",
    [
        {"acquisition_observations": -1, "attempts": 0, "reproductions": 0},
        {"acquisition_observations": 1, "attempts": 2, "reproductions": 3},
    ],
)
def test_a_finding_with_impossible_reproduction_counts_is_refused(
    reproduction: dict[str, int],
) -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(reproduction=reproduction)]
    with pytest.raises(ValueError, match="reproduction"):
        bundle_from(d)


def _calibration(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "category": "SN",
        "positives": 10,
        "negatives": 10,
        "precision": 0.9,
        "recall": 0.8,
        "precision_ci_low": 0.7,
        "precision_ci_high": 0.95,
        "recall_ci_low": 0.6,
        "recall_ci_high": 0.9,
        "meets_gate": True,
        "issuance_path": "judge_met_gate",
        "judge_model": "family-b/judge-1",
        "rubric_version": "rubric-v1",
    }
    return {**base, **over}


@pytest.mark.parametrize(
    "over",
    [
        {"positives": -1},
        {"precision": 2.0},
        {"recall": -1.0},
        {"precision_ci_low": 0.96},  # above the high bound
        {"meets_gate": False},  # yet issued on the judge path
    ],
)
def test_a_calibration_record_that_cannot_be_true_is_refused(over: dict[str, Any]) -> None:
    d = minimal_bundle_dict()
    d["methodology"]["calibration"] = [_calibration(**over)]
    with pytest.raises(ValueError, match="calibration for SN"):
        bundle_from(d)


# --- 5, 6, 7: amendments --------------------------------------------------------------------------
def _amend(bundle: Bundle, change):  # type: ignore[no-untyped-def]
    return amend(
        bundle, amendment_id="amd-1", issued_at="t", description="d", change=change, signer=SIGNER
    )


def test_an_amendment_may_not_remove_or_rewrite_a_change_attribution() -> None:
    d = {**minimal_bundle_dict(), "findings": [finding_dict()]}
    d["change_attribution"] = [{"finding_id": "F-BR-001", "cause": "measurement", "note": "v2"}]
    before = sign_bundle(bundle_from(d), SIGNER)
    with pytest.raises(ValueError, match="change attribution"):
        _amend(before, lambda b: dataclasses.replace(b, change_attribution=[]))
    rewritten = dataclasses.replace(before.change_attribution[0], cause=ChangeCause.TARGET_BEHAVIOR)
    with pytest.raises(ValueError, match="change attribution"):
        _amend(before, lambda b: dataclasses.replace(b, change_attribution=[rewritten]))


def test_one_finding_has_one_change_attribution() -> None:
    d = {**minimal_bundle_dict(), "findings": [finding_dict()]}
    d["change_attribution"] = [
        {"finding_id": "F-BR-001", "cause": "measurement", "note": ""},
        {"finding_id": "F-BR-001", "cause": "target_behavior", "note": ""},
    ]
    with pytest.raises(ValueError, match="duplicate change_attribution"):
        bundle_from(d)


def test_the_render_shows_what_an_amendment_changed_and_what_it_superseded() -> None:
    before = sign_bundle(
        bundle_from({**minimal_bundle_dict(), "findings": [finding_dict()]}), SIGNER
    )
    corrected = dataclasses.replace(before.findings[0], excerpt_redacted="[target] corrected")
    after = _amend(before, lambda b: dataclasses.replace(b, findings=[corrected]))
    html = render_html(after)
    assert "findings[F-BR-001].excerpt_redacted" in html
    assert after.amendments[0].supersedes_sha256 in html


@pytest.mark.parametrize("allowed", [True, False])
def test_the_callers_bundle_is_untouched_whether_or_not_the_amendment_is_accepted(
    allowed: bool,
) -> None:
    before = sign_bundle(
        bundle_from({**minimal_bundle_dict(), "findings": [finding_dict()]}), SIGNER
    )

    def change(b: Bundle) -> Bundle:
        if allowed:
            b.findings[0] = dataclasses.replace(b.findings[0], excerpt_redacted="[target] fixed")
        else:
            b.findings[0] = dataclasses.replace(b.findings[0], severity=Severity.LOW)
        return dataclasses.replace(b, findings=list(b.findings))

    if allowed:
        _amend(before, change)
    else:
        with pytest.raises(ValueError, match="severity"):
            _amend(before, change)
    assert before.findings[0].severity is Severity.HIGH
    assert before.findings[0].excerpt_redacted.endswith("stay a little longer with me.")
    assert verify_bundle(before, SIGNER)


# --- 11: what was measured with a different instrument is not credited to the target -------------
@pytest.mark.parametrize(
    "pin",
    [
        {"actor_model": "family-a/actor-2"},
        {"adapter_version": "mode-b-0.0.2"},
        {"script_hashes": ["sha256:" + "a" * 64]},
    ],
)
def test_a_changed_actor_adapter_or_script_is_not_attributed_to_the_target(
    pin: dict[str, Any],
) -> None:
    prev, curr = _two_builds(_rows(5, 0, 0), **pin)
    diff = diff_bundles(prev, curr)
    assert diff.acquisition_changed is True
    assert attribute_changes(diff, rescored_previous=None) == {"F-BR-001": ChangeCause.UNATTRIBUTED}


def test_with_every_pin_unchanged_a_status_change_is_the_targets() -> None:
    prev, curr = _two_builds(_rows(5, 0, 0))
    diff = diff_bundles(prev, curr)
    assert (diff.acquisition_changed, diff.measurement_changed) == (False, False)
    assert attribute_changes(diff, rescored_previous=None) == {
        "F-BR-001": ChangeCause.TARGET_BEHAVIOR
    }


@pytest.mark.parametrize("status", ["under_remediation", "risk_accepted"])
def test_a_status_the_operator_decided_is_not_attributed_to_target_behavior(status: str) -> None:
    """Remediation started, or a risk accepted, is a decision someone recorded. No test observed
    the target do anything, so neither the target nor the measurement is given as the cause."""
    prev = minimal_bundle_dict()
    prev["findings"] = [finding_dict()]
    curr = minimal_bundle_dict()
    curr["build"]["build_id"] = "pip-2026.09.20"
    curr["findings"] = [finding_dict(status=status)]
    diff = diff_bundles(bundle_from(prev), bundle_from(curr))
    assert attribute_changes(diff, rescored_previous=None) == {
        "F-BR-001": ChangeCause.OPERATOR_DECISION
    }


# --- second review of this change: the claim needs its evidence in the same bundle ---------------
def _not_observed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(status="not_observed_in_verification")]
    d["verification"] = rows
    return d


@pytest.mark.parametrize(
    "rows",
    [[], _rows(0, 0, 0), _rows(5, 0, 5), _rows(5, 0, 1), _rows(5, 0, 0)[:2]],
    ids=["no rows", "zero attempts", "all withheld", "one withheld", "two modes"],
)
def test_not_observed_is_refused_without_three_fully_graded_modes_in_the_same_bundle(
    rows: list[dict[str, Any]],
) -> None:
    with pytest.raises(ValueError, match="not_observed_in_verification"):
        bundle_from(_not_observed(rows))
    # and so it can never be signed
    assert sign_bundle(bundle_from(_not_observed(_rows(5, 0, 0))), SIGNER).issuance.signature


def test_a_move_to_not_observed_verified_against_another_build_is_not_the_targets() -> None:
    """The rows are complete, so the bundle loads, but they replay a different baseline than
    the bundle being compared with. The diff flags it; attribution must not contradict it."""
    prev, curr = _two_builds([{**r, "against_build": "pip-2026.08.01"} for r in _rows(5, 0, 0)])
    diff = diff_bundles(prev, curr)
    assert diff.incomplete_verification == ["F-BR-001"]
    assert attribute_changes(diff, rescored_previous=None) == {"F-BR-001": ChangeCause.UNATTRIBUTED}


def test_a_finding_reopened_without_a_new_observation_is_not_the_targets_regression() -> None:
    """The earlier bundle said not observed; this build's verification could not be completed,
    so the finding is carried as open. Nothing was seen: no cause is claimed."""
    prev = _not_observed(_rows(5, 0, 0))
    curr = minimal_bundle_dict()
    curr["build"]["build_id"] = "pip-2026.09.20"
    curr["findings"] = [finding_dict()]  # observed again, with the same counts as before
    diff = diff_bundles(bundle_from(prev), bundle_from(curr))
    assert diff.reopened_unverified == ["F-BR-001"]
    assert attribute_changes(diff, rescored_previous=None) == {"F-BR-001": ChangeCause.UNATTRIBUTED}


def test_a_finding_seen_again_is_the_targets_regression() -> None:
    prev = _not_observed(_rows(5, 0, 0))
    curr = minimal_bundle_dict()
    curr["build"]["build_id"] = "pip-2026.09.20"
    seen_again = {"acquisition_observations": 2, "attempts": 0, "reproductions": 0}
    curr["findings"] = [finding_dict(reproduction=seen_again)]
    diff = diff_bundles(bundle_from(prev), bundle_from(curr))
    assert diff.reopened_unverified == []
    assert attribute_changes(diff, rescored_previous=None) == {
        "F-BR-001": ChangeCause.TARGET_BEHAVIOR
    }
