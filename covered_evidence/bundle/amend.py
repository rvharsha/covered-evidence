"""Amendments: the only way an issued bundle changes (principle 10).

An amendment corrects the record; it does not rewrite what was found or who it was about. The
change is a callable, so everything it could do is checked here rather than trusted.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
from collections.abc import Callable
from typing import Any

from covered_evidence.bundle.coverage import check_coverage
from covered_evidence.bundle.schema import Amendment, Bundle, Finding, FindingStatus, Severity
from covered_evidence.bundle.signing import Signer, canonical_bytes, sign_bundle, verify_bundle

_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}
#: Identity and scope: what the bundle is about and what it claims to have tested.
_PINNED = ("schema_version", "bundle_id", "operator", "chatbot", "build", "cover", "methodology")


def _check_finding(before: Finding, after: Finding) -> None:
    fid = before.finding_id
    for name in ("scenario", "citation", "level", "ladder", "rung", "persona_band", "seeds"):
        if getattr(before, name) != getattr(after, name):
            raise ValueError(f"an amendment may not change {name} of finding {fid}")
    for count in dataclasses.fields(before.reproduction):
        if getattr(after.reproduction, count.name) < getattr(before.reproduction, count.name):
            raise ValueError(f"an amendment may not lower {count.name} of finding {fid}")
    if _RANK[after.severity] < _RANK[before.severity]:
        raise ValueError(f"an amendment may not lower the severity of finding {fid} (principle 6)")
    if before.human_confirmed and not after.human_confirmed:
        raise ValueError(f"an amendment may not un-confirm finding {fid} (principle 6)")
    if (
        after.status is FindingStatus.NOT_OBSERVED_IN_VERIFICATION
        and before.status is not FindingStatus.NOT_OBSERVED_IN_VERIFICATION
    ):
        raise ValueError(
            f"finding {fid}: not_observed_in_verification requires verification on a new build, "
            "which is a new bundle, not an amendment"
        )


def _check(before: Bundle, after: Bundle) -> None:
    for name in _PINNED:
        if getattr(before, name) != getattr(after, name):
            raise ValueError(f"an amendment may not change {name}")
    if after.amendments != before.amendments:
        raise ValueError("an amendment may not alter earlier amendments")
    pins_before = dataclasses.replace(before.issuance, signature=None, key_id=None)
    pins_after = dataclasses.replace(after.issuance, signature=None, key_id=None)
    if pins_before != pins_after:
        raise ValueError("an amendment may not change the issuance snapshot pins")
    # findings are appended, never inserted ahead of or reordered among the issued ones: a
    # reader meets the issued findings first, in the order they were issued
    issued = [f.finding_id for f in before.findings]
    if [f.finding_id for f in after.findings][: len(issued)] != issued:
        raise ValueError("an amendment may not remove findings or change their order")
    # a verification row is a measurement taken on a build: an amendment may add one, never
    # remove or rewrite one
    for v in before.verification:
        if v not in after.verification:
            raise ValueError(
                f"an amendment may not remove or rewrite the verification of {v.finding_id}"
            )
    # why a status changed is part of the record: an attribution may be added, never removed
    # or rewritten (the explanation that an improvement came from the measurement stays)
    for row in before.change_attribution:
        if row not in after.change_attribution:
            raise ValueError(
                f"an amendment may not remove or rewrite the change attribution of {row.finding_id}"
            )
    kept = {f.finding_id: f for f in after.findings}
    for f in before.findings:
        if f.finding_id not in kept:
            raise ValueError(f"an amendment may not remove finding {f.finding_id}")
        _check_finding(f, kept[f.finding_id])
    # An amendment corrects the record. It never upgrades the evidence: what was blocked, not
    # assessed or attested stays so until a new run on a new bundle says otherwise (principle 5).
    cited = {r.citation: r for r in after.requirements}
    for r in before.requirements:
        if r.citation not in cited:
            raise ValueError(f"an amendment may not remove requirement {r.citation}")
        if cited[r.citation].status is not r.status:
            raise ValueError(
                f"an amendment may not change the evidence status of {r.citation}; "
                "a new status needs a new bundle"
            )
    if set(before.coverage.planned_cells) != set(after.coverage.planned_cells):
        raise ValueError("an amendment may not add or remove planned cells")
    outcomes = {o.cell_id: o for o in after.coverage.outcomes}
    for o in before.coverage.outcomes:
        if o.cell_id not in outcomes or outcomes[o.cell_id].terminal_state is not o.terminal_state:
            raise ValueError(f"an amendment may not change the terminal state of cell {o.cell_id}")
    risks = {r.risk_id for r in after.open_risks}
    for risk in before.open_risks:
        if risk.risk_id not in risks:
            raise ValueError(f"an amendment may not remove open risk {risk.risk_id}")
    check_coverage(after.coverage)


def _leaf_changes(path: str, a: Any, b: Any, out: list[str]) -> None:
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            _leaf_changes(f"{path}.{key}" if path else key, a.get(key), b.get(key), out)
    else:
        out.append(path)


def _changes(before: Bundle, after: Bundle) -> list[str]:
    """What actually differs, keyed by finding id and citation rather than list position."""
    a, b = before.to_dict(), after.to_dict()
    out: list[str] = []
    keyed = (
        ("findings", "finding_id", a, b),
        ("requirements", "citation", a, b),
        ("open_risks", "risk_id", a, b),
        ("coverage.outcomes", "cell_id", a["coverage"], b["coverage"]),
    )
    for name, key, da, db in keyed:
        leaf = name.rpartition(".")[2]
        rows_a = {r[key]: r for r in da.pop(leaf)}
        rows_b = {r[key]: r for r in db.pop(leaf)}
        for ident in sorted(set(rows_a) | set(rows_b)):
            _leaf_changes(f"{name}[{ident}]", rows_a.get(ident, {}), rows_b.get(ident, {}), out)
    for d in (a, b):
        d.pop("amendments")
        d["issuance"] = {}
    _leaf_changes("", a, b, out)
    return out


def amend(
    bundle: Bundle,
    *,
    amendment_id: str,
    issued_at: str,
    description: str,
    change: Callable[[Bundle], Bundle],
    signer: Signer,
) -> Bundle:
    if bundle.issuance.signature is None:
        raise ValueError("cannot amend an unsigned bundle; issue it first")
    if not verify_bundle(bundle, signer):
        raise ValueError("bundle signature does not verify; it was altered outside an amendment")
    if any(a.amendment_id == amendment_id for a in bundle.amendments):
        raise ValueError(f"amendment {amendment_id} already exists on {bundle.bundle_id}")
    # The dataclasses are frozen but their lists are not: a callback could alter the bundle it
    # was handed and be compared with its own alteration. Everything below reads this copy,
    # taken after the signature verified and before the callback ran.
    # The callback works on a copy of its own, so the caller's issued bundle is as it was
    # whether the amendment is accepted or refused.
    verified = copy.deepcopy(bundle)
    changed = change(copy.deepcopy(bundle))
    bundle = verified
    _check(bundle, changed)
    changes = _changes(bundle, changed)
    if not changes:
        raise ValueError("an amendment that changes nothing is refused; there is nothing to record")
    record = Amendment(
        amendment_id=amendment_id,
        issued_at=issued_at,
        description=description,
        supersedes_sha256=hashlib.sha256(canonical_bytes(bundle)).hexdigest(),
        changes=changes,
    )
    unsigned = dataclasses.replace(
        changed,
        amendments=[*changed.amendments, record],
        issuance=dataclasses.replace(changed.issuance, signature=None),
    )
    return sign_bundle(unsigned, signer)
