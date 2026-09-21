"""Finding status transitions (principle 6).

Severity and reproduction are separate fields on ``Finding``; a transition
never touches severity. A human-confirmed critical finding is never demoted
for failing to reproduce, and no finding reaches
``not_observed_in_verification`` without verification on a new build.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum

from covered_evidence.bundle.schema import Finding, FindingStatus, Severity


class TransitionBasis(StrEnum):
    VERIFIED_ON_NEW_BUILD = "verified_on_new_build"
    FAILED_TO_REPRODUCE = "failed_to_reproduce"
    REMEDIATION_STARTED = "remediation_started"
    RISK_ACCEPTED = "risk_accepted"


_REQUIRED_BASIS: dict[FindingStatus, frozenset[TransitionBasis]] = {
    FindingStatus.NOT_OBSERVED_IN_VERIFICATION: frozenset({TransitionBasis.VERIFIED_ON_NEW_BUILD}),
    FindingStatus.UNDER_REMEDIATION: frozenset({TransitionBasis.REMEDIATION_STARTED}),
    FindingStatus.RISK_ACCEPTED: frozenset({TransitionBasis.RISK_ACCEPTED}),
    FindingStatus.OBSERVED: frozenset(TransitionBasis),
}


def transition(finding: Finding, new_status: FindingStatus, basis: TransitionBasis) -> Finding:
    """Return a copy of ``finding`` in ``new_status`` if the transition is permitted."""
    if (
        finding.human_confirmed
        and finding.severity is Severity.CRITICAL
        and basis is TransitionBasis.FAILED_TO_REPRODUCE
        and new_status is not FindingStatus.OBSERVED
    ):
        raise ValueError(
            f"{finding.finding_id}: a human-confirmed critical finding is never demoted "
            "for failing to reproduce"
        )
    if (
        new_status is FindingStatus.NOT_OBSERVED_IN_VERIFICATION
        and basis is not TransitionBasis.VERIFIED_ON_NEW_BUILD
    ):
        raise ValueError(
            f"{finding.finding_id}: not_observed_in_verification requires verification "
            "on a new build"
        )
    if basis not in _REQUIRED_BASIS[new_status]:
        raise ValueError(
            f"{finding.finding_id}: {new_status.value} requires basis "
            f"{sorted(b.value for b in _REQUIRED_BASIS[new_status])}, got {basis.value}"
        )
    return dataclasses.replace(finding, status=new_status)
