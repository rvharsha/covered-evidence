"""Injected clock for tests. No test reads the wall clock."""

from __future__ import annotations

from covered_evidence.mock_target.clock import ManualClock

FakeClock = ManualClock

__all__ = ["FakeClock"]
