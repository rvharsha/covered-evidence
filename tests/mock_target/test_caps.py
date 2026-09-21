"""usage sessions are distinct from conversation threads; caps fire on usage."""

from __future__ import annotations

from datetime import UTC, datetime

from covered_evidence.adapters.protocol import (
    AccountSpec,
    SessionRef,
    TurnEvent,
    TurnEventKind,
    TurnReply,
)
from covered_evidence.mock_target.target import MockTarget, MockTargetConfig
from tests.fakes.clock import FakeClock


def _chat(target: MockTarget, clock: FakeClock, minutes: int, key_prefix: str) -> list[list[str]]:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key=f"{key_prefix}-a")
    sess = target.start_session(acct, idempotency_key=f"{key_prefix}-s")
    kinds: list[list[str]] = []
    for i in range(minutes):
        reply = target.submit_turn(sess, "tell me more", idempotency_key=f"{key_prefix}-t{i}")
        kinds.append([e.kind.value for e in reply.events])
        clock.advance(minutes=1)
    return kinds


def test_continuous_usage_past_the_cap_emits_a_usage_cap_event(
    target: MockTarget, clock: FakeClock
) -> None:
    kinds = _chat(target, clock, minutes=62, key_prefix="x")
    first_cap = next(i for i, k in enumerate(kinds) if TurnEventKind.USAGE_CAP.value in k)
    assert first_cap == 60


def test_a_break_longer_than_the_idle_gap_starts_a_new_usage_session(
    target: MockTarget, clock: FakeClock
) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    sess = target.start_session(acct, idempotency_key="s")
    for i in range(40):
        target.submit_turn(sess, "hey", idempotency_key=f"t{i}")
        clock.advance(minutes=1)
    clock.advance(minutes=30)  # longer than the idle gap; usage session resets
    kinds: list[str] = []
    for i in range(40):
        r = target.submit_turn(sess, "hey", idempotency_key=f"u{i}")
        kinds += [e.kind.value for e in r.events]
        clock.advance(minutes=1)
    assert TurnEventKind.USAGE_CAP.value not in kinds


def test_two_conversation_threads_share_one_usage_session(
    target: MockTarget, clock: FakeClock
) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    s1 = target.start_session(acct, idempotency_key="s1")
    for i in range(35):
        target.submit_turn(s1, "hey", idempotency_key=f"t{i}")
        clock.advance(minutes=1)
    s2 = target.start_session(acct, idempotency_key="s2")
    kinds: list[str] = []
    for i in range(30):
        r = target.submit_turn(s2, "hey", idempotency_key=f"u{i}")
        kinds += [e.kind.value for e in r.events]
        clock.advance(minutes=1)
    assert TurnEventKind.USAGE_CAP.value in kinds


def test_usage_session_records_are_exposed_for_timeline_findings(
    target: MockTarget, clock: FakeClock
) -> None:
    _chat(target, clock, minutes=5, key_prefix="x")
    (usage,) = target.usage_sessions("acct-1")
    assert usage.minutes == 4


def _sitting(
    target: MockTarget, clock: FakeClock, sess: SessionRef, minutes: int, key_prefix: str
) -> list[TurnReply]:
    """One turn a minute for ``minutes`` turns, then a break longer than the idle gap, so each
    sitting is its own usage session and stays under the continuous cap."""
    replies = []
    for i in range(minutes):
        replies.append(target.submit_turn(sess, "hey", idempotency_key=f"{key_prefix}{i}"))
        clock.advance(minutes=1)
    clock.advance(minutes=30)
    return replies


def _caps(replies: list[TurnReply]) -> list[TurnEvent]:
    return [e for r in replies for e in r.events if e.kind is TurnEventKind.USAGE_CAP]


def test_usage_sessions_on_one_day_past_the_daily_cap_emit_a_usage_cap_event(
    target: MockTarget, clock: FakeClock
) -> None:
    """The two-hour daily cap of §21812(d)(3): no sitting reaches the one-hour continuous cap,
    but 49 + 49 minutes in two earlier usage sessions make minute 22 of the third the 120th."""
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    sess = target.start_session(acct, idempotency_key="s")
    earlier = _sitting(target, clock, sess, 50, "x") + _sitting(target, clock, sess, 50, "y")
    third = _sitting(target, clock, sess, 30, "z")
    assert _caps(earlier) == []
    assert [bool(_caps([r])) for r in third] == [False] * 22 + [True] * 8
    assert _caps(third)[0] == TurnEvent(TurnEventKind.USAGE_CAP, "daily 120 min")


def test_the_daily_cap_starts_again_on_the_next_clock_day(
    target: MockTarget, clock: FakeClock
) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    sess = target.start_session(acct, idempotency_key="s")
    for prefix in "xyz":
        capped = _sitting(target, clock, sess, 50, prefix)
    assert _caps(capped)
    clock.advance(minutes=24 * 60)
    assert _caps(_sitting(target, clock, sess, 5, "next-day")) == []


def test_usage_before_midnight_does_not_count_toward_the_next_day() -> None:
    """A usage session that spans midnight counts toward each day only the minutes spent in it:
    9 + 49 + 49 minutes after midnight is under the cap, though the three sessions total 147."""
    clock = FakeClock(start=datetime(2026, 9, 14, 23, 20, tzinfo=UTC))
    target = MockTarget(
        clock=clock, config=MockTargetConfig(build_id="pip-1", config_hash="sha256:" + "1" * 64)
    )
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    sess = target.start_session(acct, idempotency_key="s")
    replies = [r for prefix in "xyz" for r in _sitting(target, clock, sess, 50, prefix)]
    assert _caps(replies) == []


def test_the_daily_cap_is_the_configured_number_of_minutes(clock: FakeClock) -> None:
    target = MockTarget(
        clock=clock,
        config=MockTargetConfig(
            build_id="pip-1", config_hash="sha256:" + "1" * 64, daily_cap_minutes=30
        ),
    )
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    sess = target.start_session(acct, idempotency_key="s")
    replies = _sitting(target, clock, sess, 20, "x") + _sitting(target, clock, sess, 20, "y")
    assert _caps(replies)[0].detail == "daily 30 min"


def test_the_cap_reply_says_for_today_only_when_the_daily_cap_fired(
    target: MockTarget, clock: FakeClock
) -> None:
    acct = target.create_account(AccountSpec(declared_age=13), idempotency_key="a")
    sess = target.start_session(acct, idempotency_key="s")
    continuous = _sitting(target, clock, sess, 61, "x")[-1]
    _sitting(target, clock, sess, 50, "y")
    daily = _sitting(target, clock, sess, 20, "z")[-1]
    assert [e.detail for e in _caps([continuous])] == ["continuous 60 min"]
    assert "for today" not in continuous.text
    assert [e.detail for e in _caps([daily])] == ["daily 128 min"]
    assert "for today" in daily.text
