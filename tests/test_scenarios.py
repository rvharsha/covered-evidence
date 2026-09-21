"""the statute-to-scenario map is executable."""

from __future__ import annotations

import re

import pytest

from covered_evidence.scenarios import (
    PROHIBITED_BEHAVIORS,
    RESTRICTED_CODES,
    SCENARIOS,
    EvidenceStatus,
    scenario,
    scenarios_for_behavior,
)

APPENDIX_CODES = {
    "SH", "HO", "DX", "SX", "RO", "IS", "BR", "SN", "GF",
    "AD", "SY", "PC", "CR", "NT", "DP", "PR", "DS",
}  # fmt: skip

CITATION = re.compile(r"^§2181\d(\.5)?(\([A-Za-z0-9]+\))*$")


def test_every_appendix_code_resolves_and_no_extras_exist() -> None:
    assert set(SCENARIOS) == APPENDIX_CODES


@pytest.mark.parametrize("code", sorted(APPENDIX_CODES))
def test_scenario_has_at_least_one_well_formed_citation(code: str) -> None:
    s = scenario(code)
    assert s.citations, f"{code} has no citations"
    for c in s.citations:
        assert CITATION.match(c), f"{code} citation {c!r} is not in §NNNNN(x)(y) form"


def test_restricted_categories_are_exactly_sh_sx_ro_is() -> None:
    assert {"SH", "SX", "RO", "IS"} == RESTRICTED_CODES


@pytest.mark.parametrize("numeral", PROHIBITED_BEHAVIORS)
def test_each_of_the_fourteen_prohibited_behaviors_has_a_scenario(numeral: str) -> None:
    assert scenarios_for_behavior(numeral), f"(d)(5)(A)({numeral}) has no scenario"


def test_there_are_exactly_fourteen_prohibited_behaviors() -> None:
    assert len(PROHIBITED_BEHAVIORS) == 14
    assert PROHIBITED_BEHAVIORS[0] == "i"
    assert PROHIBITED_BEHAVIORS[-1] == "xiv"


def test_prohibited_behavior_claims_match_the_citation_text() -> None:
    for s in SCENARIOS.values():
        for numeral in s.prohibited_behaviors:
            assert any(c.startswith(f"§21812(d)(5)(A)({numeral})") for c in s.citations), (
                f"{s.code} claims ({numeral}) but no citation carries it"
            )


def test_evidence_targets_are_observed_for_every_scenario() -> None:
    # The appendix targets Observed for all codes; DP, PR, DS qualify it in notes.
    assert all(s.evidence_target is EvidenceStatus.OBSERVED for s in SCENARIOS.values())


def test_evidence_status_enum_has_the_five_states() -> None:
    assert {e.value for e in EvidenceStatus} == {
        "observed",
        "client_attested",
        "manually_inspected",
        "not_assessed",
        "blocked",
    }


def test_unknown_code_error_lists_known_codes() -> None:
    with pytest.raises(KeyError, match="unknown scenario code 'ZZ'"):
        scenario("ZZ")


def test_unknown_behavior_numeral_is_rejected() -> None:
    with pytest.raises(ValueError):
        scenarios_for_behavior("xv")
