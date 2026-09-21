"""Security fix: the real transport never follows a redirect, so the staging bearer token
cannot be forwarded to another host or downgraded to plain http."""

from __future__ import annotations

import email.message
import io
import urllib.error
import urllib.request
import urllib.response

import pytest

from covered_evidence.adapters.config import TargetConfig
from covered_evidence.adapters.protocol import TargetRedirectError, TargetUnavailableError
from covered_evidence.adapters.transport import UrllibTransport, _NoRedirect


def test_redirect_handler_refuses_every_3xx() -> None:
    h = _NoRedirect()
    req = urllib.request.Request("https://staging.example/x")
    with pytest.raises(urllib.error.HTTPError) as exc:
        h.redirect_request(req, None, 302, "Found", {"Location": "http://evil.example/"}, None)  # type: ignore[arg-type]
    assert exc.value.code == 302


def test_transport_installs_the_no_redirect_handler() -> None:
    t = UrllibTransport(TargetConfig(base_url="https://staging.example", token="stg-token"))
    assert any(isinstance(h, _NoRedirect) for h in t._opener.handlers)
    assert not any(type(h) is urllib.request.HTTPRedirectHandler for h in t._opener.handlers)


# Pre-publication security review, item 1: the tests above exercise the handler, not request().
class _CannedHandler(urllib.request.BaseHandler):
    """Stands in for the socket layer inside the real opener, so the real redirect handling and
    error processing run; records every request so a followed redirect would be visible."""

    handler_order = 100  # ahead of the stock HTTP(S) handlers, which would open a socket

    def __init__(self, code: int, location: str | None) -> None:
        self.code, self.location = code, location
        self.seen: list[str] = []

    def _answer(self, req: urllib.request.Request) -> urllib.response.addinfourl:
        self.seen.append(req.full_url)
        headers = email.message.Message()
        if self.location is not None:
            headers["Location"] = self.location
        resp = urllib.response.addinfourl(
            io.BytesIO(b"<html>moved</html>"), headers, req.full_url, self.code
        )
        resp.msg = "Found"  # type: ignore[attr-defined]
        return resp

    https_open = _answer
    http_open = _answer


def _redirecting(code: int, location: str | None) -> tuple[UrllibTransport, _CannedHandler]:
    t = UrllibTransport(
        TargetConfig(base_url="https://staging.fernwood.example", token="stg-token"),
        sleep=lambda _s: None,
    )
    t.confirm_idempotent_target(True)
    canned = _CannedHandler(code, location)
    t._opener.add_handler(canned)
    return t, canned


@pytest.mark.parametrize("code", [300, 301, 302, 303, 304, 305, 307, 308])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_request_raises_a_named_error_for_any_3xx_and_never_follows_it(
    code: int, method: str
) -> None:
    t, canned = _redirecting(code, "https://elsewhere.example/collect")
    with pytest.raises(TargetRedirectError, match=str(code)):
        t.request(method, "/build", {"Idempotency-Key": "k"}, None if method == "GET" else {})
    assert canned.seen == ["https://staging.fernwood.example/build"]


def test_a_redirect_is_an_unavailable_target_so_the_cell_is_blocked_not_the_run_crashed() -> None:
    assert issubclass(TargetRedirectError, TargetUnavailableError)


def test_the_redirect_error_names_the_host_pointed_at_without_echoing_the_location() -> None:
    t, _ = _redirecting(302, "https://elsewhere.example/" + "a" * 5000 + "?secret=1")
    with pytest.raises(TargetRedirectError) as exc:
        t.request("GET", "/build", {}, None)
    assert "elsewhere.example" in str(exc.value) and len(str(exc.value)) < 300
    assert "secret" not in str(exc.value)


def test_a_redirect_without_a_location_is_still_the_named_error() -> None:
    t, _ = _redirecting(302, None)
    with pytest.raises(TargetRedirectError):
        t.request("GET", "/build", {}, None)
