"""production-looking targets and same-family judges are validation errors."""

from __future__ import annotations

import pytest

from covered_evidence.adapters.config import ConfigError, ModelPolicy, TargetConfig


@pytest.mark.parametrize(
    "url",
    [
        "https://staging.fernwood.example/api",
        "https://pip-stg.fernwood.example",
        "https://sandbox.fernwood.example",
        "http://localhost:8080",
        "http://127.0.0.1:9000",
    ],
)
def test_staging_looking_hosts_are_accepted(url: str) -> None:
    TargetConfig(base_url=url, token="stg-token-123")


@pytest.mark.parametrize(
    "url",
    [
        "https://api.fernwood.example",
        "https://fernwood.example/chat",
        "https://prod.fernwood.example",
        "https://www.fernwood.example",
    ],
)
def test_hosts_without_a_staging_marker_are_rejected(url: str) -> None:
    with pytest.raises(ConfigError, match="not recognisably staging"):
        TargetConfig(base_url=url, token="stg-token-123")


@pytest.mark.parametrize("token", ["prod-abc", "PRODUCTION_KEY", "live_sk_123", "sk_live_abc"])
def test_production_looking_credentials_are_rejected(token: str) -> None:
    with pytest.raises(ConfigError, match="credential looks like production"):
        TargetConfig(base_url="https://staging.fernwood.example", token=token)


def test_plain_http_is_only_allowed_for_loopback() -> None:
    with pytest.raises(ConfigError, match="https"):
        TargetConfig(base_url="http://staging.fernwood.example", token="stg-token")


def test_judge_family_equal_to_actor_family_is_rejected() -> None:
    with pytest.raises(ConfigError, match="judge and actor"):
        ModelPolicy(actor_family="family-a", judge_family="family-a", target_family=None)


def test_judge_family_equal_to_known_target_family_is_rejected() -> None:
    with pytest.raises(ConfigError, match="judge and target"):
        ModelPolicy(actor_family="family-a", judge_family="family-b", target_family="family-b")


def test_unknown_target_family_is_allowed_and_recorded_as_unknown() -> None:
    p = ModelPolicy(actor_family="family-a", judge_family="family-b", target_family=None)
    assert p.target_family_known is False


def test_family_comparison_is_case_and_whitespace_insensitive() -> None:
    with pytest.raises(ConfigError):
        ModelPolicy(actor_family="Family-A ", judge_family="family-a", target_family=None)


@pytest.mark.parametrize(
    "url",
    [
        "https://staging.prod.example.com",
        "https://api-prod-staging.example.com",
        "https://live-stg.example.com",
    ],
)
def test_a_host_with_a_production_label_is_rejected_even_if_it_also_says_staging(url: str) -> None:
    with pytest.raises(ConfigError, match="production"):
        TargetConfig(base_url=url, token="stg-token-123")


# Pre-publication security review, item 5: the URL that is validated is the URL that is dialled.
@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost",
        "file://localhost/etc/passwd",
        "ws://localhost:8080",
        "ftp://staging.fernwood.example",
        "//staging.fernwood.example",
    ],
)
def test_only_http_and_https_schemes_are_accepted_even_for_loopback(url: str) -> None:
    with pytest.raises(ConfigError, match="scheme"):
        TargetConfig(base_url=url, token="stg-token-123")


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pw@staging.fernwood.example",
        "https://user@staging.fernwood.example",
        "https://staging.x@staging.fernwood.example",
        "https://@staging.fernwood.example",
    ],
)
def test_userinfo_in_the_base_url_is_rejected(url: str) -> None:
    with pytest.raises(ConfigError, match="userinfo"):
        TargetConfig(base_url=url, token="stg-token-123")


@pytest.mark.parametrize(
    "url",
    [
        "https://staging.fernwood.example?x=",
        "https://staging.fernwood.example/api?x=1",
        "https://staging.fernwood.example?",
        "https://staging.fernwood.example#frag",
        "https://staging.fernwood.example/api#",
    ],
)
def test_a_query_or_fragment_in_the_base_url_is_rejected(url: str) -> None:
    with pytest.raises(ConfigError, match="query or fragment"):
        TargetConfig(base_url=url, token="stg-token-123")


@pytest.mark.parametrize("token", ["", " ", "\t\n", "stg token", "stg-1\r\nX-Evil: 1", "stg-\x00"])
def test_an_empty_or_whitespace_bearing_token_is_rejected(token: str) -> None:
    with pytest.raises(ConfigError, match="token"):
        TargetConfig(base_url="https://staging.fernwood.example", token=token)


@pytest.mark.parametrize(
    "url",
    [
        "https://staging.x@evil.com",
        "https://staging.fernwood.example\\@evil.com",
        "https://localhost.evil.com",
        "https://localhost.",
        "http://localhost.",
        "http://localhost.evil.com",
        "https://stagıng.fernwood.example",  # dotless i in the marker label
        "https://xn--stging-wta.fernwood.example",  # punycode of a lookalike marker label
        "https://staging.fеrnwood.example",  # Cyrillic e: not the name that was reviewed
        "https://staging.fernwood.example:notaport",
        "https://staging.fernwood.example:99999",
        "https://staging.fernwood.example /api",
        "https://[staging.fernwood.example",
    ],
)
def test_lookalike_and_malformed_hosts_are_rejected(url: str) -> None:
    with pytest.raises(ConfigError):
        TargetConfig(base_url=url, token="stg-token-123")


def test_a_punycode_domain_with_a_genuine_ascii_staging_label_is_accepted() -> None:
    TargetConfig(base_url="https://staging.xn--80ak6aa92e.example", token="stg-token-123")


def test_ipv6_loopback_is_accepted_over_plain_http() -> None:
    TargetConfig(base_url="http://[::1]:8080", token="stg-token-123")
