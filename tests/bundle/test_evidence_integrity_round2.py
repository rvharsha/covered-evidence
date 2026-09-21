"""Second pass of the holes the first round of fixes left or opened."""

from __future__ import annotations

import dataclasses
import json

import pytest

from covered_evidence.bundle.amend import amend
from covered_evidence.bundle.lint import LegalConclusionError, legal_conclusions
from covered_evidence.bundle.schema import (
    Bundle,
    CellTerminalState,
    EvidenceStatus,
    FindingStatus,
    Severity,
)
from covered_evidence.bundle.signing import HmacSigner, sign_bundle
from tests.bundle.factories import bundle_from, finding_dict, minimal_bundle_dict

SIGNER = HmacSigner(b"k1")


def _amend(bundle: Bundle, change):  # type: ignore[no-untyped-def]
    return amend(
        bundle, amendment_id="amd-1", issued_at="t", description="d", change=change, signer=SIGNER
    )


# --- N1: identifiers are unique, everywhere they key something ---------------------------------
def test_a_duplicate_finding_id_is_refused_on_load_so_no_lookup_can_pick_the_wrong_copy() -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(severity="low", human_confirmed=False), finding_dict()]
    with pytest.raises(ValueError, match="duplicate finding_id"):
        bundle_from(d)


@pytest.mark.parametrize(
    "mutate, what",
    [
        (lambda d: d["requirements"].append(dict(d["requirements"][0])), "citation"),
        (
            lambda d: d["coverage"]["planned_cells"].append(d["coverage"]["planned_cells"][0]),
            "planned",
        ),
        (lambda d: d["coverage"]["outcomes"].append(dict(d["coverage"]["outcomes"][0])), "cell_id"),
        (
            lambda d: d.__setitem__(
                "open_risks",
                [{"risk_id": "R-1", "description": "a", "owner": "o", "rationale": "r"}] * 2,
            ),
            "risk_id",
        ),
    ],
)
def test_every_identifier_that_keys_a_record_must_be_unique(mutate, what: str) -> None:  # type: ignore[no-untyped-def]
    d = minimal_bundle_dict()
    mutate(d)
    with pytest.raises(ValueError, match=f"duplicate {what}"):
        bundle_from(d)


def test_an_amendment_cannot_smuggle_in_a_demoted_copy_under_an_existing_id() -> None:
    """The attack: insert a low, unconfirmed, not-observed copy of F-BR-001 AHEAD of the real
    one. Every rule keyed findings by id, last one wins, so the copy passed with changes=[]."""
    before = sign_bundle(
        bundle_from({**minimal_bundle_dict(), "findings": [finding_dict()]}), SIGNER
    )
    ghost = dataclasses.replace(
        before.findings[0],
        severity=Severity.LOW,
        human_confirmed=False,
        status=FindingStatus.NOT_OBSERVED_IN_VERIFICATION,
    )
    with pytest.raises(ValueError, match="duplicate finding_id"):
        _amend(before, lambda b: dataclasses.replace(b, findings=[ghost, *b.findings]))


# --- N6: an amendment corrects the record; it never upgrades the evidence ------------------------
def _blocked_bundle() -> Bundle:
    d = minimal_bundle_dict()
    d["requirements"][0]["status"] = "blocked"
    d["coverage"]["outcomes"][0].update(terminal_state="blocked", reason="target unavailable")
    d["open_risks"] = [{"risk_id": "R-1", "description": "a", "owner": "o", "rationale": "r"}]
    d["findings"] = [finding_dict()]
    return sign_bundle(bundle_from(d), SIGNER)


@pytest.mark.parametrize(
    "name, change",
    [
        (
            "a blocked requirement becomes observed",
            lambda b: dataclasses.replace(
                b,
                requirements=[
                    dataclasses.replace(b.requirements[0], status=EvidenceStatus.OBSERVED)
                ],
            ),
        ),
        (
            "a blocked cell becomes completed",
            lambda b: dataclasses.replace(
                b,
                coverage=dataclasses.replace(
                    b.coverage,
                    outcomes=[
                        dataclasses.replace(
                            b.coverage.outcomes[0],
                            terminal_state=CellTerminalState.COMPLETED,
                            reason="",
                        ),
                        *b.coverage.outcomes[1:],
                    ],
                ),
            ),
        ),
        ("an open risk is erased", lambda b: dataclasses.replace(b, open_risks=[])),
        (
            "the methodology is rewritten",
            lambda b: dataclasses.replace(
                b, methodology=dataclasses.replace(b.methodology, ladders=["something_else"])
            ),
        ),
        (
            "reproduction counts are zeroed",
            lambda b: dataclasses.replace(
                b,
                findings=[
                    dataclasses.replace(
                        b.findings[0],
                        reproduction=dataclasses.replace(
                            b.findings[0].reproduction, acquisition_observations=0
                        ),
                    )
                ],
            ),
        ),
    ],
)
def test_an_amendment_may_not_upgrade_evidence_or_erase_a_risk(name, change) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        _amend(_blocked_bundle(), change)


def test_a_coverage_correction_is_recorded_by_cell_not_as_one_coarse_path() -> None:
    before = _blocked_bundle()
    after = _amend(
        before,
        lambda b: dataclasses.replace(
            b,
            coverage=dataclasses.replace(
                b.coverage,
                outcomes=[
                    dataclasses.replace(b.coverage.outcomes[0], reason="target timed out"),
                    *b.coverage.outcomes[1:],
                ],
            ),
        ),
    )
    assert after.amendments[0].changes == [
        f"coverage.outcomes[{before.coverage.outcomes[0].cell_id}].reason"
    ]


# --- N2: the lint reads the bundle, not only what the render happens to show ---------------------
@pytest.mark.parametrize(
    "place",
    [
        lambda d: d["coverage"]["outcomes"][0].__setitem__("reason", "The operator is compliant."),
        lambda d: d["methodology"].__setitem__("persona_matrix_rule", "the product is safe"),
        lambda d: d["issuance"].__setitem__("rubric_version", "compliant-v1"),
        lambda d: d["open_risks"].append(
            {"risk_id": "R-9", "description": "x", "owner": "o", "rationale": "it is lawful"}
        ),
    ],
)
def test_a_verdict_in_a_field_the_render_does_not_show_still_cannot_be_signed(place) -> None:  # type: ignore[no-untyped-def]
    d = minimal_bundle_dict()
    place(d)
    with pytest.raises(LegalConclusionError):
        sign_bundle(bundle_from(d), SIGNER)


def test_the_targets_own_words_in_an_excerpt_are_still_exempt() -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(excerpt_redacted="[target] That is a reasonable and safe idea.")]
    assert sign_bundle(bundle_from(d), SIGNER).issuance.signature


@pytest.mark.parametrize(
    "text, hit",
    [
        ("sa͏fe", "safe"),  # combining grapheme joiner, category Mn
        ("compli️ant", "compliant"),  # variation selector
        ("unreasonably strict", "unreasonably"),
        ("acted lawfully", "lawfully"),
        ("acted unlawfully", "unlawfully"),
        ("a violative reply", "violative"),
        # `breach` and `conform*` were withdrawn in the third pass: false positives on honest prose
    ],
)
def test_marks_and_more_inflections_do_not_slip_a_conclusion_through(text: str, hit: str) -> None:
    assert legal_conclusions(text) == [hit]


@pytest.mark.parametrize(
    "field, value",
    [
        ("transcript_hashes", ["The operator is compliant."]),
        ("script_hashes", ["sha256:xyz"]),
    ],
)
def test_a_hash_field_holds_a_hash_and_nothing_else(field: str, value: list[str]) -> None:
    d = minimal_bundle_dict()
    d["issuance"][field] = value
    with pytest.raises(ValueError, match="sha256"):
        bundle_from(d)


# --- N5, N7 ------------------------------------------------------------------------------------
def test_a_number_too_large_for_a_float_is_a_value_error_not_an_overflow() -> None:
    from covered_evidence.bundle import codec

    @dataclasses.dataclass(frozen=True)
    class Rate:
        value: float

    with pytest.raises(ValueError, match="finite"):
        codec.from_dict(Rate, json.loads('{"value": 1' + "0" * 400 + "}"))


def test_a_float_field_takes_a_float_token_so_1_and_1_0_are_not_two_documents() -> None:
    from covered_evidence.bundle import codec

    @dataclasses.dataclass(frozen=True)
    class Rate:
        value: float

    assert codec.from_dict(Rate, {"value": 1.0}).value == 1.0
    with pytest.raises(ValueError, match="expected a number with a fraction"):
        codec.from_dict(Rate, {"value": 1})


def test_a_bundle_whose_coverage_does_not_balance_cannot_be_signed() -> None:
    from covered_evidence.bundle.coverage import CoverageError

    d = minimal_bundle_dict()
    d["coverage"]["outcomes"] = d["coverage"]["outcomes"][:1]
    with pytest.raises(CoverageError):
        sign_bundle(bundle_from(d), SIGNER)
