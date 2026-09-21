"""the fidelity checklist probes a target at onboarding
and reports every gap as blocked or client-attested, never hidden."""

from __future__ import annotations

from covered_evidence.adapters.fidelity import run_fidelity_checklist
from covered_evidence.adapters.protocol import AdapterCapabilities
from covered_evidence.bundle.schema import EvidenceStatus
from covered_evidence.mock_target.target import MockTarget, MockTargetConfig
from tests.fakes.clock import FakeClock


def _mock() -> MockTarget:
    return MockTarget(
        clock=FakeClock(),
        config=MockTargetConfig(build_id="pip-f", config_hash="sha256:" + "0" * 64),
    )


def test_full_fidelity_mock_passes_every_probe() -> None:
    report = run_fidelity_checklist(_mock(), key_prefix="fid-1")
    assert {i.name for i in report.items} >= {
        "idempotent_turns",
        "build_id_on_replies",
        "memory_control",
        "usage_sessions",
        "parent_sink",
    }
    assert all(
        i.status is EvidenceStatus.OBSERVED
        for i in report.items
        if i.name in ("idempotent_turns", "build_id_on_replies", "memory_control")
    )
    assert report.gaps == []


def test_capability_flags_alone_are_client_attested_not_observed() -> None:
    report = run_fidelity_checklist(_mock(), key_prefix="fid-2")
    by = {i.name: i for i in report.items}
    assert by["usage_sessions"].status is EvidenceStatus.CLIENT_ATTESTED
    assert by["parent_sink"].status is EvidenceStatus.CLIENT_ATTESTED


def test_a_target_that_ignores_idempotency_is_reported_blocked() -> None:
    mock = _mock()

    class Forgetful:
        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(mock, name)

        def submit_turn(self, session, text, *, idempotency_key):  # type: ignore[no-untyped-def]
            return mock.submit_turn(session, text, idempotency_key=f"{idempotency_key}:{mock._seq}")

    report = run_fidelity_checklist(Forgetful(), key_prefix="fid-3")  # type: ignore[arg-type]
    by = {i.name: i for i in report.items}
    assert by["idempotent_turns"].status is EvidenceStatus.BLOCKED
    assert "idempotent_turns" in report.gaps


def test_a_target_without_memory_control_capability_is_blocked_for_memory_cells() -> None:
    mock = _mock()

    class NoMemory:
        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(mock, name)

        def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(True, True, False, True)

    report = run_fidelity_checklist(NoMemory(), key_prefix="fid-4")  # type: ignore[arg-type]
    by = {i.name: i for i in report.items}
    assert by["memory_control"].status is EvidenceStatus.BLOCKED


def test_checklist_cleans_up_the_accounts_it_created() -> None:
    mock = _mock()
    run_fidelity_checklist(mock, key_prefix="fid-5")
    created = [e for e in mock.effects if e.method == "create_account"]
    deleted = [e for e in mock.effects if e.method == "delete_account"]
    assert created and len(created) == len(deleted)
