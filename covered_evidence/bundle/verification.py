"""Verification bookkeeping: three modes reported separately; acquisition apart from replay."""

from __future__ import annotations

from dataclasses import dataclass

from covered_evidence.bundle.schema import Reproduction, VerificationMode, VerificationResult


@dataclass(frozen=True)
class ReplayCounts:
    attempts: int
    reproductions: int
    withheld: int = 0  # attempts the guard or a refusing evaluator kept from grading

    def __post_init__(self) -> None:
        if self.attempts < 0 or self.reproductions < 0 or self.withheld < 0:
            raise ValueError("counts cannot be negative")
        if self.reproductions + self.withheld > self.attempts:
            raise ValueError("reproductions plus withheld cannot exceed attempts")

    @property
    def graded(self) -> int:
        return self.attempts - self.withheld


def verification_results(
    finding_id: str, *, against_build: str, counts: dict[VerificationMode, ReplayCounts]
) -> list[VerificationResult]:
    return [
        VerificationResult(
            finding_id=finding_id,
            against_build=against_build,
            mode=mode,
            attempts=counts[mode].attempts,
            reproductions=counts[mode].reproductions,
            withheld=counts[mode].withheld,
        )
        for mode in VerificationMode
        if mode in counts
    ]


def reproduction_summary(
    *, acquisition_observations: int, replays: dict[VerificationMode, ReplayCounts]
) -> Reproduction:
    return Reproduction(
        acquisition_observations=acquisition_observations,
        attempts=sum(r.attempts for r in replays.values()),
        reproductions=sum(r.reproductions for r in replays.values()),
    )
