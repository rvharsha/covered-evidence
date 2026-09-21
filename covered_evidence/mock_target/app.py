"""HTTP-shaped facade over MockTarget implementing the Mode B endpoints.

``handle`` takes (method, path, headers, body) and returns (status, body),
so it can be driven in-process by tests or mounted behind any WSGI/ASGI
server for a live Mode B demo. No sockets here.
"""

from __future__ import annotations

import re
from typing import Any

from covered_evidence.adapters.protocol import AccountRef, AccountSpec, SessionRef
from covered_evidence.mock_target.target import MockTarget

_ACCOUNT_SESSIONS = re.compile(r"^/accounts/([^/]+)/sessions$")
_ACCOUNT = re.compile(r"^/accounts/([^/]+)$")
_SESSION_TURNS = re.compile(r"^/sessions/([^/]+)/turns$")


class MockTargetApp:
    def __init__(self, target: MockTarget) -> None:
        self.target = target

    def handle(
        self, method: str, path: str, headers: dict[str, str], body: Any
    ) -> tuple[int, dict[str, Any]]:
        """``body`` is whatever the request's JSON decoded to, so it is checked, not trusted."""
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return 400, {"error": "request body must be a JSON object"}
        # HTTP header names are case-insensitive (RFC 9110 section 5.1).
        keys = {v for k, v in headers.items() if k.lower() == "idempotency-key"}
        if len(keys) > 1:
            return 400, {
                "error": "Idempotency-Key header given more than once with different values"
            }
        key = keys.pop() if keys else None
        try:
            return self._route(method, path, key, body)
        except KeyError as e:
            return 404, {"error": str(e).strip("'")}
        except ValueError as e:
            return 409, {"error": str(e)}

    def _route(
        self, method: str, path: str, key: str | None, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        t = self.target
        if method == "GET" and path == "/build":
            b = t.report_build()
            c = t.capabilities()
            return 200, {
                "build_id": b.build_id,
                "config_hash": b.config_hash,
                "capabilities": {
                    "idempotent_turns": c.idempotent_turns,
                    "usage_sessions": c.usage_sessions,
                    "memory_control": c.memory_control,
                    "parent_sink": c.parent_sink,
                },
            }
        if key is None:
            return 400, {"error": "Idempotency-Key header required"}
        if not key.strip():
            return 400, {"error": "Idempotency-Key header must not be empty"}
        if method == "POST" and path == "/accounts":
            age = body.get("declared_age")
            if not isinstance(age, int) or isinstance(age, bool):
                return 400, {"error": "declared_age must be an integer"}
            flags = {f: body.get(f, False) for f in ("parent_linked", "persistent_memory")}
            for name, value in flags.items():
                if not isinstance(value, bool):
                    return 400, {"error": f"{name} must be a boolean"}
            spec = AccountSpec(declared_age=age, **flags)
            ref = t.create_account(spec, idempotency_key=key)
            return 201, {"account_id": ref.account_id}
        if method == "POST" and (m := _ACCOUNT_SESSIONS.match(path)):
            sref = t.start_session(AccountRef(m.group(1)), idempotency_key=key)
            return 201, {"session_id": sref.session_id, "account_id": sref.account_id}
        if method == "POST" and (m := _SESSION_TURNS.match(path)):
            sid = m.group(1)
            if not isinstance(body.get("text"), str):
                return 400, {"error": "text must be a string"}
            account_id = t.session_account(sid) or ""
            reply = t.submit_turn(SessionRef(sid, account_id), body["text"], idempotency_key=key)
            return 200, {
                "turn_id": reply.turn_id,
                "text": reply.text,
                "build_id": reply.build_id,
                "events": [{"kind": e.kind.value, "detail": e.detail} for e in reply.events],
            }
        if method == "DELETE" and (m := _ACCOUNT.match(path)):
            t.delete_account(AccountRef(m.group(1)), idempotency_key=key)
            return 204, {}
        return 404, {"error": f"no route for {method} {path}"}
