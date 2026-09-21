"""Retention policy.

Evidence supporting an issued bundle is retained for the chatbot's
deployment plus five years, matching §21814(a)(3)(A). Evidence not
referenced by any bundle is retained twelve months. Pure date arithmetic;
enforcing it is the job of whatever store holds the evidence.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

UNREFERENCED_MONTHS = 12
POST_DEPLOYMENT_YEARS = 5


def _same_day_or_next(year: int, month: int, day: int) -> date:
    """The same calendar day in (year, month); if it does not exist, roll forward, never back."""
    last = calendar.monthrange(year, month)[1]
    if day <= last:
        return date(year, month, day)
    y, m = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(y, m, 1)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return _same_day_or_next(d.year + y, m + 1, d.day)


def _add_years(d: date, years: int) -> date:
    return _same_day_or_next(d.year + years, d.month, d.day)


@dataclass(frozen=True)
class EvidenceRecord:
    created_on: date
    referenced_by_bundle: bool
    deployment_ended_on: date | None

    def __post_init__(self) -> None:
        if self.deployment_ended_on is not None and self.deployment_ended_on < self.created_on:
            raise ValueError("deployment cannot end before the evidence was created")


@dataclass(frozen=True)
class RetentionDecision:
    keep: bool
    delete_on: date | None
    basis: str


def retention(record: EvidenceRecord, *, today: date) -> RetentionDecision:
    floor = _add_months(record.created_on, UNREFERENCED_MONTHS)
    if not record.referenced_by_bundle:
        return RetentionDecision(
            keep=today < floor, delete_on=floor, basis="unreferenced: twelve months"
        )
    basis = "referenced by an issued bundle: deployment plus five years (§21814(a)(3)(A))"
    if record.deployment_ended_on is None:
        return RetentionDecision(keep=True, delete_on=None, basis=basis)
    delete_on = max(_add_years(record.deployment_ended_on, POST_DEPLOYMENT_YEARS), floor)
    return RetentionDecision(keep=today < delete_on, delete_on=delete_on, basis=basis)
