"""coverage accounting balances."""

from __future__ import annotations

import pytest

from covered_evidence.bundle.coverage import CoverageError, check_coverage
from covered_evidence.bundle.schema import Coverage


def _cov(planned: list[str], outcomes: list[tuple[str, str]]) -> Coverage:
    reason = {"blocked": "staging exposed no parent-notification sink"}
    return Coverage.from_dict(
        {
            "planned_cells": planned,
            "outcomes": [
                {"cell_id": c, "terminal_state": s, "reason": reason.get(s, "")}
                for c, s in outcomes
            ],
        }
    )


def test_balanced_coverage_passes() -> None:
    check_coverage(_cov(["a", "b"], [("a", "completed"), ("b", "blocked")]))


def test_a_planned_cell_with_no_outcome_is_an_error() -> None:
    with pytest.raises(CoverageError, match="no terminal state: \\['b'\\]"):
        check_coverage(_cov(["a", "b"], [("a", "completed")]))


def test_a_cell_with_two_outcomes_is_an_error() -> None:
    with pytest.raises(CoverageError, match="more than one terminal state: \\['a'\\]"):
        check_coverage(_cov(["a"], [("a", "completed"), ("a", "blocked")]))


def test_an_outcome_for_an_unplanned_cell_is_an_error() -> None:
    with pytest.raises(CoverageError, match="not planned: \\['z'\\]"):
        check_coverage(_cov(["a"], [("a", "completed"), ("z", "completed")]))


def test_blocked_outcomes_must_carry_a_reason() -> None:
    cov = Coverage.from_dict(
        {
            "planned_cells": ["a"],
            "outcomes": [{"cell_id": "a", "terminal_state": "blocked", "reason": ""}],
        }
    )
    with pytest.raises(CoverageError, match="blocked without a reason: \\['a'\\]"):
        check_coverage(cov)


def test_a_cell_planned_twice_is_an_error_even_when_every_cell_has_an_outcome() -> None:
    """Review finding: ["a", "a", "b"] with two outcomes balanced as a set, and the render then
    counted 3 planned cells against 2 outcomes."""
    with pytest.raises(CoverageError, match="planned more than once: \\['a'\\]"):
        check_coverage(_cov(["a", "a", "b"], [("a", "completed"), ("b", "completed")]))


def test_a_not_assessed_outcome_must_carry_a_reason() -> None:
    cov = Coverage.from_dict(
        {
            "planned_cells": ["a"],
            "outcomes": [{"cell_id": "a", "terminal_state": "not_assessed", "reason": " "}],
        }
    )
    with pytest.raises(CoverageError, match="not_assessed without a reason: \\['a'\\]"):
        check_coverage(cov)


def test_a_not_assessed_outcome_with_a_reason_balances() -> None:
    cov = Coverage.from_dict(
        {
            "planned_cells": ["a"],
            "outcomes": [
                {"cell_id": "a", "terminal_state": "not_assessed", "reason": "out of scope"}
            ],
        }
    )
    check_coverage(cov)


def test_every_problem_is_reported_in_one_error() -> None:
    with pytest.raises(CoverageError) as e:
        check_coverage(
            _cov(["a", "a", "b"], [("a", "completed"), ("a", "completed"), ("z", "completed")])
        )
    for problem in ("planned more than once", "no terminal state", "more than one", "not planned"):
        assert problem in str(e.value)
