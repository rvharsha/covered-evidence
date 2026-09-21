"""verification results per mode, reported separately."""

from __future__ import annotations

import pytest

from covered_evidence.bundle.diff import ConfirmationChange, SeverityChange, diff_bundles
from covered_evidence.bundle.schema import Bundle, FindingStatus, Severity, VerificationMode
from tests.bundle.factories import bundle_from, finding_dict, minimal_bundle_dict


def _two_builds() -> tuple[Bundle, Bundle]:
    prev = minimal_bundle_dict()
    prev["findings"] = [finding_dict()]
    curr = minimal_bundle_dict()
    curr["build"]["build_id"] = "pip-2026.09.20"
    curr["findings"] = [finding_dict(status="not_observed_in_verification")]
    curr["verification"] = [
        {
            "finding_id": "F-BR-001",
            "against_build": "pip-2026.09.01",
            "mode": m,
            "attempts": n,
            "reproductions": 0,
        }
        for m, n in (("exact_replay", 20), ("adaptive_replay", 20), ("held_out_variation", 15))
    ]
    return bundle_from(prev), bundle_from(curr)


def test_diff_reports_a_status_change_per_finding() -> None:
    prev, curr = _two_builds()
    d = diff_bundles(prev, curr)
    assert [(c.finding_id, c.before, c.after) for c in d.status_changes] == [
        ("F-BR-001", FindingStatus.OBSERVED, FindingStatus.NOT_OBSERVED_IN_VERIFICATION)
    ]


def test_diff_reports_all_three_verification_modes_separately() -> None:
    prev, curr = _two_builds()
    d = diff_bundles(prev, curr)
    modes = {v.mode for v in d.verification_for("F-BR-001")}
    assert modes == set(VerificationMode)


def test_diff_flags_a_finding_moved_to_not_observed_without_all_three_modes() -> None:
    prev, curr = _two_builds()
    curr_d = curr.to_dict()
    # a bundle cannot hold the claim without three graded modes; here one of them replayed a
    # different baseline than the bundle it is compared with
    curr_d["verification"][2]["against_build"] = "pip-2026.08.01"
    d = diff_bundles(prev, bundle_from(curr_d))
    assert d.incomplete_verification == ["F-BR-001"]


def test_diff_separates_measurement_change_from_target_change() -> None:
    prev, curr = _two_builds()
    curr_d = curr.to_dict()
    curr_d["issuance"]["rubric_version"] = "rubric-v2"
    d = diff_bundles(prev, bundle_from(curr_d))
    assert d.measurement_changed is True
    assert d.target_changed is True


def test_diff_new_and_resolved_finding_ids() -> None:
    prev, curr = _two_builds()
    curr_d = curr.to_dict()
    curr_d["findings"].append(finding_dict(finding_id="F-SN-001", scenario="SN"))
    d = diff_bundles(prev, bundle_from(curr_d))
    assert d.new_finding_ids == ["F-SN-001"]


@pytest.mark.parametrize(
    ("field", "other"),
    [("operator", "Larkspur Learning (fictional)"), ("chatbot", "Wren")],
)
def test_diff_refuses_a_bundle_from_a_different_operator_or_chatbot(field: str, other: str) -> None:
    """Rule 12: one operator's evidence never appears in a diff against another's."""
    prev, curr = _two_builds()
    foreign = curr.to_dict()
    foreign[field] = other
    with pytest.raises(ValueError, match=f"different {field}"):
        diff_bundles(prev, bundle_from(foreign))


def test_diff_lists_findings_removed_between_builds() -> None:
    """A finding that is simply absent from the later bundle is a change the diff must show."""
    prev, curr = _two_builds()
    curr_d = curr.to_dict()
    curr_d["findings"] = []
    curr_d["verification"] = []  # rows must name a finding in the bundle
    d = diff_bundles(prev, bundle_from(curr_d))
    assert d.removed_finding_ids == ["F-BR-001"]


def test_diff_has_no_removed_findings_when_every_finding_is_carried_forward() -> None:
    prev, curr = _two_builds()
    assert diff_bundles(prev, curr).removed_finding_ids == []


def test_diff_reports_a_severity_downgrade() -> None:
    prev, curr = _two_builds()
    curr_d = curr.to_dict()
    curr_d["findings"] = [finding_dict(severity="low")]
    d = diff_bundles(prev, bundle_from(curr_d))
    assert d.severity_changes == [SeverityChange("F-BR-001", Severity.HIGH, Severity.LOW)]
    assert d.severity_changes[0].downgraded is True


def test_a_severity_raised_between_builds_is_reported_and_is_not_a_downgrade() -> None:
    prev, curr = _two_builds()
    curr_d = curr.to_dict()
    curr_d["findings"] = [finding_dict(severity="critical")]
    (change,) = diff_bundles(prev, bundle_from(curr_d)).severity_changes
    assert (change.before, change.after, change.downgraded) == (
        Severity.HIGH,
        Severity.CRITICAL,
        False,
    )


def test_diff_reports_human_confirmation_withdrawn() -> None:
    prev, curr = _two_builds()
    curr_d = curr.to_dict()
    curr_d["findings"] = [finding_dict(human_confirmed=False)]
    d = diff_bundles(prev, bundle_from(curr_d))
    assert d.confirmation_changes == [ConfirmationChange("F-BR-001", before=True, after=False)]


def test_unchanged_severity_and_confirmation_report_no_change() -> None:
    prev, curr = _two_builds()
    d = diff_bundles(prev, curr)
    assert (d.severity_changes, d.confirmation_changes) == ([], [])
