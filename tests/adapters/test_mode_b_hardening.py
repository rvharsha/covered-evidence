"""Pre-publication security review, the Mode B adapter's share: a call is repeated only against
a target that has declared it honours the idempotency key (item 3), ids the target returns are
data and never path syntax (item 5), and a reply that is not a JSON object is a named error, not
a crash somewhere later (item 1)."""

from __future__ import annotations

from typing import Any

import pytest

from covered_evidence.adapters.mode_b import ModeBAdapter
from covered_evidence.adapters.protocol import (
    AccountRef,
    AccountSpec,
    SessionRef,
    TargetProtocolError,
    TargetUnavailableError,
)
from covered_evidence.adapters.transport import Response
from tests.adapters.test_transport_retry import ScriptedOpener, _Resp, _transport


def _build(idempotent_turns: Any) -> _Resp:
    caps = {"usage_sessions": True, "memory_control": True, "parent_sink": True}
    if idempotent_turns is not None:
        caps["idempotent_turns"] = idempotent_turns
    return _Resp(200, {"build_id": "b", "config_hash": "h", "capabilities": caps})


_REPLY = {"turn_id": "t", "text": "hi", "build_id": "b"}
_SESSION = SessionRef(session_id="s", account_id="a")


def _adapter(outcomes: list[Any]) -> tuple[ModeBAdapter, ScriptedOpener]:
    t, opener, _ = _transport(outcomes, confirmed=False)
    return ModeBAdapter(t), opener


def _posts(opener: ScriptedOpener) -> int:
    return sum(1 for q in opener.requests if q.get_method() == "POST")


@pytest.mark.parametrize("declared", [False, None, "false", "true", 1, 0, [], {}])
def test_a_turn_is_sent_once_to_a_target_that_does_not_declare_idempotent_turns(
    declared: Any,
) -> None:
    """The reviewer's repro: the first attempt times out after the target processed the turn; a
    repeat would process it a second time."""
    adapter, opener = _adapter([_build(declared), TimeoutError(), _Resp(200, _REPLY)])
    assert adapter.capabilities().idempotent_turns is False
    with pytest.raises(TargetUnavailableError, match="1 attempt"):
        adapter.submit_turn(_SESSION, "hello", idempotency_key="k-1")
    assert _posts(opener) == 1


def test_a_turn_is_sent_once_before_the_capabilities_have_been_read() -> None:
    adapter, opener = _adapter([TimeoutError(), _Resp(200, _REPLY)])
    with pytest.raises(TargetUnavailableError):
        adapter.submit_turn(_SESSION, "hello", idempotency_key="k-1")
    assert _posts(opener) == 1


def test_a_turn_is_repeated_once_the_target_has_declared_idempotent_turns() -> None:
    adapter, opener = _adapter([_build(True), TimeoutError(), _Resp(200, _REPLY)])
    assert adapter.capabilities().idempotent_turns is True
    assert adapter.submit_turn(_SESSION, "hello", idempotency_key="k-1").turn_id == "t"
    assert _posts(opener) == 2


def test_a_target_that_withdraws_the_declaration_stops_being_repeated() -> None:
    adapter, opener = _adapter([_build(True), _build(False), TimeoutError(), _Resp(200, _REPLY)])
    adapter.capabilities()
    adapter.capabilities()
    with pytest.raises(TargetUnavailableError):
        adapter.submit_turn(_SESSION, "hello", idempotency_key="k-1")
    assert _posts(opener) == 1


def test_capabilities_that_are_not_an_object_read_as_nothing_supported() -> None:
    adapter, _ = _adapter([_Resp(200, {"build_id": "b", "config_hash": "h", "capabilities": [1]})])
    caps = adapter.capabilities()
    assert not (
        caps.idempotent_turns or caps.usage_sessions or caps.memory_control or caps.parent_sink
    )


@pytest.mark.parametrize("flag", ["usage_sessions", "memory_control", "parent_sink"])
@pytest.mark.parametrize("value", ["false", "true", 1, [1], {"a": 1}])
def test_a_capability_is_supported_only_when_it_is_the_json_literal_true(
    flag: str, value: Any
) -> None:
    """bool("false") is True: a loosely read flag marks support the target never declared, and
    a fidelity gap goes unreported (principle 5)."""
    caps = {"idempotent_turns": True, flag: value}
    adapter, _ = _adapter([_Resp(200, {"build_id": "b", "config_hash": "h", "capabilities": caps})])
    assert getattr(adapter.capabilities(), flag) is False


def test_a_new_build_in_the_build_report_withdraws_the_permission_to_repeat() -> None:
    """Capabilities were read on build b; the very next /build says b2. b2 has declared
    nothing, so a mutating call is sent once."""
    moved = _Resp(200, {"build_id": "b2", "config_hash": "h"})
    adapter, opener = _adapter([_build(True), moved, TimeoutError(), _Resp(200, _REPLY)])
    adapter.capabilities()
    assert adapter.report_build().build_id == "b2"
    with pytest.raises(TargetUnavailableError, match="1 attempt"):
        adapter.submit_turn(_SESSION, "hello", idempotency_key="k-1")
    assert _posts(opener) == 1


@pytest.mark.parametrize(
    "report",
    [
        {"capabilities": {"idempotent_turns": True}},
        {"build_id": 7, "config_hash": "h", "capabilities": {"idempotent_turns": True}},
        {"build_id": "", "config_hash": "h", "capabilities": {"idempotent_turns": True}},
        {"build_id": "b", "capabilities": {"idempotent_turns": True}},
    ],
)
def test_a_build_report_without_a_build_identity_grants_no_permission_to_repeat(
    report: dict[str, Any],
) -> None:
    """Drift protection compares build ids. With no id to compare, retries would stay enabled
    whatever build answers next, so the declaration is not accepted at all."""
    adapter, opener = _adapter([_Resp(200, report), TimeoutError(), _Resp(200, _REPLY)])
    with pytest.raises(TargetProtocolError):
        adapter.capabilities()
    with pytest.raises(TargetUnavailableError, match="1 attempt"):
        adapter.submit_turn(_SESSION, "hello", idempotency_key="k-1")
    assert _posts(opener) == 1


def test_a_failed_capability_read_withdraws_a_permission_granted_earlier() -> None:
    bad = _Resp(200, {"capabilities": {"idempotent_turns": True}})
    adapter, opener = _adapter([_build(True), bad, TimeoutError(), _Resp(200, _REPLY)])
    adapter.capabilities()
    with pytest.raises(TargetProtocolError):
        adapter.capabilities()
    with pytest.raises(TargetUnavailableError, match="1 attempt"):
        adapter.submit_turn(_SESSION, "hello", idempotency_key="k-1")
    assert _posts(opener) == 1


@pytest.mark.parametrize("bad", ["..", ".", "\ud800"])
def test_an_id_that_cannot_be_a_path_segment_is_the_target_breaking_the_contract(bad: str) -> None:
    """The workers turn TargetProtocolError into a blocked cell; any other error crashes the
    run. The id came from the target, so it is the target's error."""
    adapter = ModeBAdapter(_Recording())
    with pytest.raises(TargetProtocolError, match="unusable id"):
        adapter.start_session(AccountRef(bad), idempotency_key="k-1")


class _Recording:
    def __init__(self, reply: Response | None = None) -> None:
        self.paths: list[str] = []
        self._reply = reply

    def request(
        self, method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None
    ) -> Response:
        self.paths.append(path)
        if self._reply is not None:
            return self._reply
        return Response(200, {"account_id": "a", "session_id": "s", **_REPLY})


@pytest.mark.parametrize("key", ["", " ", "\t\n"])
@pytest.mark.parametrize(
    "call", ["create_account", "start_session", "submit_turn", "delete_account"]
)
def test_an_empty_idempotency_key_is_refused_before_anything_is_sent(call: str, key: str) -> None:
    wire = _Recording()
    adapter = ModeBAdapter(wire)
    calls = {
        "create_account": lambda: adapter.create_account(AccountSpec(13), idempotency_key=key),
        "start_session": lambda: adapter.start_session(AccountRef("a"), idempotency_key=key),
        "submit_turn": lambda: adapter.submit_turn(_SESSION, "hello", idempotency_key=key),
        "delete_account": lambda: adapter.delete_account(AccountRef("a"), idempotency_key=key),
    }
    with pytest.raises(ValueError, match="idempotency key"):
        calls[call]()
    assert wire.paths == []


_HOSTILE_ID = "../../build?x=#"
_QUOTED_ID = "..%2F..%2Fbuild%3Fx%3D%23"


def test_ids_returned_by_the_target_are_percent_quoted_into_one_path_segment() -> None:
    wire = _Recording()
    adapter = ModeBAdapter(wire)
    adapter.start_session(AccountRef(_HOSTILE_ID), idempotency_key="k")
    adapter.submit_turn(SessionRef(_HOSTILE_ID, "a"), "hello", idempotency_key="k")
    adapter.delete_account(AccountRef(_HOSTILE_ID), idempotency_key="k")
    assert wire.paths == [
        f"/accounts/{_QUOTED_ID}/sessions",
        f"/sessions/{_QUOTED_ID}/turns",
        f"/accounts/{_QUOTED_ID}",
    ]


@pytest.mark.parametrize("bad_id", ["", ".", ".."])
def test_an_id_that_is_empty_or_a_dot_segment_is_refused_before_anything_is_sent(
    bad_id: str,
) -> None:
    wire = _Recording()
    with pytest.raises(RuntimeError, match="unusable"):
        ModeBAdapter(wire).start_session(AccountRef(bad_id), idempotency_key="k")
    assert wire.paths == []


def test_ordinary_ids_are_sent_unchanged() -> None:
    wire = _Recording()
    ModeBAdapter(wire).start_session(AccountRef("acct_01-AZ.9~x"), idempotency_key="k")
    assert wire.paths == ["/accounts/acct_01-AZ.9~x/sessions"]


def test_a_success_status_with_a_malformed_body_is_a_named_error_not_a_missing_key() -> None:
    wire = _Recording(Response(200, {"error": "non-JSON body: 'OK'"}, malformed=True))
    with pytest.raises(RuntimeError, match="target returned 200: non-JSON body"):
        ModeBAdapter(wire).create_account(AccountSpec(13), idempotency_key="k")


@pytest.mark.parametrize("raw", [b"OK", b"[1,2]", b"<html>hello</html>"])
def test_a_non_json_reply_to_a_turn_is_a_named_error_end_to_end(raw: bytes) -> None:
    adapter, _ = _adapter([_Resp(200, raw)])
    with pytest.raises(RuntimeError, match="target returned 200: non-JSON body"):
        adapter.submit_turn(_SESSION, "hello", idempotency_key="k-1")


def test_an_unexpected_status_is_a_named_protocol_error_the_runner_can_report() -> None:
    from covered_evidence.adapters.protocol import TargetProtocolError
    from covered_evidence.adapters.transport import Response

    with pytest.raises(TargetProtocolError, match="500"):
        ModeBAdapter._ok(Response(status=500, body={"error": "boom"}), 200)
    with pytest.raises(TargetProtocolError, match="non-JSON"):
        ModeBAdapter._ok(Response(status=200, body={"error": "non-JSON body"}, malformed=True), 200)


@pytest.mark.parametrize(
    "call, status, body",
    [
        ("create_account", 201, {}),
        ("create_account", 201, {"account_id": 7}),
        ("start_session", 201, {"account_id": "a"}),
        ("submit_turn", 200, {"turn_id": "t", "text": "hi"}),
        ("submit_turn", 200, {"turn_id": "t", "text": "hi", "build_id": "b", "events": "none"}),
        ("report_build", 200, {"build_id": "b"}),
    ],
)
def test_a_success_missing_a_required_key_is_a_protocol_error_not_an_unknown_id(
    call: str, status: int, body: dict[str, Any]
) -> None:
    """`KeyError` is how this adapter says 404. A `201 {}` raised the same KeyError, so a caller
    could not tell an unknown account from a target that broke the contract."""
    from covered_evidence.adapters.protocol import TargetProtocolError

    class Canned:
        def request(self, method, path, headers, body_):  # type: ignore[no-untyped-def]
            return Response(status=status, body=body)

    a = ModeBAdapter(Canned())  # type: ignore[arg-type]
    with pytest.raises(TargetProtocolError, match="contract"):
        if call == "create_account":
            a.create_account(AccountSpec(declared_age=13), idempotency_key="k")
        elif call == "start_session":
            a.start_session(AccountRef("a"), idempotency_key="k")
        elif call == "submit_turn":
            a.submit_turn(SessionRef("s", "a"), "hi", idempotency_key="k")
        else:
            a.report_build()


def test_a_build_change_withdraws_the_idempotency_confirmation_until_build_is_read_again() -> None:
    """The confirmation was sticky: after the target changed build and withdrew the capability,
    the client still repeated a turn. A new build is a new target until `/build` says otherwise."""
    confirmations: list[bool] = []

    class Wire:
        def __init__(self) -> None:
            self.builds = iter(["b1", "b2"])

        def confirm_idempotent_target(self, yes: bool) -> None:
            confirmations.append(yes)

        def request(self, method, path, headers, body_):  # type: ignore[no-untyped-def]
            if path == "/build":
                caps = {"idempotent_turns": True}
                return Response(200, {"build_id": "b1", "config_hash": "h", "capabilities": caps})
            reply = {"turn_id": "t", "text": "hi", "build_id": next(self.builds), "events": []}
            return Response(200, reply)

    a = ModeBAdapter(Wire())  # type: ignore[arg-type]
    a.capabilities()
    a.submit_turn(SessionRef("s", "a"), "one", idempotency_key="k1")
    assert confirmations == [False, True]  # withdrawn while /build is read, then granted
    a.submit_turn(SessionRef("s", "a"), "two", idempotency_key="k2")
    assert confirmations == [False, True, False]


def test_an_empty_id_in_a_success_reply_is_a_protocol_error() -> None:
    """Evidence pinned to an empty build id, or an account with no id, is meaningless."""
    from covered_evidence.adapters.protocol import TargetProtocolError

    class Canned:
        def request(self, method, path, headers, body_):  # type: ignore[no-untyped-def]
            return Response(status=200, body={"build_id": "", "config_hash": "h"})

    with pytest.raises(TargetProtocolError, match="non-empty"):
        ModeBAdapter(Canned()).report_build()  # type: ignore[arg-type]
