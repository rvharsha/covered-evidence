"""Pre-publication security review of the client that holds an operator's staging token.

Items 1 (bodies that are not JSON objects), 2 (unbounded read), 4 (a true per-attempt deadline)
and 5 (the URL that carries the token). Retry policy (3, 6, 7) is in test_transport_retry.py and
the refused redirect in test_transport_redirect.py."""

from __future__ import annotations

from typing import Any

import pytest

from covered_evidence.adapters.config import TargetConfig
from covered_evidence.adapters.protocol import TargetUnavailableError
from covered_evidence.adapters.transport import MAX_BODY_BYTES, UrllibTransport
from tests.adapters.test_transport_retry import ScriptedOpener, _http_error, _Resp, _transport

_HTML = b"<html><head><title>502 Bad Gateway</title></head><body>" + b"x" * 5000 + b"</body></html>"


# item 1 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw", [b"OK", _HTML, b"[1,2]", b'"text"', b"12", b"null", b"\xff\xfe\x00", b'{"a":']
)
def test_a_success_body_that_is_not_a_json_object_is_a_malformed_response_not_a_crash(
    raw: bytes,
) -> None:
    t, _, _ = _transport([_Resp(200, raw)])
    r = t.request("GET", "/build", {}, None)
    assert r.status == 200 and r.malformed and set(r.body) == {"error"}
    assert "non-JSON" in r.body["error"]


@pytest.mark.parametrize("raw", [b"OK", _HTML, b"[1,2]", b"\xff\xfe\x00"])
def test_an_error_body_that_is_not_a_json_object_is_a_malformed_response_not_a_crash(
    raw: bytes,
) -> None:
    t, _, _ = _transport([_http_error(500, raw=raw)])
    r = t.request("POST", "/accounts", {"Idempotency-Key": "k"}, {})
    assert r.status == 500 and r.malformed and "non-JSON" in r.body["error"]


def test_a_gateway_html_page_on_a_retryable_status_is_retried_not_decoded() -> None:
    t, opener, _ = _transport([_http_error(502, raw=_HTML), _Resp(200, {"ok": 1})])
    assert t.request("GET", "/build", {}, None).body == {"ok": 1} and len(opener.requests) == 2


def test_a_non_json_body_is_quoted_only_briefly() -> None:
    t, _, _ = _transport([_Resp(200, _HTML)])
    message = t.request("GET", "/build", {}, None).body["error"]
    assert len(message) < 200 and "502 Bad Gateway" in message


def test_a_json_object_and_an_empty_body_are_ordinary_responses() -> None:
    t, _, _ = _transport([_Resp(200, {"a": [1]}), _Resp(204, b"")])
    first, second = t.request("GET", "/build", {}, None), t.request("GET", "/build", {}, None)
    assert (first.body, first.malformed) == ({"a": [1]}, False)
    assert (second.body, second.malformed) == ({}, False)


# item 2 ------------------------------------------------------------------------------------------
class _Endless(_Resp):
    """Adversarial stand-in: never runs out of body."""

    def __init__(self, status: int = 200) -> None:
        super().__init__(status, b"")
        self.served = 0

    def read1(self, n: int = -1) -> bytes:
        size = n if n and n > 0 else 1 << 16
        self.served += size
        return b"a" * size


def test_an_oversized_body_is_an_error_response_and_reading_stops_at_the_cap() -> None:
    endless = _Endless()
    t, _, _ = _transport([endless])
    r = t.request("GET", "/build", {}, None)
    assert r.status == 200 and r.malformed and "exceeds" in r.body["error"]
    assert MAX_BODY_BYTES <= 8 * 1024 * 1024 and endless.served <= MAX_BODY_BYTES + (1 << 16)


def test_a_body_exactly_at_the_cap_is_still_read() -> None:
    raw = b'{"pad":"' + b"a" * (MAX_BODY_BYTES - 10) + b'"}'
    t, _, _ = _transport([_Resp(200, raw)])
    assert len(raw) == MAX_BODY_BYTES and not t.request("GET", "/build", {}, None).malformed


# item 4 ------------------------------------------------------------------------------------------
class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Drip(_Resp):
    """Adversarial stand-in: one byte per read, each read costing ``step`` seconds of wall clock
    while staying under the per-socket-operation timeout, so urllib alone never times out."""

    def __init__(self, clock: _Clock, step: float, raw: bytes) -> None:
        super().__init__(200, raw)
        self._clock, self._step, self.reads = clock, step, 0

    def read1(self, n: int = -1) -> bytes:
        self.reads += 1
        self._clock.now += self._step
        return super().read1(1)


def test_a_dripped_body_is_abandoned_as_a_timeout_when_the_attempt_deadline_passes() -> None:
    clock = _Clock()
    drip = _Drip(clock, 0.6, b'{"ok": 1}')
    t, _, _ = _transport([drip], timeout_s=1.0, attempts=1, clock=clock)
    with pytest.raises(TargetUnavailableError, match="deadline"):
        t.request("GET", "/build", {}, None)
    assert drip.reads == 2  # 0.6 s, 1.2 s, and no third read


def test_one_request_never_outlasts_what_the_transport_states_it_can_block() -> None:
    clock = _Clock()
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds

    t = UrllibTransport(
        TargetConfig(base_url="http://localhost:8080", token="stg-1"),
        timeout_s=1.0,
        attempts=3,
        sleep=sleep,
        clock=clock,
    )
    # every read takes just under the socket timeout, the slowest a read can be without urllib
    # itself giving up; every attempt therefore ends on a read that began before the deadline
    t._opener = ScriptedOpener([_Drip(clock, 0.999, b"x" * 50) for _ in range(3)])  # type: ignore[assignment]
    started = clock.now
    with pytest.raises(TargetUnavailableError):
        t.request("GET", "/build", {}, None)
    assert clock.now - started <= t.max_block_seconds
    assert t.max_block_seconds == 3 * 2 * 1.0 + 2 * 30


def test_a_reply_that_arrives_within_the_deadline_is_read_in_pieces_and_returned() -> None:
    clock = _Clock()
    t, _, _ = _transport([_Drip(clock, 0.01, b'{"ok": 1}')], timeout_s=1.0, clock=clock)
    assert t.request("GET", "/build", {}, None).body == {"ok": 1}


def test_each_attempt_gets_its_own_deadline() -> None:
    clock = _Clock()
    outcomes: list[Any] = [_Drip(clock, 0.6, b'{"ok": 1}'), _Drip(clock, 0.01, b'{"ok": 2}')]
    t, opener, _ = _transport(outcomes, timeout_s=1.0, clock=clock)
    assert t.request("GET", "/build", {}, None).body == {"ok": 2} and len(opener.requests) == 2


# item 5 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        ".evil.example/x",
        "@evil.example/x",
        ":8443/x",
        "build",
        "",
        "//evil.example/x",
        "/\\evil.example/x",
        "/build\r\nX-Evil: 1",
        "/bu ild",
    ],
)
def test_a_path_that_could_change_the_host_or_the_request_is_refused_before_any_io(
    path: str,
) -> None:
    t = UrllibTransport(TargetConfig(base_url="https://staging.fernwood.example", token="stg-1"))
    opener = ScriptedOpener([_Resp(200, {})])
    t._opener = opener  # type: ignore[assignment]
    with pytest.raises(ValueError, match="path"):
        t.request("GET", path, {}, None)
    assert opener.requests == []


@pytest.mark.parametrize(
    ("base", "path", "url"),
    [
        ("https://staging.fernwood.example", "/build", "https://staging.fernwood.example/build"),
        (
            "https://staging.fernwood.example:8443/api/",
            "/accounts/a%2Fb/sessions",
            "https://staging.fernwood.example:8443/api/accounts/a%2Fb/sessions",
        ),
        ("http://[::1]:8080", "/build", "http://[::1]:8080/build"),
    ],
)
def test_the_token_goes_only_to_the_configured_scheme_host_and_port(
    base: str, path: str, url: str
) -> None:
    t = UrllibTransport(TargetConfig(base_url=base, token="stg-1"))
    opener = ScriptedOpener([_Resp(200, {})])
    t._opener = opener  # type: ignore[assignment]
    t.request("GET", path, {}, None)
    (req,) = opener.requests
    assert req.full_url == url and req.get_header("Authorization") == "Bearer stg-1"


def test_a_joined_url_whose_host_is_not_the_configured_one_never_carries_the_token() -> None:
    """Belt and braces: even if the base were tampered with after validation, the re-check on
    the joined URL refuses before a request object with the token exists."""
    t = UrllibTransport(TargetConfig(base_url="https://staging.fernwood.example", token="stg-1"))
    opener = ScriptedOpener([_Resp(200, {})])
    t._opener = opener  # type: ignore[assignment]
    t._base = "https://staging.fernwood.example.evil.example"
    with pytest.raises(ValueError, match="configured"):
        t.request("GET", "/build", {}, None)
    assert opener.requests == []


def test_a_certificate_failure_is_not_a_blip_and_is_never_retried() -> None:
    """Every OSError was "transient", so a TLS certificate failure was tried four times. A wrong
    certificate is not the target being slow; it is the wrong target, or an interception."""
    import ssl

    from covered_evidence.adapters.protocol import TargetUnavailableError
    from tests.adapters.test_transport_retry import _transport

    t, opener, slept = _transport([ssl.SSLCertVerificationError("self-signed certificate")] * 4)
    with pytest.raises(TargetUnavailableError, match="certificate"):
        t.request("GET", "/build", {}, None)
    assert len(opener.requests) == 1 and slept == []
