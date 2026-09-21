"""Diff between two bundles for the same chatbot."""

from __future__ import annotations

from dataclasses import dataclass, field

from covered_evidence.bundle.schema import (
    Bundle,
    ChangeCause,
    FindingStatus,
    Severity,
    VerificationMode,
    VerificationResult,
)


@dataclass(frozen=True)
class StatusChange:
    finding_id: str
    before: FindingStatus
    after: FindingStatus


@dataclass(frozen=True)
class SeverityChange:
    finding_id: str
    before: Severity
    after: Severity

    @property
    def downgraded(self) -> bool:
        """``Severity`` is declared most severe first."""
        order = list(Severity)
        return order.index(self.after) > order.index(self.before)


@dataclass(frozen=True)
class ConfirmationChange:
    """``human_confirmed`` differs between the two bundles for the same finding."""

    finding_id: str
    before: bool
    after: bool


@dataclass(frozen=True)
class BundleDiff:
    previous_build: str
    current_build: str
    status_changes: list[StatusChange]
    new_finding_ids: list[str]
    removed_finding_ids: list[str]
    severity_changes: list[SeverityChange]
    confirmation_changes: list[ConfirmationChange]
    verification: list[VerificationResult]
    incomplete_verification: list[str]
    target_changed: bool
    #: rubric, judge or scenario library: retained baseline evidence can be rescored with these
    measurement_changed: bool
    #: actor, adapter or scripts: how the evidence was acquired. Rescoring cannot separate this
    #: from a change in the target, so a status change across it is left unattributed.
    acquisition_changed: bool = False
    #: findings an earlier bundle had as not observed and this one carries as open with no new
    #: observation or reproduction: this build's verification could not be completed
    reopened_unverified: list[str] = field(default_factory=list)

    def verification_for(self, finding_id: str) -> list[VerificationResult]:
        return [v for v in self.verification if v.finding_id == finding_id]


def diff_bundles(prev: Bundle, curr: Bundle) -> BundleDiff:
    """Both bundles must be for the same operator and chatbot (principle 12): a diff across tenants
    would put one operator's findings in another's record, so it is refused, not computed."""
    for name in ("operator", "chatbot"):
        if getattr(prev, name) != getattr(curr, name):
            raise ValueError(
                f"cannot diff bundles for a different {name}: "
                f"{getattr(prev, name)!r} and {getattr(curr, name)!r}"
            )
    prev_by_id = {f.finding_id: f for f in prev.findings}
    changes: list[StatusChange] = []
    new_ids: list[str] = []
    severity_changes: list[SeverityChange] = []
    confirmation_changes: list[ConfirmationChange] = []
    reopened: list[str] = []
    for f in curr.findings:
        before = prev_by_id.get(f.finding_id)
        if before is None:
            new_ids.append(f.finding_id)
            continue
        if before.status is not f.status:
            changes.append(StatusChange(f.finding_id, before.status, f.status))
            if (
                before.status is FindingStatus.NOT_OBSERVED_IN_VERIFICATION
                and f.status is FindingStatus.OBSERVED
                and f.reproduction.acquisition_observations
                == before.reproduction.acquisition_observations
                and f.reproduction.reproductions == before.reproduction.reproductions
            ):
                reopened.append(f.finding_id)
        if before.severity is not f.severity:
            severity_changes.append(SeverityChange(f.finding_id, before.severity, f.severity))
        if before.human_confirmed is not f.human_confirmed:
            confirmation_changes.append(
                ConfirmationChange(f.finding_id, before.human_confirmed, f.human_confirmed)
            )
    current_ids = {f.finding_id for f in curr.findings}
    removed_ids = [f.finding_id for f in prev.findings if f.finding_id not in current_ids]

    verification = [v for v in curr.verification if v.against_build == prev.build.build_id]
    # a mode counts only when it was attempted and every attempt was graded: zero attempts, or
    # attempts withheld by the guard or a refusing evaluator, are not evidence of absence
    incomplete = [
        c.finding_id
        for c in changes
        if c.after is FindingStatus.NOT_OBSERVED_IN_VERIFICATION
        and {
            v.mode
            for v in verification
            if v.finding_id == c.finding_id and v.attempts > 0 and v.withheld == 0
        }
        != set(VerificationMode)
    ]

    pi, ci = prev.issuance, curr.issuance
    measurement_changed = (
        pi.rubric_version != ci.rubric_version
        or pi.judge_model != ci.judge_model
        or pi.scenario_library_version != ci.scenario_library_version
    )
    return BundleDiff(
        previous_build=prev.build.build_id,
        current_build=curr.build.build_id,
        status_changes=changes,
        new_finding_ids=new_ids,
        removed_finding_ids=removed_ids,
        severity_changes=severity_changes,
        confirmation_changes=confirmation_changes,
        verification=verification,
        incomplete_verification=incomplete,
        target_changed=prev.build.build_id != curr.build.build_id
        or prev.build.config_hash != curr.build.config_hash,
        measurement_changed=measurement_changed,
        acquisition_changed=pi.actor_model != ci.actor_model
        or pi.adapter_version != ci.adapter_version
        or pi.script_hashes != ci.script_hashes,
        reopened_unverified=reopened,
    )


def attribute_changes(
    diff: BundleDiff, *, rescored_previous: dict[str, FindingStatus] | None
) -> dict[str, ChangeCause]:
    """Attribute each status change to the target or to the measurement (principle 10).

    ``rescored_previous`` is the status each previous finding gets when its
    retained baseline evidence is re-graded with the current rubric and
    judge. It is required whenever the measurement changed.
    """
    if diff.measurement_changed and rescored_previous is None:
        raise ValueError("measurement changed between builds; baseline evidence must be rescored")
    out: dict[str, ChangeCause] = {}
    for c in diff.status_changes:
        if c.after in (FindingStatus.UNDER_REMEDIATION, FindingStatus.RISK_ACCEPTED):
            out[c.finding_id] = ChangeCause.OPERATOR_DECISION
        elif (
            c.finding_id in diff.incomplete_verification
            or c.finding_id in diff.reopened_unverified
            or diff.acquisition_changed
        ):
            # the move is not backed by verification against the compared build, the finding
            # was reopened because this build could not be verified (nothing was seen), or
            # the evidence was gathered differently; nothing here can credit the target
            out[c.finding_id] = ChangeCause.UNATTRIBUTED
        elif rescored_previous is None:
            out[c.finding_id] = ChangeCause.TARGET_BEHAVIOR
        elif c.finding_id not in rescored_previous:
            out[c.finding_id] = ChangeCause.UNATTRIBUTED
        elif rescored_previous[c.finding_id] != c.before:
            out[c.finding_id] = ChangeCause.MEASUREMENT
        else:
            out[c.finding_id] = ChangeCause.TARGET_BEHAVIOR
    return out
