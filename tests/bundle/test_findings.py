"""severity and reproduction are separate; no demotion on reproduction grounds."""

from __future__ import annotations

import dataclasses

import pytest

from covered_evidence.bundle.findings import TransitionBasis, transition
from covered_evidence.bundle.schema import Finding, FindingStatus, Severity
from tests.bundle.factories import finding_dict


def _finding(**overrides: object) -> Finding:
    return Finding.from_dict(finding_dict(**overrides))


def test_severity_and_reproduction_are_distinct_fields() -> None:
    names = {f.name for f in dataclasses.fields(Finding)}
    assert {"severity", "reproduction"} <= names


def test_human_confirmed_critical_is_not_demoted_for_failing_to_reproduce() -> None:
    f = _finding(severity="critical", human_confirmed=True)
    with pytest.raises(ValueError, match="human-confirmed critical"):
        transition(
            f, FindingStatus.NOT_OBSERVED_IN_VERIFICATION, TransitionBasis.FAILED_TO_REPRODUCE
        )


def test_no_finding_reaches_not_observed_without_a_new_build() -> None:
    f = _finding(severity="low", human_confirmed=False)
    with pytest.raises(ValueError, match="new build"):
        transition(
            f, FindingStatus.NOT_OBSERVED_IN_VERIFICATION, TransitionBasis.FAILED_TO_REPRODUCE
        )


def test_verification_on_a_new_build_moves_a_finding_to_not_observed() -> None:
    f = _finding(severity="critical", human_confirmed=True)
    out = transition(
        f, FindingStatus.NOT_OBSERVED_IN_VERIFICATION, TransitionBasis.VERIFIED_ON_NEW_BUILD
    )
    assert out.status is FindingStatus.NOT_OBSERVED_IN_VERIFICATION
    assert out.severity is Severity.CRITICAL, "severity is untouched by a status transition"


def test_transition_returns_a_new_finding_and_leaves_the_original_unchanged() -> None:
    f = _finding()
    out = transition(f, FindingStatus.UNDER_REMEDIATION, TransitionBasis.REMEDIATION_STARTED)
    assert f.status is FindingStatus.OBSERVED
    assert out.status is FindingStatus.UNDER_REMEDIATION


def test_risk_accepted_requires_the_risk_accepted_basis() -> None:
    f = _finding()
    with pytest.raises(ValueError, match="risk_accepted"):
        transition(f, FindingStatus.RISK_ACCEPTED, TransitionBasis.REMEDIATION_STARTED)


def test_reproduction_counts_acquisition_separately_from_attempts() -> None:
    f = _finding(reproduction={"acquisition_observations": 2, "attempts": 10, "reproductions": 3})
    assert f.reproduction.acquisition_observations == 2
    assert f.reproduction.attempts == 10
    assert f.reproduction.reproductions == 3
