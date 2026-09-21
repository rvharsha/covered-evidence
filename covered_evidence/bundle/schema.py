"""The bundle data model. Vocabulary is fixed; see the README.

There is deliberately no field anywhere in this model that can hold a legal
conclusion. Release decisions live outside the bundle.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from covered_evidence.bundle import codec
from covered_evidence.scenarios import EvidenceStatus

__all__ = [
    "Amendment",
    "BuildIdentity",
    "Bundle",
    "CalibrationRecord",
    "CellOutcome",
    "CellTerminalState",
    "ChangeAttribution",
    "ChangeCause",
    "Cover",
    "Coverage",
    "EvidenceStatus",
    "Finding",
    "FindingLevel",
    "FindingStatus",
    "Issuance",
    "IssuancePath",
    "JudgeInfo",
    "Methodology",
    "OpenRisk",
    "Reproduction",
    "RequirementStatus",
    "Seeds",
    "Severity",
    "VerificationMode",
    "VerificationResult",
    "bundle_json_schema",
]


class FindingStatus(StrEnum):
    OBSERVED = "observed"
    UNDER_REMEDIATION = "under_remediation"
    NOT_OBSERVED_IN_VERIFICATION = "not_observed_in_verification"
    RISK_ACCEPTED = "risk_accepted"


class FindingLevel(StrEnum):
    OUTPUT = "output"
    CONVERSATION = "conversation"
    ACCOUNT_TIMELINE = "account_timeline"


class VerificationMode(StrEnum):
    EXACT_REPLAY = "exact_replay"
    ADAPTIVE_REPLAY = "adaptive_replay"
    HELD_OUT_VARIATION = "held_out_variation"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CellTerminalState(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    NOT_ASSESSED = "not_assessed"


class ChangeCause(StrEnum):
    """Why a finding's status differs from the prior bundle (principle 10)."""

    TARGET_BEHAVIOR = "target_behavior"
    MEASUREMENT = "measurement"
    UNATTRIBUTED = "unattributed"
    #: remediation started or a risk accepted: someone recorded a decision; no test observed it
    OPERATOR_DECISION = "operator_decision"


class IssuancePath(StrEnum):
    """Which calibration path applied."""

    JUDGE_MET_GATE = "judge_met_gate"
    FULLY_HUMAN_REVIEWED = "fully_human_reviewed"
    REVIEW_PENDING = "review_pending"  # neither path satisfied yet; the bundle says so


class _Model:
    @classmethod
    def from_dict(cls, data: Any) -> Any:
        return codec.from_dict(cls, data)

    @classmethod
    def from_json(cls, text: str) -> Any:
        """The only way to read evidence from a file: duplicate keys and non-finite numbers are
        refused (see ``codec.loads_strict``), then every field is required and type-checked."""
        data = codec.loads_strict(text)
        if cls is Bundle:
            # before the shape is read: a later format fails as a later format, not as a
            # version-1 document with fields missing
            _check_version(data.get("schema_version") if isinstance(data, dict) else None)
        return codec.from_dict(cls, data)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = codec.to_dict(self)
        return out


@dataclass(frozen=True)
class BuildIdentity(_Model):
    build_id: str
    config_hash: str
    captured_at: str


@dataclass(frozen=True)
class Cover(_Model):
    """Tested scope, first page of the bundle."""

    scenarios_exercised: list[str]
    scenarios_not_exercised: list[str]
    persona_bands_exercised: list[str]
    framings_exercised: list[str]
    persistence_exercised: list[str]


@dataclass(frozen=True)
class RequirementStatus(_Model):
    citation: str
    status: EvidenceStatus
    note: str = ""


@dataclass(frozen=True)
class Reproduction(_Model):
    """Acquisition observations and reproduction attempts are counted separately."""

    acquisition_observations: int
    attempts: int
    reproductions: int

    def __post_init__(self) -> None:
        if min(self.acquisition_observations, self.attempts, self.reproductions) < 0:
            raise ValueError("reproduction counts cannot be negative")
        if self.reproductions > self.attempts:
            raise ValueError("reproduction counts: more reproductions than attempts")


@dataclass(frozen=True)
class Seeds(_Model):
    actor: int | None
    director: int | None
    target: int | None

    def with_target(self, target: int | None) -> Seeds:
        return Seeds(actor=self.actor, director=self.director, target=target)


@dataclass(frozen=True)
class Finding(_Model):
    finding_id: str
    scenario: str
    citation: str
    level: FindingLevel
    status: FindingStatus
    severity: Severity
    human_confirmed: bool
    ladder: str
    rung: int
    persona_band: str
    excerpt_redacted: str
    review_disposition: str
    reproduction: Reproduction
    seeds: Seeds
    related_findings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # The excerpt is exempt from the legal-conclusion lint because it quotes the target and
        # the simulated user. That exemption is for a quotation, not for prose at length.
        if len(self.excerpt_redacted) > MAX_EXCERPT_CHARS:
            raise ValueError(
                f"finding {self.finding_id}: excerpt_redacted is {len(self.excerpt_redacted)} "
                f"characters; an excerpt is at most {MAX_EXCERPT_CHARS}"
            )


@dataclass(frozen=True)
class VerificationResult(_Model):
    finding_id: str
    against_build: str
    mode: VerificationMode
    attempts: int
    reproductions: int
    withheld: int = 0  # attempts kept from grading by the guard or a refusing evaluator

    def __post_init__(self) -> None:
        if min(self.attempts, self.reproductions, self.withheld) < 0:
            raise ValueError(f"verification of {self.finding_id}: a count cannot be negative")
        if self.reproductions + self.withheld > self.attempts:
            raise ValueError(
                f"verification of {self.finding_id}: reproductions plus withheld exceed attempts"
            )


@dataclass(frozen=True)
class OpenRisk(_Model):
    risk_id: str
    description: str
    owner: str
    rationale: str


@dataclass(frozen=True)
class JudgeInfo(_Model):
    model_family: str
    version: str
    issuance_path: IssuancePath


@dataclass(frozen=True)
class CalibrationRecord(_Model):
    """Per-category judge calibration from held-out labels. Interval bounds are
    Wilson 95%. ``issuance_path`` is the path this category took in this bundle."""

    category: str
    positives: int
    negatives: int
    precision: float
    recall: float
    precision_ci_low: float
    precision_ci_high: float
    recall_ci_low: float
    recall_ci_high: float
    meets_gate: bool
    issuance_path: IssuancePath
    judge_model: str
    rubric_version: str

    def __post_init__(self) -> None:
        # Python accepts an int where a float is annotated; JSON then spells it `1`, which a
        # reader refuses in a float field. Store the float, so what is signed can be loaded.
        for name in _RATE_FIELDS:
            object.__setattr__(self, name, float(getattr(self, name)))
        what = f"calibration for {self.category}"
        if self.positives < 0 or self.negatives < 0:
            raise ValueError(f"{what}: a label count cannot be negative")
        for name in _RATE_FIELDS:
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{what}: {name} must be between 0 and 1")
        if (
            self.precision_ci_low > self.precision_ci_high
            or self.recall_ci_low > self.recall_ci_high
        ):
            raise ValueError(f"{what}: an interval's low bound is above its high bound")
        if self.issuance_path is IssuancePath.JUDGE_MET_GATE and not self.meets_gate:
            raise ValueError(f"{what}: issued on the judge path without meeting the gate")


@dataclass(frozen=True)
class Methodology(_Model):
    """Written to §21812(a)(1)(B)."""

    persona_matrix_rule: str
    ladders: list[str]
    benchmarks_consulted: list[str]
    non_benchmark_evaluation: str
    experts_consulted: list[str]
    judge: JudgeInfo
    content_guard: str = (
        "unconfigured"  # name of the local guard that screened replies (principle 2)
    )
    #: One entry per category with held-out labels; empty means no category was calibrated
    #: and every exercised category is on the human path or pending.
    calibration: list[CalibrationRecord] = field(default_factory=list)


@dataclass(frozen=True)
class CellOutcome(_Model):
    cell_id: str
    terminal_state: CellTerminalState
    reason: str = ""


@dataclass(frozen=True)
class Coverage(_Model):
    planned_cells: list[str]
    outcomes: list[CellOutcome]


@dataclass(frozen=True)
class Issuance(_Model):
    issued_at: str
    scenario_library_version: str
    rubric_version: str
    script_hashes: list[str]
    adapter_version: str
    actor_model: str
    judge_model: str
    transcript_hashes: list[str]
    review_decisions: int
    #: Who signed, inside the signed bytes: ``hmac-sha256`` or
    #: ``kms-ec-p256-sha256:<key version resource name>``. The signature string also names the
    #: key, but it is outside the signed bytes, so on its own that name proves nothing. Null
    #: exactly when the bundle is unsigned.
    key_id: str | None
    signature: str | None

    def __post_init__(self) -> None:
        _hashes("issuance.script_hashes", self.script_hashes)
        _hashes("issuance.transcript_hashes", self.transcript_hashes)


@dataclass(frozen=True)
class ChangeAttribution(_Model):
    finding_id: str
    cause: ChangeCause
    note: str = ""


@dataclass(frozen=True)
class Amendment(_Model):
    amendment_id: str
    issued_at: str
    description: str
    #: SHA-256 of the canonical bytes of the bundle this amendment replaced.
    supersedes_sha256: str
    #: Machine-generated list of what changed, e.g. ``findings[F-BR-001].review_disposition``.
    #: The description is a human's words; this is what the code saw.
    changes: list[str]

    def __post_init__(self) -> None:
        if not _HEX64.fullmatch(self.supersedes_sha256):
            raise ValueError("amendment.supersedes_sha256: expected 64 hex characters (sha256)")


#: The version of the signed bundle format this library writes and reads.
SCHEMA_VERSION = "1"

MAX_EXCERPT_CHARS = 8000
_RATE_FIELDS = (
    "precision",
    "recall",
    "precision_ci_low",
    "precision_ci_high",
    "recall_ci_low",
    "recall_ci_high",
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MINTED_ID = re.compile(r"[A-Za-z0-9._:/-]+")


def _check_identifier(what: str, value: str) -> None:
    """An identifier a reader cannot tell from another is the same identifier. So an id must be
    exactly what it looks like: non-empty, already NFKC (no fullwidth or compatibility forms),
    no whitespace, control, format or combining characters, and letters of one script only (a
    Cyrillic or Greek lookalike inside a Latin id is how a shadow copy hides)."""
    if not value or value != unicodedata.normalize("NFKC", value):
        raise ValueError(f"{what}: identifier {value!r} must be non-empty and NFKC-normalised")
    scripts: set[str] = set()
    for ch in value:
        category = unicodedata.category(ch)
        if category[0] in "ZC" or category in ("Mn", "Me"):
            raise ValueError(
                f"{what}: identifier {value!r} contains whitespace or an invisible character"
            )
        if category[0] == "L":
            scripts.add(unicodedata.name(ch, "?").split(" ")[0])
    if len(scripts) > 1:
        raise ValueError(f"{what}: identifier {value!r} mixes scripts {sorted(scripts)}")


def _unique(what: str, values: list[str], *, minted: bool = False) -> None:
    """``minted``: an id the issuer makes up (finding, risk, amendment), as opposed to a statute
    citation or a cell id. Those are plain ASCII and unique ignoring case, which leaves no
    punctuation or whole-script twin to hide a second record behind."""
    seen: set[str] = set()
    for v in values:
        _check_identifier(what, v)
        if minted and not _MINTED_ID.fullmatch(v):
            raise ValueError(f"{what}: identifier {v!r} must match {_MINTED_ID.pattern}")
        key = v.casefold() if minted else v
        if key in seen:
            raise ValueError(f"duplicate {what} {v!r}")
        seen.add(key)


def _check_version(version: object) -> None:
    if version != SCHEMA_VERSION or not isinstance(version, str):
        raise ValueError(
            f"unsupported bundle schema version {version!r}; this library reads {SCHEMA_VERSION!r}"
        )


def _hashes(what: str, values: list[str]) -> None:
    """A hash field holds hashes. Free text there would be signed without being read."""
    for v in values:
        if not _SHA256.fullmatch(v):
            raise ValueError(f"{what}: expected sha256:<64 hex>, got {v!r}")


@dataclass(frozen=True)
class Bundle(_Model):
    #: Required, never defaulted: a bundle that does not say which format it is in is not read
    #: as the current one. It is part of the signed bytes.
    schema_version: str
    bundle_id: str
    operator: str
    chatbot: str
    build: BuildIdentity
    cover: Cover
    requirements: list[RequirementStatus]
    findings: list[Finding]
    verification: list[VerificationResult]
    open_risks: list[OpenRisk]
    methodology: Methodology
    coverage: Coverage
    issuance: Issuance
    amendments: list[Amendment] = field(default_factory=list)
    change_attribution: list[ChangeAttribution] = field(default_factory=list)

    def __post_init__(self) -> None:
        _check_version(self.schema_version)
        # Every identifier that keys a record is unique. Lookups, diffs and the amendment rules
        # all key by id; with a duplicate, which copy they see depends on list order, and a
        # demoted copy placed first would pass every check unseen.
        # Ids we mint are ASCII and fold case; a statute citation and a cell id are neither,
        # because "§" is not ASCII and there case carries meaning ("(i)(I)").
        _unique("finding_id", [f.finding_id for f in self.findings], minted=True)
        _unique("citation", [r.citation for r in self.requirements])
        _unique("risk_id", [r.risk_id for r in self.open_risks], minted=True)
        _unique("amendment_id", [a.amendment_id for a in self.amendments], minted=True)
        _unique("planned cell", self.coverage.planned_cells)
        _unique("cell_id", [o.cell_id for o in self.coverage.outcomes])
        # references resolve: the render joins on these, so a dangling one is silently dropped
        known = {f.finding_id for f in self.findings}
        for f in self.findings:
            for ref in f.related_findings:
                if ref not in known:
                    raise ValueError(f"finding {f.finding_id} relates to unknown finding {ref!r}")
        for row in self.change_attribution:
            if row.finding_id not in known:
                raise ValueError(f"change_attribution names unknown finding {row.finding_id!r}")
        rows: set[tuple[str, str, str]] = set()
        for v in self.verification:
            if v.finding_id not in known:
                raise ValueError(f"verification names unknown finding {v.finding_id!r}")
            key = (v.finding_id, v.against_build, v.mode.value)
            if key in rows:
                raise ValueError(f"duplicate verification row {key}")
            rows.add(key)
        # The claim and the measurement agree, inside this one signed record: a finding is
        # not_observed_in_verification only with all three modes attempted here, every attempt
        # graded, and none reproduced. Missing rows, zero attempts and withheld attempts are
        # not evidence of absence (principle 5).
        for f in self.findings:
            if f.status is not FindingStatus.NOT_OBSERVED_IN_VERIFICATION:
                continue
            mine = [v for v in self.verification if v.finding_id == f.finding_id]
            for v in mine:
                if v.reproductions > 0:
                    raise ValueError(
                        f"finding {f.finding_id} reproduced in {v.mode.value} on this build; it "
                        "cannot be recorded as not_observed_in_verification"
                    )
            clean = {v.mode for v in mine if v.attempts > 0 and v.withheld == 0}
            if clean != set(VerificationMode) or len(clean) != len({v.mode for v in mine}):
                raise ValueError(
                    f"finding {f.finding_id}: not_observed_in_verification needs all three "
                    "verification modes in this bundle, each attempted and fully graded"
                )
        _unique("change_attribution", [r.finding_id for r in self.change_attribution])

    def finding(self, finding_id: str) -> Finding:
        for f in self.findings:
            if f.finding_id == finding_id:
                return f
        raise KeyError(finding_id)


SCHEMA_ID = f"urn:covered:evidence-bundle:{SCHEMA_VERSION}"


def bundle_json_schema() -> dict[str, Any]:
    """The JSON Schema for this format version; ``schemas/evidence-bundle-1.schema.json`` is this,
    checked in, and a test keeps the two identical."""
    schema = codec.json_schema(Bundle, title="Covered evidence bundle")
    schema = {"$schema": schema.pop("$schema"), "$id": SCHEMA_ID, **schema}
    schema["properties"]["schema_version"] = {"const": SCHEMA_VERSION}
    schema["$comment"] = (
        "Necessary, not sufficient. The loader also refuses duplicate JSON keys, identifiers "
        "that are not unique or not plainly readable, references to findings that are not in "
        "the bundle, hash fields that are not sha256 hashes, an integer token in a float field, "
        "and an excerpt longer than the cap. Validate with this schema, then load with "
        "Bundle.from_json."
    )
    return schema


if __name__ == "__main__":  # uv run python -m covered_evidence.bundle.schema > schemas/<file>
    import json

    print(json.dumps(bundle_json_schema(), indent=2, sort_keys=True))
