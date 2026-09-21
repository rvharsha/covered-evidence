"""when the rubric or judge changes, baseline evidence is rescored and each
status change is attributed to target behavior or to measurement."""

from __future__ import annotations

from covered_evidence.bundle.diff import ChangeCause, attribute_changes, diff_bundles
from covered_evidence.bundle.schema import Bundle, FindingStatus
from tests.bundle.factories import bundle_from, finding_dict, minimal_bundle_dict


def _pair(rubric_changed: bool) -> tuple[Bundle, Bundle]:
    prev = minimal_bundle_dict()
    prev["findings"] = [finding_dict(finding_id="F-1"), finding_dict(finding_id="F-2")]
    curr = minimal_bundle_dict()
    curr["build"]["build_id"] = "b2"
    curr["findings"] = [
        finding_dict(finding_id="F-1", status="not_observed_in_verification"),
        finding_dict(finding_id="F-2", status="not_observed_in_verification"),
    ]
    curr["verification"] = [
        {
            "finding_id": fid,
            "against_build": "pip-2026.09.01",
            "mode": m,
            "attempts": 5,
            "reproductions": 0,
        }
        for fid in ("F-1", "F-2")
        for m in ("exact_replay", "adaptive_replay", "held_out_variation")
    ]
    if rubric_changed:
        curr["issuance"]["rubric_version"] = "rubric-v2"
    return bundle_from(prev), bundle_from(curr)


def test_without_a_measurement_change_every_change_is_target_behavior() -> None:
    prev, curr = _pair(rubric_changed=False)
    d = diff_bundles(prev, curr)
    causes = attribute_changes(d, rescored_previous=None)
    assert causes == {"F-1": ChangeCause.TARGET_BEHAVIOR, "F-2": ChangeCause.TARGET_BEHAVIOR}


def test_with_a_measurement_change_rescoring_is_required() -> None:
    import pytest

    prev, curr = _pair(rubric_changed=True)
    with pytest.raises(ValueError, match="rescored"):
        attribute_changes(diff_bundles(prev, curr), rescored_previous=None)


def test_rescored_baseline_that_no_longer_fails_is_a_measurement_change() -> None:
    prev, curr = _pair(rubric_changed=True)
    d = diff_bundles(prev, curr)
    rescored = {"F-1": FindingStatus.OBSERVED, "F-2": FindingStatus.NOT_OBSERVED_IN_VERIFICATION}
    causes = attribute_changes(d, rescored_previous=rescored)
    assert causes == {"F-1": ChangeCause.TARGET_BEHAVIOR, "F-2": ChangeCause.MEASUREMENT}
