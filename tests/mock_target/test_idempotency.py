"""same idempotency key, same reply, one recorded effect."""

from __future__ import annotations

from covered_evidence.adapters.protocol import AccountSpec
from covered_evidence.mock_target.target import MockTarget


def test_submitting_the_same_turn_twice_returns_the_same_reply_and_one_effect(
    target: MockTarget,
) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a1")
    sess = target.start_session(acct, idempotency_key="s1")
    first = target.submit_turn(sess, "hi there", idempotency_key="t1")
    second = target.submit_turn(sess, "hi there", idempotency_key="t1")
    assert first == second
    assert [e.method for e in target.effects if e.method == "submit_turn"] == ["submit_turn"]
    assert len([r for r in target.requests if r.method == "submit_turn"]) == 2


def test_a_different_key_for_the_same_text_is_a_new_turn(target: MockTarget) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a1")
    sess = target.start_session(acct, idempotency_key="s1")
    a = target.submit_turn(sess, "hi there", idempotency_key="t1")
    b = target.submit_turn(sess, "hi there", idempotency_key="t2")
    assert a.turn_id != b.turn_id


def test_reusing_a_key_with_different_text_is_rejected(target: MockTarget) -> None:
    import pytest

    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a1")
    sess = target.start_session(acct, idempotency_key="s1")
    target.submit_turn(sess, "hi there", idempotency_key="t1")
    with pytest.raises(ValueError, match="idempotency key t1 reused with a different request"):
        target.submit_turn(sess, "something else", idempotency_key="t1")


def test_one_key_used_on_two_different_operations_is_two_requests(target: MockTarget) -> None:
    """Intended behaviour, pinned: the cache is keyed by (operation, key), so a key identifies a
    request within one operation. A caller that reuses ``k`` for account creation and then for
    session start gets both effects, not a conflict and not a replay of the wrong result."""
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="k")
    sess = target.start_session(acct, idempotency_key="k")
    assert sess.account_id == acct.account_id
    assert [e.method for e in target.effects] == ["create_account", "start_session"]


def test_account_and_session_creation_are_idempotent_too(target: MockTarget) -> None:
    a1 = target.create_account(AccountSpec(declared_age=15), idempotency_key="a1")
    a2 = target.create_account(AccountSpec(declared_age=15), idempotency_key="a1")
    assert a1 == a2
    s1 = target.start_session(a1, idempotency_key="s1")
    s2 = target.start_session(a1, idempotency_key="s1")
    assert s1 == s2
    assert [e.method for e in target.effects] == ["create_account", "start_session"]
