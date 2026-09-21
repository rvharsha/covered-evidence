"""Mode B: the reference webhook adapter.

Five endpoints the operator implements in staging:

    POST   /accounts                      create account
    POST   /accounts/{id}/sessions        start session
    POST   /sessions/{id}/turns           submit turn
    DELETE /accounts/{id}                 delete account
    GET    /build                         report build

Every mutating call carries an ``Idempotency-Key`` header. The operator must
return the original response for a repeated key and 409 for a key reused
with a different request body.

A mutating call is repeated by the transport only after ``GET /build`` has reported
``idempotent_turns: true``; a target that does not honour the key would process a repeated turn
twice. Ids the target returns are data: they are percent-quoted into a single path segment.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from covered_evidence.adapters.protocol import (
    AccountRef,
    AccountSpec,
    AdapterCapabilities,
    BuildReport,
    SessionRef,
    TargetProtocolError,
    TurnEvent,
    TurnEventKind,
    TurnReply,
)
from covered_evidence.adapters.transport import Response, Transport

VERSION = "mode-b-0.1.0"


def _required(body: dict[str, Any], key: str, kind: type) -> Any:
    """A success that lacks a required key, or has it with the wrong type, is the target breaking
    the contract. It must not surface as KeyError, which this adapter uses to mean 404."""
    value = body.get(key)
    if not isinstance(value, kind) or isinstance(value, bool):
        raise TargetProtocolError(
            f"target broke the contract: a success reply must carry {key!r} as {kind.__name__}"
        )
    if isinstance(value, str) and not value.strip():
        raise TargetProtocolError(
            f"target broke the contract: {key!r} must be non-empty; evidence pinned to an "
            "empty id means nothing"
        )
    return value


def _event(e: dict[str, Any]) -> TurnEvent:
    kind = str(e.get("kind", ""))
    detail = str(e.get("detail", ""))
    try:
        return TurnEvent(kind=TurnEventKind(kind), detail=detail)
    except ValueError:
        return TurnEvent(kind=TurnEventKind.OTHER, detail=f"{kind}: {detail}".rstrip(": "))


def _segment(target_id: str) -> str:
    """One path segment, whatever the target put in the id: no '/', '?', '#' or dot-segment can
    turn an id into a different endpoint."""
    try:
        quoted = quote(target_id, safe="")
    except UnicodeEncodeError:  # an unpaired surrogate
        quoted = ""
    if quoted in ("", ".", ".."):
        # the target's error, so the target's error type: the workers block the cell on it
        raise TargetProtocolError(f"target returned an unusable id {target_id!r}")
    return quoted


def _keyed(idempotency_key: str) -> dict[str, str]:
    if not idempotency_key.strip():
        raise ValueError("an empty idempotency key is never sent (principle 9)")
    return {"Idempotency-Key": idempotency_key}


class ModeBAdapter:
    version = VERSION

    def __init__(self, transport: Transport) -> None:
        self._t = transport
        #: the build whose capabilities were last read; None until `/build` is read
        self._build: str | None = None

    @staticmethod
    def _ok(resp: Response, *expected: int) -> dict[str, Any]:
        if resp.status in expected and not resp.malformed:
            return resp.body
        message = str(resp.body.get("error", resp.status))
        if resp.status == 404:
            raise KeyError(message)
        if resp.status == 409:
            raise ValueError(message)
        raise TargetProtocolError(f"target returned {resp.status}: {message}")

    @property
    def max_block_seconds(self) -> float:
        """How long one call to the target can block, as the transport reports it."""
        return float(getattr(self._t, "max_block_seconds", 0.0))

    def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> AccountRef:
        body = self._ok(
            self._t.request(
                "POST",
                "/accounts",
                _keyed(idempotency_key),
                {
                    "declared_age": spec.declared_age,
                    "parent_linked": spec.parent_linked,
                    "persistent_memory": spec.persistent_memory,
                },
            ),
            200,
            201,
        )
        return AccountRef(account_id=_required(body, "account_id", str))

    def start_session(self, account: AccountRef, *, idempotency_key: str) -> SessionRef:
        body = self._ok(
            self._t.request(
                "POST",
                f"/accounts/{_segment(account.account_id)}/sessions",
                _keyed(idempotency_key),
                {},
            ),
            200,
            201,
        )
        return SessionRef(
            session_id=_required(body, "session_id", str), account_id=account.account_id
        )

    def submit_turn(self, session: SessionRef, text: str, *, idempotency_key: str) -> TurnReply:
        body = self._ok(
            self._t.request(
                "POST",
                f"/sessions/{_segment(session.session_id)}/turns",
                _keyed(idempotency_key),
                {"text": text},
            ),
            200,
            201,
        )
        events = body.get("events", [])
        if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
            raise TargetProtocolError("target broke the contract: events must be a list of objects")
        reply = TurnReply(
            turn_id=_required(body, "turn_id", str),
            text=_required(body, "text", str),
            build_id=_required(body, "build_id", str),
            events=[_event(e) for e in events],
        )
        self._saw_build(reply.build_id)
        return reply

    def delete_account(self, account: AccountRef, *, idempotency_key: str) -> None:
        self._ok(
            self._t.request(
                "DELETE",
                f"/accounts/{_segment(account.account_id)}",
                _keyed(idempotency_key),
                None,
            ),
            200,
            204,
        )

    def _saw_build(self, build_id: str) -> None:
        """A reply from a build other than the one whose capabilities were read is a new target
        until `/build` is read again: the permission to repeat mutating calls is withdrawn."""
        known = self._build
        if known is not None and build_id != known:
            confirm = getattr(self._t, "confirm_idempotent_target", None)
            if callable(confirm):
                confirm(False)
            self._build = None

    def report_build(self) -> BuildReport:
        body = self._ok(self._t.request("GET", "/build", {}, None), 200)
        report = BuildReport(
            build_id=_required(body, "build_id", str),
            config_hash=_required(body, "config_hash", str),
        )
        self._saw_build(report.build_id)
        return report

    def capabilities(self) -> AdapterCapabilities:
        # Fail closed: the permission to repeat mutating calls is withdrawn before the report
        # is read and granted again only by a whole, identified one. Drift protection compares
        # build ids, so a declaration that names no build is not accepted.
        confirm = getattr(self._t, "confirm_idempotent_target", None)
        if callable(confirm):
            confirm(False)
        self._build = None
        body = self._ok(self._t.request("GET", "/build", {}, None), 200)
        build = _required(body, "build_id", str)
        _required(body, "config_hash", str)
        caps = body.get("capabilities", {})
        if not isinstance(caps, dict):
            caps = {}
        # strictly the JSON literal true, for every flag: bool("false") is True. The transport
        # repeats mutating calls on the strength of the first; the others decide what the
        # fidelity report may call supported (principle 5).
        idempotent = caps.get("idempotent_turns") is True
        if callable(confirm):
            confirm(idempotent)
        self._build = build
        return AdapterCapabilities(
            idempotent_turns=idempotent,
            usage_sessions=caps.get("usage_sessions") is True,
            memory_control=caps.get("memory_control") is True,
            parent_sink=caps.get("parent_sink") is True,
        )
