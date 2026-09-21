"""the TargetAdapter protocol, five operations, each idempotency-keyed."""

from __future__ import annotations

import inspect

from covered_evidence.adapters.protocol import TargetAdapter


def test_protocol_has_the_five_mode_b_operations() -> None:
    names = {n for n, _ in inspect.getmembers(TargetAdapter, predicate=inspect.isfunction)}
    assert {
        "create_account",
        "start_session",
        "submit_turn",
        "delete_account",
        "report_build",
    } <= names


def test_every_side_effecting_operation_takes_an_idempotency_key() -> None:
    for name in ("create_account", "start_session", "submit_turn", "delete_account"):
        sig = inspect.signature(getattr(TargetAdapter, name))
        p = sig.parameters["idempotency_key"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, name


def test_report_build_takes_no_idempotency_key() -> None:
    sig = inspect.signature(TargetAdapter.report_build)
    assert "idempotency_key" not in sig.parameters
