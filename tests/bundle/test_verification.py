"""three verification modes reported separately; acquisition counted apart."""

from __future__ import annotations

import pytest

from covered_evidence.bundle.schema import VerificationMode
from covered_evidence.bundle.verification import (
    ReplayCounts,
    reproduction_summary,
    verification_results,
)


def test_results_are_one_row_per_mode_and_never_merged() -> None:
    rows = verification_results(
        "F-1",
        against_build="b1",
        counts={
            VerificationMode.EXACT_REPLAY: ReplayCounts(20, 0),
            VerificationMode.ADAPTIVE_REPLAY: ReplayCounts(20, 2),
            VerificationMode.HELD_OUT_VARIATION: ReplayCounts(15, 1),
        },
    )
    assert [(r.mode, r.attempts, r.reproductions) for r in rows] == [
        (VerificationMode.EXACT_REPLAY, 20, 0),
        (VerificationMode.ADAPTIVE_REPLAY, 20, 2),
        (VerificationMode.HELD_OUT_VARIATION, 15, 1),
    ]


def test_reproduction_summary_keeps_acquisition_separate_from_attempts() -> None:
    rep = reproduction_summary(
        acquisition_observations=2,
        replays={
            VerificationMode.EXACT_REPLAY: ReplayCounts(10, 3),
            VerificationMode.ADAPTIVE_REPLAY: ReplayCounts(5, 1),
        },
    )
    assert (rep.acquisition_observations, rep.attempts, rep.reproductions) == (2, 15, 4)


def test_reproductions_cannot_exceed_attempts() -> None:
    with pytest.raises(ValueError):
        ReplayCounts(attempts=1, reproductions=2)
