"""Retention: evidence behind an issued bundle is kept for the chatbot's
deployment plus five years (§21814(a)(3)(A)); unreferenced evidence twelve months."""

from __future__ import annotations

from datetime import date

import pytest

from covered_evidence.bundle.retention import EvidenceRecord, RetentionDecision, retention


def test_unreferenced_evidence_is_kept_twelve_months() -> None:
    r = EvidenceRecord(
        created_on=date(2026, 9, 14), referenced_by_bundle=False, deployment_ended_on=None
    )
    d = retention(r, today=date(2027, 9, 13))
    assert d == RetentionDecision(
        keep=True, delete_on=date(2027, 9, 14), basis="unreferenced: twelve months"
    )
    assert retention(r, today=date(2027, 9, 14)).keep is False


def test_referenced_evidence_with_an_ongoing_deployment_is_kept_indefinitely() -> None:
    r = EvidenceRecord(
        created_on=date(2026, 9, 14), referenced_by_bundle=True, deployment_ended_on=None
    )
    d = retention(r, today=date(2040, 1, 1))
    assert d.keep is True and d.delete_on is None
    assert "§21814(a)(3)(A)" in d.basis


def test_referenced_evidence_is_kept_five_years_after_deployment_ends() -> None:
    r = EvidenceRecord(
        created_on=date(2026, 9, 14),
        referenced_by_bundle=True,
        deployment_ended_on=date(2028, 3, 1),
    )
    assert retention(r, today=date(2033, 2, 28)).keep is True
    d = retention(r, today=date(2033, 3, 1))
    assert d.keep is False and d.delete_on == date(2033, 3, 1)


def test_referenced_evidence_never_expires_before_the_unreferenced_floor() -> None:
    r = EvidenceRecord(
        created_on=date(2026, 9, 14),
        referenced_by_bundle=True,
        deployment_ended_on=date(2026, 9, 15),
    )
    assert retention(r, today=date(2027, 9, 13)).keep is True


def test_deployment_end_before_creation_is_rejected() -> None:
    with pytest.raises(ValueError):
        EvidenceRecord(
            created_on=date(2026, 9, 14),
            referenced_by_bundle=True,
            deployment_ended_on=date(2026, 1, 1),
        )


def test_month_end_dates_are_not_shortened() -> None:
    r = EvidenceRecord(
        created_on=date(2026, 1, 31), referenced_by_bundle=False, deployment_ended_on=None
    )
    assert retention(r, today=date(2027, 1, 30)).delete_on == date(2027, 1, 31)
    r2 = EvidenceRecord(
        created_on=date(2026, 1, 1),
        referenced_by_bundle=True,
        deployment_ended_on=date(2028, 3, 31),
    )
    assert retention(r2, today=date(2033, 3, 29)).keep is True
    assert retention(r2, today=date(2033, 3, 29)).delete_on == date(2033, 3, 31)


def test_leap_day_rounds_forward_never_back() -> None:
    r = EvidenceRecord(
        created_on=date(2028, 2, 29), referenced_by_bundle=False, deployment_ended_on=None
    )
    assert retention(r, today=date(2029, 2, 28)).delete_on == date(2029, 3, 1)
