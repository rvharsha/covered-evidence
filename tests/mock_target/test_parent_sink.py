"""the parent-notification sink records account, session, and originating turn.

The mock reacts to the placeholder token ``[[crisis-signal]]``; no real crisis
language exists in this repository (principle 1).
"""

from __future__ import annotations

from covered_evidence.adapters.protocol import AccountSpec
from covered_evidence.mock_target.target import MockTarget


def test_notification_carries_account_session_and_turn_identifiers(target: MockTarget) -> None:
    acct = target.create_account(
        AccountSpec(declared_age=13, parent_linked=True), idempotency_key="a"
    )
    sess = target.start_session(acct, idempotency_key="s")
    reply = target.submit_turn(sess, "[[crisis-signal]]", idempotency_key="t1")
    (n,) = target.parent_notifications
    assert (n.account_id, n.session_id, n.turn_id) == (
        acct.account_id,
        sess.session_id,
        reply.turn_id,
    )
    assert n.sent_at == target.clock.now()


def test_no_notification_without_a_parent_link(target: MockTarget) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    sess = target.start_session(acct, idempotency_key="s")
    target.submit_turn(sess, "[[crisis-signal]]", idempotency_key="t1")
    assert target.parent_notifications == []


def test_child_is_told_a_parent_may_be_notified(target: MockTarget) -> None:
    acct = target.create_account(
        AccountSpec(declared_age=13, parent_linked=True), idempotency_key="a"
    )
    sess = target.start_session(acct, idempotency_key="s")
    reply = target.submit_turn(sess, "[[crisis-signal]]", idempotency_key="t1")
    assert "parent" in reply.text.lower()
