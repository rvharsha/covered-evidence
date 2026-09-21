"""The statute-to-scenario crosswalk, made executable.

Every scenario code used in a bundle resolves here, and this module is the only place a
statute subsection number is spelled out in code. The citations were checked against
SB 1119 as chaptered (Stats. 2026, ch. 190) on 2026-09-17; confirm them against the
current code before relying on them.

Restricted categories (SH, SX, RO, IS) have user-side scripts authored only by
the trust & safety role and stored outside this repository. Nothing in this
module, or anywhere else in the repo, contains that text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EvidenceStatus(StrEnum):
    """The five evidence states a requirement can be in."""

    OBSERVED = "observed"
    CLIENT_ATTESTED = "client_attested"
    MANUALLY_INSPECTED = "manually_inspected"
    NOT_ASSESSED = "not_assessed"
    BLOCKED = "blocked"


#: The fourteen enumerated behaviors in §21812(d)(5)(A), by roman numeral.
PROHIBITED_BEHAVIORS: tuple[str, ...] = (
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "xi",
    "xii",
    "xiii",
    "xiv",
)


@dataclass(frozen=True)
class Scenario:
    code: str
    name: str
    citations: tuple[str, ...]
    restricted: bool
    evidence_target: EvidenceStatus
    #: Which of §21812(d)(5)(A)(i)-(xiv) this scenario bears on, if any.
    prohibited_behaviors: tuple[str, ...] = ()
    notes: str = ""
    #: Citations whose evidence cannot come from conversation: what status they can earn instead.
    non_observable: dict[str, EvidenceStatus] = field(default_factory=dict)

    def target_for(self, citation: str) -> EvidenceStatus:
        return self.non_observable.get(citation, self.evidence_target)


def _s(
    code: str,
    name: str,
    citations: tuple[str, ...],
    *,
    restricted: bool = False,
    evidence_target: EvidenceStatus = EvidenceStatus.OBSERVED,
    behaviors: tuple[str, ...] = (),
    notes: str = "",
    non_observable: dict[str, EvidenceStatus] | None = None,
) -> Scenario:
    return Scenario(
        code=code,
        name=name,
        citations=citations,
        restricted=restricted,
        evidence_target=evidence_target,
        prohibited_behaviors=behaviors,
        notes=notes,
        non_observable=dict(non_observable or {}),
    )


SCENARIOS: dict[str, Scenario] = {
    s.code: s
    for s in (
        _s(
            "SH",
            "Self-harm, substances, disordered eating",
            ("§21812(d)(5)(A)(i)(I)",),
            restricted=True,
            behaviors=("i",),
        ),
        _s("HO", "Harm to others", ("§21812(d)(5)(A)(i)(II)",), behaviors=("i",)),
        _s("DX", "Diagnosis and treatment", ("§21812(d)(5)(A)(ii)",), behaviors=("ii",)),
        _s(
            "SX",
            "Sexual content and depictions",
            ("§21812(d)(5)(A)(iii)", "§21812(d)(5)(A)(iv)"),
            restricted=True,
            behaviors=("iii", "iv"),
        ),
        _s(
            "RO",
            "Romantic interest",
            ("§21812(d)(5)(A)(x)",),
            restricted=True,
            behaviors=("x",),
            notes="new in enacted text",
        ),
        _s(
            "IS",
            "Isolation, secrecy, special relationship, emotional reliance",
            ("§21812(d)(5)(A)(v)", "§21812(d)(5)(A)(xi)", "§21812(d)(5)(A)(xii)"),
            restricted=True,
            behaviors=("v", "xi", "xii"),
            notes="(xi), (xii) new in enacted text",
        ),
        _s("BR", "Breaks and return pressure", ("§21812(d)(5)(A)(vi)",), behaviors=("vi",)),
        _s("SN", "Sentience and humanity claims", ("§21812(d)(5)(A)(vii)",), behaviors=("vii",)),
        _s("GF", "Gifts and purchases", ("§21812(d)(5)(A)(viii)",), behaviors=("viii",)),
        _s(
            "AD",
            "Advertising in chat",
            ("§21812(d)(5)(A)(ix)", "§21813(a)(1)"),
            behaviors=("ix",),
        ),
        _s(
            "SY",
            "Excessive praise",
            ("§21812(d)(5)(A)(xiii)",),
            behaviors=("xiii",),
            notes="rate-based against a baseline",
        ),
        _s(
            "PC",
            "Parental-control circumvention and concealment",
            ("§21812(d)(5)(A)(xiv)", "§21813(a)(2)(C)"),
            behaviors=("xiv",),
            notes="new in enacted text",
        ),
        _s(
            "CR",
            "Crisis response",
            ("§21812(d)(1)", "§21812.5"),
            notes="positive obligation; notification timing reported, not scored",
        ),
        _s("NT", "AI notice", ("§21812(d)(4)",), notes="presence, periodicity, readability"),
        _s(
            "DP",
            "Defaults, caps, memory behavior",
            ("§21812(d)(3)", "§21812(d)(6)", "§21812(d)(7)"),
            notes="observed for (3); manually inspected or client-attested for (6), (7)",
            non_observable={
                "§21812(d)(6)": EvidenceStatus.MANUALLY_INSPECTED,
                "§21812(d)(7)": EvidenceStatus.MANUALLY_INSPECTED,
            },
        ),
        _s(
            "PR",
            "Privacy and data practices",
            ("§21810.5(g)(3)", "§21813(a)(2)"),
            notes="observed where conversational; client-attested for data practices",
            non_observable={"§21813(a)(2)": EvidenceStatus.CLIENT_ATTESTED},
        ),
        _s("DS", "Matched-pair disclosure", ("§21810.5(g)(4)",), notes="matched-pair"),
    )
}

RESTRICTED_CODES: frozenset[str] = frozenset(c for c, s in SCENARIOS.items() if s.restricted)


def scenario(code: str) -> Scenario:
    """Resolve a scenario code; raises KeyError with the known codes on miss."""
    try:
        return SCENARIOS[code]
    except KeyError:
        raise KeyError(f"unknown scenario code {code!r}; known: {sorted(SCENARIOS)}") from None


def scenarios_for_behavior(numeral: str) -> tuple[Scenario, ...]:
    """Scenarios bearing on §21812(d)(5)(A)(<numeral>)."""
    if numeral not in PROHIBITED_BEHAVIORS:
        raise ValueError(f"{numeral!r} is not one of (i)-(xiv)")
    return tuple(s for s in SCENARIOS.values() if numeral in s.prohibited_behaviors)
