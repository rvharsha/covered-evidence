"""PR review 1 (principle 8): the real transport only exists over a validated TargetConfig."""

from __future__ import annotations

import pytest

from covered_evidence.adapters.config import ConfigError, TargetConfig
from covered_evidence.adapters.transport import UrllibTransport


def test_transport_takes_a_validated_config_not_a_raw_url() -> None:
    cfg = TargetConfig(base_url="https://staging.fernwood.example/api/", token="stg-1")
    t = UrllibTransport(cfg)
    assert t.base_url == "https://staging.fernwood.example/api"


def test_a_production_looking_url_cannot_reach_the_transport() -> None:
    with pytest.raises(ConfigError):
        UrllibTransport(TargetConfig(base_url="https://api.fernwood.example", token="stg-1"))


def test_raw_strings_are_rejected() -> None:
    with pytest.raises(TypeError):
        UrllibTransport("https://staging.fernwood.example", "stg-1")  # type: ignore[arg-type]
