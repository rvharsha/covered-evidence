"""The TargetAdapter protocol: five operations, each side effect idempotency-keyed.

This is the seam between Covered and an operator's staging target. Both the
in-repo mock target and every real adapter satisfy it, and the contract suite
in tests/adapters/contract is the specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True)
class AccountSpec:
    """What the operator's system knows about the synthetic account.

    ``declared_age`` is the age the operator's own age determination would
    hold, not the evaluator-only persona band. Persistent memory defaults
    off, matching the §21812(d)(3) default.
    """

    declared_age: int
    parent_linked: bool = False
    persistent_memory: bool = False


@dataclass(frozen=True)
class AccountRef:
    account_id: str


@dataclass(frozen=True)
class SessionRef:
    session_id: str
    account_id: str


class TurnEventKind(StrEnum):
    USAGE_CAP = "usage_cap"
    AI_NOTICE = "ai_notice"
    BREAK_REMINDER = "break_reminder"
    PARENT_NOTIFIED = "parent_notified"
    OTHER = "other"  # an operator-specific kind we do not model; the original kind is in detail


@dataclass(frozen=True)
class TurnEvent:
    kind: TurnEventKind
    detail: str = ""


@dataclass(frozen=True)
class TurnReply:
    turn_id: str
    text: str
    build_id: str
    events: list[TurnEvent] = field(default_factory=list)


@dataclass(frozen=True)
class BuildReport:
    build_id: str
    config_hash: str


@dataclass(frozen=True)
class AdapterCapabilities:
    """What the target can support. Anything false is reported as blocked, never hidden."""

    idempotent_turns: bool
    usage_sessions: bool
    memory_control: bool
    parent_sink: bool


class TargetAdapter(Protocol):
    def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> AccountRef: ...

    def start_session(self, account: AccountRef, *, idempotency_key: str) -> SessionRef: ...

    def submit_turn(self, session: SessionRef, text: str, *, idempotency_key: str) -> TurnReply: ...

    def delete_account(self, account: AccountRef, *, idempotency_key: str) -> None: ...

    def report_build(self) -> BuildReport: ...

    def capabilities(self) -> AdapterCapabilities: ...


class TargetUnavailableError(RuntimeError):
    """The staging target did not answer within the transport's retries. Reported as a blocked
    cell with the stage named, never as a crashed run (principle 5)."""


class TargetRedirectError(TargetUnavailableError):
    """The staging target answered with a 3xx. A Mode B target has no reason to redirect, and
    following one would hand the staging bearer token to whatever host it names, so it is never
    followed and never taken for an answer. Reported like any other unavailable target: a blocked
    cell with the stage named (principle 5)."""


class TargetProtocolError(RuntimeError):
    """The target answered, but outside the contract: an unexpected status (a 500), or a success
    whose body is not a JSON object. Reported as a blocked cell with the stage named, never as a
    crashed run (principle 5). It is not retried: the target did answer."""
