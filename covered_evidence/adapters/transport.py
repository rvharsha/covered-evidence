"""HTTP-shaped transport boundary so adapters can be tested without sockets."""

from __future__ import annotations

import http.client
import json
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from covered_evidence.adapters.config import TargetConfig
from covered_evidence.adapters.protocol import TargetRedirectError, TargetUnavailableError


@dataclass(frozen=True)
class Response:
    """``body`` is always a JSON object. When the target sent anything else (an HTML gateway page,
    a bare ``OK``, a list, more than ``MAX_BODY_BYTES``), ``malformed`` is set and ``body`` is
    ``{"error": ...}`` describing it, so a caller reports a named error instead of crashing."""

    status: int
    body: dict[str, Any]
    malformed: bool = False


class Transport(Protocol):
    def request(
        self, method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None
    ) -> Response: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A Mode B target has no reason to redirect. Following one would forward the staging
    bearer token to whatever host the redirect names, possibly over plain http."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str | None,
    ) -> None:
        raise urllib.error.HTTPError(req.full_url, code, f"redirect refused: {msg}", headers, fp)


#: answers that mean "not now", worth repeating an idempotent call for
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
_MAX_DELAY_S = 30.0
#: far more than any Mode B reply needs; a larger body is an error, not something to buffer
MAX_BODY_BYTES = 4 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
_SNIPPET_BYTES = 80
#: "did not answer": the socket, TLS, or HTTP framing failed before a whole reply arrived
_TRANSIENT = (OSError, http.client.HTTPException)


def _is_certificate_failure(error: BaseException) -> bool:
    """urllib wraps the ssl error in a URLError; look at both."""
    reason = getattr(error, "reason", None)
    return isinstance(error, ssl.SSLCertVerificationError) or isinstance(
        reason, ssl.SSLCertVerificationError
    )


def _response(status: int, raw: bytes | None) -> Response:
    """Never raises: whatever the target sent becomes a Response whose body is a dict."""
    if raw is None:
        return Response(status, {"error": f"response body exceeds {MAX_BODY_BYTES} bytes"}, True)
    if not raw:
        return Response(status, {})
    try:
        parsed = json.loads(raw)
    except (ValueError, RecursionError):  # bad JSON, bad UTF-8, or nesting deep enough to overflow
        parsed = None
    if isinstance(parsed, dict):
        return Response(status, parsed)
    snippet = raw[:_SNIPPET_BYTES].decode("utf-8", "replace")
    return Response(status, {"error": f"non-JSON body: {snippet!r}"}, True)


def _retry_after(headers: Any) -> float | None:
    """Whole seconds in ASCII digits, or nothing. ``str.isdigit`` alone is true for characters
    such as a superscript two that ``float`` rejects; a header must never raise."""
    text = str((headers.get("Retry-After") if headers else None) or "").strip()
    if text.isascii() and text.isdigit():
        return min(float(text), _MAX_DELAY_S)
    return None


def _redirect_host(headers: Any) -> str:
    """The host a refused redirect pointed at, for the error message: never the whole Location,
    which is the target's text and may be long or carry a query."""
    location = str((headers.get("Location") if headers else None) or "")
    try:
        host = urlsplit(location).netloc.rpartition("@")[2]
    except ValueError:
        host = ""
    return host[:100] or "an unnamed location"


class UrllibTransport:
    """The real thing. Only ever pointed at a validated staging TargetConfig.

    A target backed by a live model can take longer than any one timeout, and staging
    environments blip. GETs are repeated on a timeout, a broken or refused connection, or a
    429/502/503/504, honouring ``Retry-After`` up to a cap. A mutating call is repeated only when
    it carries a non-empty ``Idempotency-Key`` AND the target has declared that it honours the
    key (``confirm_idempotent_target``, which the adapter calls after reading ``GET /build``);
    otherwise it is attempted exactly once, because repeating it could make the target process
    one turn twice (principle 9). When the attempts run out the caller gets
    ``TargetUnavailableError``, not a crashed run.

    The bearer token goes only to the configured scheme, host and port: no proxy from the
    environment, no redirect (``TargetRedirectError``), and a request path cannot alter the
    authority. Each attempt has a wall-clock deadline of ``timeout_s`` enforced between chunked
    reads, because urllib's own timeout applies to each socket operation, not to the attempt."""

    def __init__(
        self,
        config: TargetConfig,
        timeout_s: float = 90.0,
        *,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(config, TargetConfig):
            raise TypeError("UrllibTransport takes a validated TargetConfig (principle 8)")
        self._base = config.base_url.rstrip("/")
        parts = urlsplit(config.base_url)
        self._origin = (parts.scheme, parts.netloc)
        self._token = config.token
        self._timeout = timeout_s
        self._attempts = attempts
        self._sleep = sleep
        self._clock = clock
        self._repeat_mutations = False
        # ProxyHandler({}): build_opener otherwise installs one that reads http_proxy/https_proxy
        # and the system settings, and the Authorization header would travel through that proxy.
        self._opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))

    def confirm_idempotent_target(self, confirmed: bool) -> None:
        """Off until the target's own capability report says ``idempotent_turns: true``. While
        off, no mutating call is repeated, whatever key it carries."""
        self._repeat_mutations = confirmed is True

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def max_block_seconds(self) -> float:
        """How long one ``request`` is expected to block at most. NOT a hard bound: the response
        body is cut off at a wall-clock deadline, but connecting, the TLS handshake and receipt
        of the response headers are limited only per socket operation, so a target that drips
        its headers can exceed this. Size a lease from it with margin, and make losing the lease
        harmless (the workers stand down), rather than relying on it.

        Per attempt: the wall-clock deadline (``timeout_s``) plus one socket operation that
        began just before it and may itself take ``timeout_s``; between attempts, the longest
        wait. Connecting and receiving the response headers are bounded per socket operation
        by ``timeout_s`` and checked against the deadline as soon as they return."""
        return self._attempts * 2 * self._timeout + (self._attempts - 1) * _MAX_DELAY_S

    def _url(self, path: str) -> str:
        if (
            not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or not path.isascii()
            or any(c.isspace() or not c.isprintable() for c in path)
        ):
            raise ValueError(
                f"request path {path!r} must start with a single '/' and be printable ASCII "
                "with no backslash or whitespace"
            )
        url = self._base + path
        joined = urlsplit(url)
        if (joined.scheme, joined.netloc) != self._origin:
            raise ValueError("request URL is not on the configured scheme and host; token withheld")
        return url

    def _build(
        self, method: str, path: str, headers: dict[str, str], data: bytes | None
    ) -> urllib.request.Request:
        req = urllib.request.Request(self._url(path), data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        return req

    def _read(self, source: Any, deadline: float) -> bytes | None:
        """The body, or None once it passes ``MAX_BODY_BYTES``. ``read1`` returns after at most
        one socket read, so the clock is consulted between reads and a body dripped a byte at
        a time cannot hold the attempt past its deadline by more than one socket timeout."""
        chunks: list[bytes] = []
        size = 0
        while True:
            if self._clock() >= deadline:
                raise TimeoutError(f"no complete reply by the {self._timeout:g} s attempt deadline")
            chunk = source.read1(_CHUNK_BYTES)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return None
            chunks.append(chunk)

    def request(
        self, method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None
    ) -> Response:
        data = json.dumps(body).encode() if body is not None else None
        keyed = bool(headers.get("Idempotency-Key", "").strip())
        repeatable = method == "GET" or (keyed and self._repeat_mutations)
        tries = self._attempts if repeatable else 1
        last = ""
        for attempt in range(tries):
            delay = min(float(2**attempt), _MAX_DELAY_S)
            req = self._build(method, path, headers, data)
            deadline = self._clock() + self._timeout
            try:
                try:
                    with self._opener.open(req, timeout=self._timeout) as resp:
                        status, reply_headers = int(resp.status), resp.headers
                        raw = self._read(resp, deadline)
                except urllib.error.HTTPError as e:
                    status, reply_headers = e.code, e.headers
                    try:
                        raw = self._read(e, deadline) if e.fp is not None else b""
                    finally:
                        if e.fp is not None:
                            e.close()
            except _TRANSIENT as e:
                if _is_certificate_failure(e):
                    # not the target being slow: the wrong target, or an interception
                    raise TargetUnavailableError(
                        f"TLS certificate verification failed and is never retried: {e}"
                    ) from None
                last = str(e) or type(e).__name__
            else:
                if 300 <= status < 400:
                    raise TargetRedirectError(
                        f"target answered {status}, a redirect to {_redirect_host(reply_headers)}; "
                        "redirects are never followed (the staging token stays with the "
                        "configured host)"
                    )
                if status not in _RETRYABLE_STATUS:
                    return _response(status, raw)
                last = f"HTTP {status}"
                after = _retry_after(reply_headers)
                delay = delay if after is None else after
            if attempt + 1 < tries:
                self._sleep(delay)
        raise TargetUnavailableError(f"target did not answer after {tries} attempt(s): {last}")
