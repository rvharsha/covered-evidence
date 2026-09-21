from __future__ import annotations

import pytest

from covered_evidence.mock_target.target import MockTarget, MockTargetConfig
from tests.fakes.clock import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def target(clock: FakeClock) -> MockTarget:
    return MockTarget(
        clock=clock, config=MockTargetConfig(build_id="pip-1", config_hash="sha256:" + "1" * 64)
    )
