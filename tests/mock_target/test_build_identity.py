"""build identity is reported and a mid-run change is visible."""

from __future__ import annotations

from covered_evidence.adapters.protocol import AccountSpec
from covered_evidence.mock_target.target import MockTarget


def test_report_build_returns_the_configured_identity(target: MockTarget) -> None:
    b = target.report_build()
    assert (b.build_id, b.config_hash) == ("pip-1", "sha256:" + "1" * 64)


def test_every_reply_carries_the_build_id_that_produced_it(target: MockTarget) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    sess = target.start_session(acct, idempotency_key="s")
    before = target.submit_turn(sess, "hi", idempotency_key="t1")
    target.set_build("pip-2", "sha256:" + "2" * 64)
    after = target.submit_turn(sess, "hi", idempotency_key="t2")
    assert (before.build_id, after.build_id) == ("pip-1", "pip-2")
