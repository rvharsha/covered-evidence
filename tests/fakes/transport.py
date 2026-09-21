"""In-process HTTP-shaped transport: routes requests straight to a MockTargetApp."""

from __future__ import annotations

from typing import Any

from covered_evidence.adapters.transport import Response
from covered_evidence.mock_target.app import MockTargetApp


class InProcessTransport:
    def __init__(self, app: MockTargetApp) -> None:
        self.app = app
        self.log: list[tuple[str, str]] = []

    def request(
        self, method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None
    ) -> Response:
        self.log.append((method, path))
        status, payload = self.app.handle(method, path, headers, body)
        return Response(status=status, body=payload)
