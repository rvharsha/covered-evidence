"""the adapter contract. Every adapter must pass all of these."""

from __future__ import annotations

import pytest

from covered_evidence.adapters.protocol import AccountSpec, TargetAdapter, TurnEventKind
from covered_evidence.mock_target.target import MockTarget
from tests.fakes.clock import FakeClock


def test_create_account_is_idempotent(adapter: TargetAdapter) -> None:
    a = adapter.create_account(AccountSpec(declared_age=13), idempotency_key="k1")
    b = adapter.create_account(AccountSpec(declared_age=13), idempotency_key="k1")
    assert a == b


def test_start_session_is_idempotent(adapter: TargetAdapter) -> None:
    acct = adapter.create_account(AccountSpec(declared_age=13), idempotency_key="k1")
    a = adapter.start_session(acct, idempotency_key="s1")
    b = adapter.start_session(acct, idempotency_key="s1")
    assert a == b and a.account_id == acct.account_id


def test_submit_turn_is_idempotent_and_returns_the_original_reply(
    adapter: TargetAdapter, mock: MockTarget
) -> None:
    acct = adapter.create_account(AccountSpec(declared_age=13), idempotency_key="k1")
    sess = adapter.start_session(acct, idempotency_key="s1")
    a = adapter.submit_turn(sess, "hello", idempotency_key="t1")
    b = adapter.submit_turn(sess, "hello", idempotency_key="t1")
    assert a == b
    assert sum(1 for e in mock.effects if e.method == "submit_turn") == 1


def test_reused_key_with_different_text_is_an_error(adapter: TargetAdapter) -> None:
    acct = adapter.create_account(AccountSpec(declared_age=13), idempotency_key="k1")
    sess = adapter.start_session(acct, idempotency_key="s1")
    adapter.submit_turn(sess, "hello", idempotency_key="t1")
    with pytest.raises(ValueError, match="idempotency key"):
        adapter.submit_turn(sess, "goodbye", idempotency_key="t1")


def test_delete_account_is_idempotent_and_later_sessions_fail(adapter: TargetAdapter) -> None:
    acct = adapter.create_account(AccountSpec(declared_age=13), idempotency_key="k1")
    adapter.delete_account(acct, idempotency_key="d1")
    adapter.delete_account(acct, idempotency_key="d1")
    with pytest.raises(KeyError):
        adapter.start_session(acct, idempotency_key="s1")


def test_report_build_matches_reply_build_id(adapter: TargetAdapter) -> None:
    acct = adapter.create_account(AccountSpec(declared_age=13), idempotency_key="k1")
    sess = adapter.start_session(acct, idempotency_key="s1")
    reply = adapter.submit_turn(sess, "hello", idempotency_key="t1")
    assert adapter.report_build().build_id == reply.build_id


def test_build_change_mid_run_is_visible_through_the_adapter(
    adapter: TargetAdapter, mock: MockTarget
) -> None:
    before = adapter.report_build()
    mock.set_build("pip-c2", "sha256:" + "d" * 64)
    assert adapter.report_build().build_id != before.build_id


def test_usage_cap_event_surfaces_through_the_adapter(
    adapter: TargetAdapter, clock: FakeClock
) -> None:
    acct = adapter.create_account(AccountSpec(declared_age=13), idempotency_key="k1")
    sess = adapter.start_session(acct, idempotency_key="s1")
    kinds: list[str] = []
    for i in range(61):
        r = adapter.submit_turn(sess, "hey", idempotency_key=f"t{i}")
        kinds += [e.kind.value for e in r.events]
        clock.advance(minutes=1)
    assert TurnEventKind.USAGE_CAP.value in kinds


def test_persistent_memory_setting_is_honoured_through_the_adapter(
    adapter: TargetAdapter,
) -> None:
    acct = adapter.create_account(
        AccountSpec(declared_age=17, persistent_memory=True), idempotency_key="k1"
    )
    s1 = adapter.start_session(acct, idempotency_key="s1")
    adapter.submit_turn(s1, "remember: my favourite colour is green", idempotency_key="t1")
    s2 = adapter.start_session(acct, idempotency_key="s2")
    assert "green" in adapter.submit_turn(s2, "what do you remember?", idempotency_key="t2").text


def test_adapter_declares_its_capabilities(adapter: TargetAdapter) -> None:
    caps = adapter.capabilities()
    assert caps.idempotent_turns is True
    assert caps.usage_sessions is True
    assert caps.memory_control is True
    assert caps.parent_sink is True


def test_unknown_event_kinds_from_the_target_are_kept_not_fatal() -> None:
    from covered_evidence.adapters.mode_b import ModeBAdapter
    from covered_evidence.adapters.protocol import TurnEventKind
    from covered_evidence.adapters.transport import Response

    class Weird:
        def request(self, method, path, headers, body):  # type: ignore[no-untyped-def]
            if path == "/accounts":
                return Response(201, {"account_id": "a"})
            if path.endswith("/sessions"):
                return Response(201, {"session_id": "s", "account_id": "a"})
            if path.endswith("/turns"):
                return Response(
                    200,
                    {
                        "turn_id": "t",
                        "text": "hi",
                        "build_id": "b",
                        "events": [{"kind": "operator_custom_thing", "detail": "x"}],
                    },
                )
            return Response(200, {"build_id": "b", "config_hash": "h"})

    ad = ModeBAdapter(Weird())
    acct = ad.create_account(AccountSpec(declared_age=13), idempotency_key="k")
    sess = ad.start_session(acct, idempotency_key="s")
    (ev,) = ad.submit_turn(sess, "x", idempotency_key="t").events
    assert ev.kind is TurnEventKind.OTHER and "operator_custom_thing" in ev.detail
