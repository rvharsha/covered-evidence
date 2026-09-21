"""The in-process mock can persist its accounts, sessions, and idempotency cache to a file so
a second process (a re-run a later run) sees the same target; the real target keeps this
state itself. Observations (`requests`, `effects`) stay per process."""

from __future__ import annotations

from pathlib import Path

from covered_evidence.adapters.protocol import AccountSpec
from covered_evidence.mock_target.target import MockTarget, MockTargetConfig
from tests.fakes.clock import FakeClock


def _mock(path: Path) -> MockTarget:
    return MockTarget(
        clock=FakeClock(),
        config=MockTargetConfig(build_id="b", config_hash="sha256:" + "0" * 64, faults=[]),
        state_path=path,
    )


def test_a_second_process_sees_the_same_accounts_sessions_and_idempotency_cache(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mock.state"
    m1 = _mock(path)
    acct = m1.create_account(
        AccountSpec(declared_age=13, persistent_memory=False), idempotency_key="a"
    )
    sess = m1.start_session(acct, idempotency_key="s")
    reply = m1.submit_turn(sess, "hello", idempotency_key="t0")
    m2 = _mock(path)
    assert m2.submit_turn(sess, "hello", idempotency_key="t0") == reply  # replayed, not re-sent
    assert m2.effects == []
    again = m2.submit_turn(sess, "and again", idempotency_key="t1")
    assert again.turn_id != reply.turn_id
    m3 = _mock(path)
    assert m3.session_account(sess.session_id) == acct.account_id
    assert (
        m3.create_account(
            AccountSpec(declared_age=13, persistent_memory=False), idempotency_key="a"
        )
        == acct
    )


def test_without_a_state_path_nothing_is_written(tmp_path: Path) -> None:
    m = MockTarget(
        clock=FakeClock(),
        config=MockTargetConfig(build_id="b", config_hash="sha256:" + "0" * 64, faults=[]),
    )
    m.create_account(AccountSpec(declared_age=13, persistent_memory=False), idempotency_key="a")
    assert list(tmp_path.iterdir()) == []


def test_the_state_file_is_plain_json(tmp_path: Path) -> None:
    import json

    path = tmp_path / "mock.state"
    m = _mock(path)
    acct = m.create_account(
        AccountSpec(declared_age=13, persistent_memory=True), idempotency_key="a"
    )
    sess = m.start_session(acct, idempotency_key="s")
    m.submit_turn(sess, "hello", idempotency_key="t0")
    state = json.loads(path.read_text())
    assert acct.account_id in state["accounts"] and sess.session_id in state["sessions"]


def test_a_pickle_planted_at_the_state_path_is_refused_and_never_executed(tmp_path: Path) -> None:
    """A public reference server must not run code from a file it is pointed at."""
    import pickle

    import pytest

    sentinel = tmp_path / "executed"

    class Boom:
        def __reduce__(self):  # type: ignore[no-untyped-def]
            return (Path.touch, (sentinel,))

    path = tmp_path / "mock.state"
    path.write_bytes(pickle.dumps(Boom()))
    with pytest.raises(ValueError, match="state file"):
        _mock(path)
    assert not sentinel.exists()


def test_usage_memory_events_and_deletion_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "mock.state"
    m1 = _mock(path)
    acct = m1.create_account(
        AccountSpec(declared_age=13, persistent_memory=True), idempotency_key="a"
    )
    sess = m1.start_session(acct, idempotency_key="s")
    reply = m1.submit_turn(sess, "my hamster is called Biscuit", idempotency_key="t0")
    usage = m1.usage_sessions(acct.account_id)
    m2 = _mock(path)
    assert m2.usage_sessions(acct.account_id) == usage
    replayed = m2.submit_turn(sess, "my hamster is called Biscuit", idempotency_key="t0")
    assert replayed == reply and replayed.events == reply.events
    m2.delete_account(acct, idempotency_key="d")
    m3 = _mock(path)
    m3.delete_account(acct, idempotency_key="d")  # replayed, not an error
    assert m3.effects == []


def _valid_state(tmp_path: Path) -> dict:  # type: ignore[type-arg]
    import json

    path = tmp_path / "seed.state"
    m = _mock(path)
    acct = m.create_account(
        AccountSpec(declared_age=13, persistent_memory=True), idempotency_key="a"
    )
    sess = m.start_session(acct, idempotency_key="s")
    m.submit_turn(sess, "hello", idempotency_key="t0")
    linked = m.create_account(
        AccountSpec(declared_age=13, parent_linked=True), idempotency_key="a2"
    )
    linked_sess = m.start_session(linked, idempotency_key="s2")
    m.submit_turn(linked_sess, "[[crisis-signal]]", idempotency_key="t1")  # placeholder token
    # a third account is the deleted one: deleting removes what the account holds, and the
    # state above must keep its parent notification
    gone = m.create_account(AccountSpec(declared_age=13), idempotency_key="a3")
    m.delete_account(gone, idempotency_key="d3")
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def _first(d: dict) -> dict:  # type: ignore[type-arg]
    return next(iter(d.values()))  # type: ignore[no-any-return]


def _break_accounts_list(s: dict) -> None:  # type: ignore[type-arg]
    s["accounts"] = []


def _break_sessions_scalar(s: dict) -> None:  # type: ignore[type-arg]
    s["sessions"] = "nope"


def _break_idem_arity(s: dict) -> None:  # type: ignore[type-arg]
    s["idem"][0] = s["idem"][0][:3]


def _break_idem_result_untagged_object(s: dict) -> None:  # type: ignore[type-arg]
    s["idem"][0][3] = {"anything": "goes"}


def _break_reply_event_kind(s: dict) -> None:  # type: ignore[type-arg]
    reply = next(e[3] for e in s["idem"] if isinstance(e[3], dict))
    reply["events"] = [{"kind": "not_a_kind", "detail": ""}]


def _break_reply_text_type(s: dict) -> None:  # type: ignore[type-arg]
    next(e[3] for e in s["idem"] if isinstance(e[3], dict))["text"] = 7


def _break_seq(s: dict) -> None:  # type: ignore[type-arg]
    s["seq"] = "three"


def _break_age(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["spec"]["declared_age"] = "13"


def _break_bool(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["deleted"] = "no"


def _break_timestamp(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["sessions"])["started_at"] = "yesterday"


def _break_facts(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["persistent_facts"] = [1, 2]


def _break_missing_key(s: dict) -> None:  # type: ignore[type-arg]
    del s["parent_notifications"]


def _break_top_level(s: dict) -> None:  # type: ignore[type-arg]
    s.clear()


def _cached(s: dict, method: str) -> list:  # type: ignore[type-arg]
    return next(e for e in s["idem"] if e[0] == method)  # type: ignore[no-any-return]


def _reply(s: dict) -> dict:  # type: ignore[type-arg]
    return _cached(s, "submit_turn")[3]  # type: ignore[no-any-return]


def _break_seq_behind_the_issued_ids(s: dict) -> None:  # type: ignore[type-arg]
    s["seq"] = 0  # the next create_account would hand out acct-1 again and overwrite it


def _break_seq_behind_a_cached_turn_id(s: dict) -> None:  # type: ignore[type-arg]
    _reply(s)["turn_id"] = "turn-1000001"


def _break_account_id_not_one_the_mock_issues(s: dict) -> None:  # type: ignore[type-arg]
    acct = s["accounts"].pop("acct-1")
    acct["ref"]["account_id"] = "acct-one"
    s["accounts"]["acct-one"] = acct
    for sess in s["sessions"].values():
        if sess["ref"]["account_id"] == "acct-1":
            sess["ref"]["account_id"] = "acct-one"
    _cached(s, "create_account")[3] = "acct-one"


def _break_naive_session_timestamp(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["sessions"])["started_at"] = "2026-09-14T09:00:00"


def _break_naive_notice_timestamp(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["sessions"])["last_notice_at"] = "2026-09-14T09:00:00"


def _break_naive_usage_timestamp(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["usage"][0]["last_turn_at"] = "2026-09-14T09:00:00"


def _break_naive_notification_timestamp(s: dict) -> None:  # type: ignore[type-arg]
    s["parent_notifications"][0]["sent_at"] = "2026-09-14T09:00:00"


def _break_cached_turn_is_a_string(s: dict) -> None:  # type: ignore[type-arg]
    _cached(s, "submit_turn")[3] = "turn-3"


def _break_cached_account_is_null(s: dict) -> None:  # type: ignore[type-arg]
    _cached(s, "create_account")[3] = None


def _break_cached_session_is_a_turn_reply(s: dict) -> None:  # type: ignore[type-arg]
    _cached(s, "start_session")[3] = _reply(s)


def _break_cached_deletion_is_a_string(s: dict) -> None:  # type: ignore[type-arg]
    _cached(s, "delete_account")[3] = "acct-1"


def _break_cached_account_does_not_exist(s: dict) -> None:  # type: ignore[type-arg]
    _cached(s, "create_account")[3] = "acct-5"


def _break_cached_session_does_not_exist(s: dict) -> None:  # type: ignore[type-arg]
    _cached(s, "start_session")[3] = "sess-1"


def _break_cached_method_unknown(s: dict) -> None:  # type: ignore[type-arg]
    _cached(s, "delete_account")[0] = "drop_everything"


def _break_cached_entry_repeated(s: dict) -> None:  # type: ignore[type-arg]
    s["idem"].append(list(s["idem"][0]))


def _break_session_of_a_missing_account(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["sessions"])["ref"]["account_id"] = "acct-2"


def _break_account_key_differs_from_its_ref(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["ref"]["account_id"] = "acct-4"  # the other account's id


def _break_session_key_differs_from_its_ref(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["sessions"])["ref"]["session_id"] = "sess-5"  # the other session's id


def _break_negative_turn_count(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["sessions"])["turn_count"] = -1


def _break_usage_session_ends_before_it_starts(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["usage"][0]["last_turn_at"] = "2020-01-01T00:00:00+00:00"


def _break_notification_for_a_missing_session(s: dict) -> None:  # type: ignore[type-arg]
    s["parent_notifications"][0]["session_id"] = "sess-1"


def _break_unknown_key_top_level(s: dict) -> None:  # type: ignore[type-arg]
    s["extra"] = 1


def _break_unknown_key_account(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["extra"] = 1


def _break_unknown_key_spec(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["spec"]["extra"] = 1


def _break_unknown_key_account_ref(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["ref"]["extra"] = 1


def _break_unknown_key_usage(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["accounts"])["usage"][0]["extra"] = 1


def _break_unknown_key_session(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["sessions"])["extra"] = 1


def _break_unknown_key_session_ref(s: dict) -> None:  # type: ignore[type-arg]
    _first(s["sessions"])["ref"]["extra"] = 1


def _break_unknown_key_notification(s: dict) -> None:  # type: ignore[type-arg]
    s["parent_notifications"][0]["extra"] = 1


def _break_unknown_key_reply(s: dict) -> None:  # type: ignore[type-arg]
    _reply(s)["extra"] = 1


def _break_unknown_key_event(s: dict) -> None:  # type: ignore[type-arg]
    _reply(s)["events"][0]["extra"] = 1


_BREAKS = [
    _break_seq_behind_the_issued_ids,
    _break_seq_behind_a_cached_turn_id,
    _break_account_id_not_one_the_mock_issues,
    _break_naive_session_timestamp,
    _break_naive_notice_timestamp,
    _break_naive_usage_timestamp,
    _break_naive_notification_timestamp,
    _break_cached_turn_is_a_string,
    _break_cached_account_is_null,
    _break_cached_session_is_a_turn_reply,
    _break_cached_deletion_is_a_string,
    _break_cached_account_does_not_exist,
    _break_cached_session_does_not_exist,
    _break_cached_method_unknown,
    _break_cached_entry_repeated,
    _break_session_of_a_missing_account,
    _break_account_key_differs_from_its_ref,
    _break_session_key_differs_from_its_ref,
    _break_negative_turn_count,
    _break_usage_session_ends_before_it_starts,
    _break_notification_for_a_missing_session,
    _break_unknown_key_top_level,
    _break_unknown_key_account,
    _break_unknown_key_spec,
    _break_unknown_key_account_ref,
    _break_unknown_key_usage,
    _break_unknown_key_session,
    _break_unknown_key_session_ref,
    _break_unknown_key_notification,
    _break_unknown_key_reply,
    _break_unknown_key_event,
    _break_accounts_list,
    _break_sessions_scalar,
    _break_idem_arity,
    _break_idem_result_untagged_object,
    _break_reply_event_kind,
    _break_reply_text_type,
    _break_seq,
    _break_age,
    _break_bool,
    _break_timestamp,
    _break_facts,
    _break_missing_key,
    _break_top_level,
]


import pytest  # noqa: E402


@pytest.mark.parametrize("damage", _BREAKS, ids=lambda f: f.__name__)
def test_well_formed_json_of_the_wrong_shape_is_refused_at_load_not_at_replay(
    tmp_path: Path, damage
) -> None:  # type: ignore[no-untyped-def]
    """json.loads checks syntax only. The whole document is validated before any
    of it becomes state, so a bad value can never survive loading and fail later on a replay."""
    import json

    state = _valid_state(tmp_path)
    damage(state)
    path = tmp_path / "mock.state"
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="not valid JSON state"):
        _mock(path)


def test_the_state_the_mock_writes_is_state_the_mock_loads(tmp_path: Path) -> None:
    """The control for the breaks above: undamaged, the same seed document loads."""
    import json

    path = tmp_path / "mock.state"
    path.write_text(json.dumps(_valid_state(tmp_path)))
    assert _mock(path).session_account("sess-2") == "acct-1"


def test_a_negative_seq_is_refused_even_when_no_id_has_been_issued(tmp_path: Path) -> None:
    import json

    empty = {"accounts": {}, "sessions": {}, "idem": [], "seq": -1, "parent_notifications": []}
    path = tmp_path / "mock.state"
    path.write_text(json.dumps(empty))
    with pytest.raises(ValueError, match="not valid JSON state"):
        _mock(path)


def test_json_nested_too_deeply_to_parse_is_refused_as_invalid_state(tmp_path: Path) -> None:
    path = tmp_path / "mock.state"
    path.write_text("[" * 100_000 + "]" * 100_000)
    with pytest.raises(ValueError, match="not valid JSON state"):
        _mock(path)


def test_a_directory_at_the_state_path_is_refused_as_invalid_state(tmp_path: Path) -> None:
    path = tmp_path / "mock.state"
    path.mkdir()
    with pytest.raises(ValueError, match="not valid JSON state"):
        _mock(path)


def test_a_json_array_at_the_top_level_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mock.state"
    path.write_text("[]")
    with pytest.raises(ValueError, match="not valid JSON state"):
        _mock(path)


def test_a_state_file_with_a_duplicate_key_is_refused(tmp_path: Path) -> None:
    """json.loads keeps the last duplicate; an untrusted file must not get to pick which of two
    values a reader and the loader each see."""
    import json

    state = _valid_state(tmp_path)
    text = json.dumps(state).replace('"seq":', '"seq": 0, "seq":', 1)
    path = tmp_path / "mock.state"
    path.write_text(text)
    with pytest.raises(ValueError, match="not valid JSON state"):
        _mock(path)


def test_a_cached_request_fingerprint_that_is_not_json_is_refused_at_load(tmp_path: Path) -> None:
    """A garbage fingerprint loaded fine and then turned every replay of that key into a 409."""
    import json

    state = _valid_state(tmp_path)
    state["idem"][0][2] = "not a fingerprint"
    path = tmp_path / "mock.state"
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="not valid JSON state"):
        _mock(path)
