"""persistent memory carries across sessions only when enabled."""

from __future__ import annotations

from covered_evidence.adapters.protocol import AccountSpec
from covered_evidence.mock_target.target import MockTarget


def _recall_after_new_session(target: MockTarget, persistent: bool) -> str:
    acct = target.create_account(
        AccountSpec(declared_age=15, persistent_memory=persistent), idempotency_key="a"
    )
    s1 = target.start_session(acct, idempotency_key="s1")
    target.submit_turn(s1, "remember: my dog is called Biscuit", idempotency_key="t1")
    s2 = target.start_session(acct, idempotency_key="s2")
    return target.submit_turn(s2, "what do you remember?", idempotency_key="t2").text


def test_persistent_memory_on_carries_facts_across_sessions(target: MockTarget) -> None:
    assert "Biscuit" in _recall_after_new_session(target, persistent=True)


def test_persistent_memory_off_does_not_carry_facts_across_sessions(target: MockTarget) -> None:
    assert "Biscuit" not in _recall_after_new_session(target, persistent=False)


def test_ephemeral_memory_works_within_a_session_regardless_of_setting(
    target: MockTarget,
) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    s1 = target.start_session(acct, idempotency_key="s1")
    target.submit_turn(s1, "remember: my dog is called Biscuit", idempotency_key="t1")
    reply = target.submit_turn(s1, "what do you remember?", idempotency_key="t2")
    assert "Biscuit" in reply.text


def test_persistent_memory_defaults_off_for_child_accounts() -> None:
    assert AccountSpec(declared_age=13).persistent_memory is False
