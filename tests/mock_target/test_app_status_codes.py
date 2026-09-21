"""Review fix: malformed requests are 400s, not 404s or 409s."""

from __future__ import annotations

import pytest

from covered_evidence.adapters.protocol import AccountSpec
from covered_evidence.mock_target.app import MockTargetApp
from covered_evidence.mock_target.target import MockTarget, MockTargetConfig
from tests.fakes.clock import FakeClock


def _app() -> MockTargetApp:
    return MockTargetApp(
        MockTarget(
            clock=FakeClock(),
            config=MockTargetConfig(build_id="b", config_hash="sha256:" + "0" * 64),
        )
    )


def test_missing_text_field_is_a_400() -> None:
    app = _app()
    status, body = app.handle("POST", "/accounts", {"Idempotency-Key": "a"}, {"declared_age": 13})
    sid = app.handle(
        "POST", f"/accounts/{body['account_id']}/sessions", {"Idempotency-Key": "s"}, {}
    )[1]["session_id"]
    status, body = app.handle("POST", f"/sessions/{sid}/turns", {"Idempotency-Key": "t"}, {})
    assert status == 400 and "text" in body["error"]


def test_non_integer_age_is_a_400() -> None:
    status, body = _app().handle(
        "POST", "/accounts", {"Idempotency-Key": "a"}, {"declared_age": "thirteen"}
    )
    assert status == 400 and "declared_age" in body["error"]


def test_unknown_session_is_still_a_404() -> None:
    status, _ = _app().handle(
        "POST", "/sessions/nope/turns", {"Idempotency-Key": "t"}, {"text": "hi"}
    )
    assert status == 404


@pytest.mark.parametrize("field", ["parent_linked", "persistent_memory"])
@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, []])
def test_a_non_boolean_account_flag_is_a_400_not_a_truthiness_guess(
    field: str, value: object
) -> None:
    """``bool("false")`` is True: a string flag once linked a parent nobody asked to link."""
    app = _app()
    status, body = app.handle(
        "POST", "/accounts", {"Idempotency-Key": "a"}, {"declared_age": 13, field: value}
    )
    assert status == 400 and field in body["error"]
    assert app.target.effects == []


def test_boolean_account_flags_reach_the_account_as_given() -> None:
    app = _app()
    status, _ = app.handle(
        "POST",
        "/accounts",
        {"Idempotency-Key": "a"},
        {"declared_age": 13, "parent_linked": True, "persistent_memory": False},
    )
    (effect,) = app.target.effects
    assert status == 201
    assert effect.args == (AccountSpec(13, parent_linked=True, persistent_memory=False),)


@pytest.mark.parametrize("body", [[], [{"declared_age": 13}], "text", 7, True])
def test_a_json_body_that_is_not_an_object_is_a_400(body: object) -> None:
    status, reply = _app().handle("POST", "/accounts", {"Idempotency-Key": "a"}, body)
    assert status == 400 and "object" in reply["error"]


@pytest.mark.parametrize("name", ["idempotency-key", "IDEMPOTENCY-KEY", "Idempotency-key"])
def test_the_idempotency_key_header_name_is_matched_in_any_case(name: str) -> None:
    status, _ = _app().handle("POST", "/accounts", {name: "a"}, {"declared_age": 13})
    assert status == 201


def test_the_same_key_under_two_header_spellings_is_one_request() -> None:
    app = _app()
    first = app.handle("POST", "/accounts", {"Idempotency-Key": "a"}, {"declared_age": 13})
    second = app.handle("POST", "/accounts", {"idempotency-key": "a"}, {"declared_age": 13})
    assert first == second and len(app.target.effects) == 1


def test_two_idempotency_key_headers_that_disagree_are_a_400() -> None:
    status, _ = _app().handle(
        "POST", "/accounts", {"Idempotency-Key": "a", "idempotency-key": "b"}, {"declared_age": 13}
    )
    assert status == 400


@pytest.mark.parametrize("key", ["", " ", "\t"])
def test_an_empty_idempotency_key_is_a_400_because_it_identifies_nothing(key: str) -> None:
    app = _app()
    status, body = app.handle("POST", "/accounts", {"Idempotency-Key": key}, {"declared_age": 13})
    assert status == 400 and "Idempotency-Key" in body["error"]
    assert app.target.effects == []
