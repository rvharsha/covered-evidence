"""A slow or briefly unavailable staging target must not end a run. Every mutating Mode B call
carries an Idempotency-Key, so repeating it is safe by contract (principle 9) once the target has
declared that it honours the key; the transport retries those and GETs, and gives up with a
named error the worker can report."""

from __future__ import annotations

import http.client
import io
import json
import ssl
import urllib.error
from typing import Any

import pytest

from covered_evidence.adapters.config import TargetConfig
from covered_evidence.adapters.protocol import TargetUnavailableError
from covered_evidence.adapters.transport import UrllibTransport


class _Resp:
    """A response the way the transport reads one: ``read1`` in pieces until nothing is left."""

    def __init__(self, status: int, body: dict[str, Any] | bytes) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self._fp = io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())

    def read1(self, n: int = -1) -> bytes:
        return self._fp.read1(n)

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


class ScriptedOpener:
    """Adversarial stand-in: fails the scripted number of times, then answers."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.requests: list[Any] = []

    def open(self, req: Any, timeout: float) -> Any:
        self.requests.append(req)
        out = self._outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


def _http_error(
    code: int, retry_after: str | None = None, raw: bytes = b'{"error":"busy"}'
) -> urllib.error.HTTPError:
    hdrs: Any = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("http://x", code, "err", hdrs, io.BytesIO(raw))


def _transport(
    outcomes: list[Any], *, confirmed: bool = True, **kw: Any
) -> tuple[UrllibTransport, ScriptedOpener, list[float]]:
    """``confirmed`` stands for the adapter having seen ``idempotent_turns: true`` on /build;
    without it no mutating call is ever repeated (security review, item 3)."""
    slept: list[float] = []
    t = UrllibTransport(
        TargetConfig(base_url="http://localhost:8080", token="stg-1"), sleep=slept.append, **kw
    )
    t.confirm_idempotent_target(confirmed)
    opener = ScriptedOpener(outcomes)
    t._opener = opener  # type: ignore[assignment]
    return t, opener, slept


def test_a_timed_out_idempotent_call_is_repeated_with_the_same_key_until_it_answers() -> None:
    t, opener, slept = _transport(
        [TimeoutError("timed out"), TimeoutError(), _Resp(200, {"ok": 1})]
    )
    r = t.request("POST", "/sessions/s/turns", {"Idempotency-Key": "k-1"}, {"text": "hi"})
    assert r.status == 200 and r.body == {"ok": 1}
    assert [q.get_header("Idempotency-key") for q in opener.requests] == ["k-1"] * 3
    assert len(slept) == 2 and slept[1] > slept[0] > 0


def test_a_503_or_429_is_retried_and_retry_after_is_honoured_but_capped() -> None:
    t, opener, slept = _transport(
        [_http_error(503, "2"), _http_error(429, "9999"), _Resp(201, {"ok": 1})]
    )
    r = t.request("POST", "/accounts", {"Idempotency-Key": "k-2"}, {"declared_age": 13})
    assert r.status == 201 and len(opener.requests) == 3
    assert slept[0] == 2 and slept[1] <= 30


def test_a_get_is_retried_too() -> None:
    t, opener, _ = _transport([urllib.error.URLError("connection refused"), _Resp(200, {"b": 1})])
    assert t.request("GET", "/build", {}, None).body == {"b": 1} and len(opener.requests) == 2


def test_a_mutating_call_without_an_idempotency_key_is_never_repeated() -> None:
    t, opener, _ = _transport([TimeoutError(), _Resp(200, {})])
    with pytest.raises(TargetUnavailableError):
        t.request("POST", "/accounts", {}, {"declared_age": 13})
    assert len(opener.requests) == 1


def test_it_gives_up_with_a_named_error_after_the_last_attempt() -> None:
    t, opener, _ = _transport([TimeoutError()] * 4)
    with pytest.raises(TargetUnavailableError, match="4 attempt"):
        t.request("POST", "/sessions/s/turns", {"Idempotency-Key": "k-3"}, {"text": "hi"})
    assert len(opener.requests) == 4


def test_other_client_errors_are_still_plain_responses() -> None:
    t, opener, _ = _transport([_http_error(409)])
    assert t.request("POST", "/accounts", {"Idempotency-Key": "k"}, {}).status == 409
    assert len(opener.requests) == 1


def test_the_transport_states_the_longest_one_call_can_block() -> None:
    """the worker lease must outlast this, or another execution can take a
    job while its call is still in flight. Security review, item 4: an attempt can run to its
    deadline and then sit out one socket operation that began just before it, so each attempt
    counts twice the timeout."""
    t, _, _ = _transport([])
    assert t.max_block_seconds == 4 * (90 + 90) + 3 * 30


# Pre-publication security review, item 3 -----------------------------------------------------
def test_a_keyed_mutating_call_is_attempted_once_until_the_target_is_confirmed_idempotent() -> None:
    t, opener, slept = _transport([TimeoutError(), _Resp(200, {"ok": 1})], confirmed=False)
    with pytest.raises(TargetUnavailableError, match="1 attempt"):
        t.request("POST", "/sessions/s/turns", {"Idempotency-Key": "k-1"}, {"text": "hi"})
    assert len(opener.requests) == 1 and slept == []


def test_a_new_transport_does_not_repeat_mutating_calls_by_default() -> None:
    t = UrllibTransport(TargetConfig(base_url="http://localhost:8080", token="stg-1"))
    opener = ScriptedOpener([_http_error(503), _Resp(200, {"ok": 1})])
    t._opener = opener  # type: ignore[assignment]
    with pytest.raises(TargetUnavailableError):
        t.request("POST", "/accounts", {"Idempotency-Key": "k-1"}, {})
    assert len(opener.requests) == 1


def test_a_get_is_repeated_even_before_the_target_is_confirmed_idempotent() -> None:
    t, opener, _ = _transport([TimeoutError(), _Resp(200, {"b": 1})], confirmed=False)
    assert t.request("GET", "/build", {}, None).body == {"b": 1} and len(opener.requests) == 2


def test_withdrawing_the_confirmation_stops_repeats_again() -> None:
    t, opener, _ = _transport([TimeoutError(), _Resp(200, {})])
    t.confirm_idempotent_target(False)
    with pytest.raises(TargetUnavailableError):
        t.request("DELETE", "/accounts/a", {"Idempotency-Key": "k-1"}, None)
    assert len(opener.requests) == 1


@pytest.mark.parametrize("key", ["", " ", "\t", "\u00a0"])
def test_an_empty_or_whitespace_idempotency_key_never_makes_a_call_repeatable(key: str) -> None:
    t, opener, _ = _transport([TimeoutError(), _Resp(200, {})])
    with pytest.raises(TargetUnavailableError):
        t.request("POST", "/accounts", {"Idempotency-Key": key}, {})
    assert len(opener.requests) == 1


# item 6 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "header", ["\u00b2", "\u0663", "1\u00b2", "-5", "1.5", "soon", "Wed, 21 Oct 2026 07:28:00 GMT"]
)
def test_a_retry_after_that_is_not_ascii_digits_is_ignored_not_fatal(header: str) -> None:
    t, _, slept = _transport([_http_error(503, header), _Resp(200, {"ok": 1})])
    assert t.request("GET", "/build", {}, None).status == 200
    assert slept == [1.0]  # the ordinary first backoff


def test_an_absurdly_long_retry_after_is_capped_not_fatal() -> None:
    t, _, slept = _transport([_http_error(503, "9" * 5000), _Resp(200, {"ok": 1})])
    assert t.request("GET", "/build", {}, None).status == 200 and slept == [30.0]


# item 7 ------------------------------------------------------------------------------------------
class _FailingBody(io.BytesIO):
    def __init__(self, exc: BaseException) -> None:
        super().__init__(b"")
        self._exc = exc

    def read1(self, size: int | None = -1, /) -> bytes:
        raise self._exc

    def read(self, size: int | None = -1, /) -> bytes:
        raise self._exc


@pytest.mark.parametrize(
    "failure",
    [
        http.client.IncompleteRead(b"par"),
        http.client.BadStatusLine("garbage"),
        http.client.RemoteDisconnected("closed without a response"),
        http.client.LineTooLong("header line"),
        ConnectionResetError("reset"),
        ssl.SSLError("record layer failure"),
        OSError("network is unreachable"),
    ],
)
def test_a_connection_that_breaks_is_the_same_transient_condition_as_a_timeout(
    failure: BaseException,
) -> None:
    t, opener, _ = _transport([failure, _Resp(200, {"ok": 1})])
    assert t.request("GET", "/build", {}, None).body == {"ok": 1} and len(opener.requests) == 2


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), http.client.IncompleteRead(b"")])
def test_an_error_body_that_cannot_be_read_is_transient_not_a_crash(failure: BaseException) -> None:
    broken = urllib.error.HTTPError("http://x", 500, "err", {}, _FailingBody(failure))  # type: ignore[arg-type]
    t, opener, _ = _transport([broken, _Resp(200, {"ok": 1})])
    assert t.request("GET", "/build", {}, None).body == {"ok": 1} and len(opener.requests) == 2


def test_a_success_body_that_breaks_mid_read_ends_in_the_named_error_when_not_repeatable() -> None:
    class _Broken(_Resp):
        def read1(self, n: int = -1) -> bytes:
            raise http.client.IncompleteRead(b"{")

    t, opener, _ = _transport([_Broken(200, {})], confirmed=False)
    with pytest.raises(TargetUnavailableError, match="IncompleteRead"):
        t.request("POST", "/accounts", {"Idempotency-Key": "k"}, {})
    assert len(opener.requests) == 1


def test_no_proxy_is_used_even_when_the_environment_names_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy would be handed the staging bearer token (in clear, for an http target)."""
    for name in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.setenv(name, "http://proxy.elsewhere.example:3128")
    t = UrllibTransport(TargetConfig(base_url="https://staging.fernwood.example", token="stg-1"))
    assert [h for h in t._opener.handlers if getattr(h, "proxies", None)] == []
