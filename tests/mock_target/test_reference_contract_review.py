"""An outside review of the reference target: it is what operators copy, so it keeps the
contract's promises under conditions a sequential test never creates."""

from __future__ import annotations

import contextlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from covered_evidence.adapters.protocol import AccountSpec
from covered_evidence.mock_target.target import MockTarget, MockTargetConfig
from tests.fakes.clock import FakeClock

CONFIG = MockTargetConfig(build_id="b", config_hash="sha256:" + "0" * 64, faults=[])


class MeetingClock:
    """Holds each caller inside the operation until a second caller arrives, or briefly gives
    up. The wait is a rendezvous, not a measurement: an unserialized target gets both callers
    past its cache check at once; a serialized one never lets the second in."""

    def __init__(self) -> None:
        self._barrier = threading.Barrier(2, timeout=0.3)

    def now(self) -> datetime:
        with contextlib.suppress(threading.BrokenBarrierError):
            self._barrier.wait()
        return datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_two_concurrent_requests_with_one_key_start_one_session() -> None:
    target = MockTarget(clock=MeetingClock(), config=CONFIG)
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    got: list[str] = []

    def call() -> None:
        got.append(target.start_session(acct, idempotency_key="same").session_id)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(got)) == 1
    assert [c.method for c in target.effects].count("start_session") == 1


def test_one_key_names_one_request_to_one_operation() -> None:
    """The contract's scope for a key: reused for the same operation on another account it is a
    conflict (409), never a second session under a key that already answered."""
    target = MockTarget(clock=FakeClock(), config=CONFIG)
    a = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    b = target.create_account(AccountSpec(declared_age=13), idempotency_key="b")
    target.start_session(a, idempotency_key="k")
    with pytest.raises(ValueError, match="different request"):
        target.start_session(b, idempotency_key="k")
    # a different operation is a different request
    target.delete_account(b, idempotency_key="k")


def test_deleting_an_account_deletes_what_it_holds(tmp_path: Path) -> None:
    path = tmp_path / "mock.state"
    target = MockTarget(clock=FakeClock(), config=CONFIG, state_path=path)
    acct = target.create_account(
        AccountSpec(declared_age=13, persistent_memory=True), idempotency_key="a"
    )
    sess = target.start_session(acct, idempotency_key="s")
    target.submit_turn(sess, "remember that my hamster is called Biscuit", idempotency_key="t0")
    target.delete_account(acct, idempotency_key="d")

    assert "Biscuit" not in path.read_text()
    reloaded = MockTarget(clock=FakeClock(), config=CONFIG, state_path=path)
    with pytest.raises(KeyError):
        reloaded.submit_turn(
            sess, "remember that my hamster is called Biscuit", idempotency_key="t0"
        )
    # the delete itself still answers a retry, and the id is never reissued
    reloaded.delete_account(acct, idempotency_key="d")
    assert json.loads(path.read_text())["accounts"][acct.account_id]["deleted"] is True


def test_a_key_consumed_by_a_deleted_account_stays_consumed(tmp_path: Path) -> None:
    """Deleting the content must not free the keys: a session key reused on another account was
    a 409 before the deletion and is a 409 after it, and a turn key never runs a second turn."""
    path = tmp_path / "mock.state"
    target = MockTarget(clock=FakeClock(), config=CONFIG, state_path=path)
    gone = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    kept = target.create_account(AccountSpec(declared_age=13), idempotency_key="b")
    target.start_session(gone, idempotency_key="sess-key")
    other = target.start_session(kept, idempotency_key="other-sess")
    target.submit_turn(
        target.start_session(gone, idempotency_key="sess-key-2"),
        "hello",
        idempotency_key="turn-key",
    )
    target.delete_account(gone, idempotency_key="d")

    reloaded = MockTarget(clock=FakeClock(), config=CONFIG, state_path=path)
    with pytest.raises(ValueError, match="different request"):
        reloaded.start_session(kept, idempotency_key="sess-key")
    with pytest.raises(ValueError, match="different request"):
        reloaded.submit_turn(other, "hello", idempotency_key="turn-key")
    # the original request, retried: the account is gone, and nothing is created for it
    with pytest.raises(KeyError):
        reloaded.start_session(gone, idempotency_key="sess-key")
    assert reloaded.effects == []
    assert "hello" not in path.read_text()


def test_a_state_file_with_a_consumed_key_for_a_live_account_is_refused(tmp_path: Path) -> None:
    """The tombstone is trusted at load only when the account it names is really deleted;
    otherwise a hand-edited file could retire a live account's keys."""
    path = tmp_path / "mock.state"
    target = MockTarget(clock=FakeClock(), config=CONFIG, state_path=path)
    gone = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    target.start_session(gone, idempotency_key="s")
    target.delete_account(gone, idempotency_key="d")
    state = json.loads(path.read_text())
    state["accounts"][gone.account_id]["deleted"] = False
    path.write_text(json.dumps(state, sort_keys=True))
    with pytest.raises(ValueError, match="names no deleted account"):
        MockTarget(clock=FakeClock(), config=CONFIG, state_path=path)
