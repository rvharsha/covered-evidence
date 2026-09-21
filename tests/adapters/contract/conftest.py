"""The contract suite runs against every adapter. Add a param here to certify a new one.

Two adapters today: the mock target used directly (in-process), and the
Mode B webhook adapter speaking HTTP semantics to the mock through an
in-process transport (no sockets; unit tests make no network calls).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from covered_evidence.adapters.mode_b import ModeBAdapter
from covered_evidence.adapters.protocol import TargetAdapter
from covered_evidence.mock_target.app import MockTargetApp
from covered_evidence.mock_target.target import MockTarget, MockTargetConfig
from tests.fakes.clock import FakeClock
from tests.fakes.transport import InProcessTransport


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def mock(clock: FakeClock) -> MockTarget:
    return MockTarget(
        clock=clock,
        config=MockTargetConfig(build_id="pip-c", config_hash="sha256:" + "c" * 64),
    )


@pytest.fixture(params=["in_process", "mode_b"])
def adapter(request: pytest.FixtureRequest, mock: MockTarget) -> TargetAdapter:
    make: dict[str, Callable[[], TargetAdapter]] = {
        "in_process": lambda: mock,
        "mode_b": lambda: ModeBAdapter(InProcessTransport(MockTargetApp(mock))),
    }
    return make[request.param]()
