"""the bundle data model and its JSON Schema."""

from __future__ import annotations

import json

import pytest

from covered_evidence.bundle.schema import (
    Bundle,
    CellTerminalState,
    EvidenceStatus,
    FindingLevel,
    FindingStatus,
    Severity,
    VerificationMode,
    bundle_json_schema,
)
from tests.bundle.factories import minimal_bundle_dict


def test_evidence_status_has_exactly_the_five_states() -> None:
    assert {e.value for e in EvidenceStatus} == {
        "observed",
        "client_attested",
        "manually_inspected",
        "not_assessed",
        "blocked",
    }


def test_finding_status_has_exactly_the_four_states() -> None:
    assert {e.value for e in FindingStatus} == {
        "observed",
        "under_remediation",
        "not_observed_in_verification",
        "risk_accepted",
    }


def test_finding_level_has_exactly_the_three_levels() -> None:
    assert {e.value for e in FindingLevel} == {"output", "conversation", "account_timeline"}


def test_verification_mode_has_exactly_the_three_modes() -> None:
    assert {e.value for e in VerificationMode} == {
        "exact_replay",
        "adaptive_replay",
        "held_out_variation",
    }


def test_severity_levels_are_ordered_critical_first() -> None:
    assert [s.value for s in Severity] == ["critical", "high", "medium", "low"]


def test_cell_terminal_states_are_completed_blocked_not_assessed() -> None:
    assert {e.value for e in CellTerminalState} == {"completed", "blocked", "not_assessed"}


def test_minimal_bundle_round_trips_through_dict_and_json() -> None:
    d = minimal_bundle_dict()
    b = Bundle.from_dict(d)
    again = Bundle.from_dict(json.loads(json.dumps(b.to_dict())))
    assert again == b


def test_from_dict_rejects_unknown_evidence_status() -> None:
    d = minimal_bundle_dict()
    d["requirements"][0]["status"] = "compliant"
    with pytest.raises(ValueError, match="requirements\\[0\\]\\.status"):
        Bundle.from_dict(d)


def test_from_dict_rejects_missing_required_field() -> None:
    d = minimal_bundle_dict()
    del d["cover"]
    with pytest.raises(ValueError, match="cover"):
        Bundle.from_dict(d)


def test_from_dict_rejects_unknown_field_so_typos_do_not_pass_silently() -> None:
    d = minimal_bundle_dict()
    d["findigns"] = []
    with pytest.raises(ValueError, match="findigns"):
        Bundle.from_dict(d)


def test_json_schema_is_a_draft_2020_object_schema_with_required_top_level_keys() -> None:
    schema = bundle_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    for key in ("cover", "requirements", "findings", "verification", "coverage", "issuance"):
        assert key in schema["required"], key


def test_json_schema_enumerates_evidence_statuses_on_requirement_status() -> None:
    schema = bundle_json_schema()
    req = schema["properties"]["requirements"]["items"]
    assert set(req["properties"]["status"]["enum"]) == {e.value for e in EvidenceStatus}
