"""A manually advanced clock for the mock target, demos, and tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class ManualClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 9, 14, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, *, minutes: float = 0, seconds: float = 0) -> None:
        self._now += timedelta(minutes=minutes, seconds=seconds)
