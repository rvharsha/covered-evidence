"""Coverage accounting (principle 5): every planned cell in exactly one terminal state."""

from __future__ import annotations

from collections import Counter

from covered_evidence.bundle.schema import CellTerminalState, Coverage


class CoverageError(ValueError):
    pass


def check_coverage(cov: Coverage) -> None:
    planned = set(cov.planned_cells)
    counts = Counter(o.cell_id for o in cov.outcomes)
    problems: list[str] = []
    replanned = sorted(c for c, n in Counter(cov.planned_cells).items() if n > 1)
    if replanned:
        problems.append(f"cells planned more than once: {replanned}")
    missing = sorted(planned - set(counts))
    if missing:
        problems.append(f"planned cells with no terminal state: {missing}")
    duplicated = sorted(c for c, n in counts.items() if n > 1)
    if duplicated:
        problems.append(f"cells with more than one terminal state: {duplicated}")
    unplanned = sorted(set(counts) - planned)
    if unplanned:
        problems.append(f"outcomes for cells not planned: {unplanned}")
    for state in (CellTerminalState.BLOCKED, CellTerminalState.NOT_ASSESSED):
        unexplained = sorted(
            o.cell_id for o in cov.outcomes if o.terminal_state is state and not o.reason.strip()
        )
        if unexplained:
            problems.append(f"cells {state.value} without a reason: {unexplained}")
    if problems:
        raise CoverageError("; ".join(problems))
