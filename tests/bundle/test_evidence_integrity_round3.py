"""Third pass of the"""

from __future__ import annotations

import dataclasses
import json

import pytest

from covered_evidence.bundle.amend import amend
from covered_evidence.bundle.schema import Bundle, CalibrationRecord, IssuancePath
from covered_evidence.bundle.signing import HmacSigner, sign_bundle, verify_bundle
from tests.bundle.factories import bundle_from, finding_dict, minimal_bundle_dict

SIGNER = HmacSigner(b"k1")


def _amend(bundle: Bundle, change):  # type: ignore[no-untyped-def]
    return amend(
        bundle, amendment_id="amd-1", issued_at="t", description="d", change=change, signer=SIGNER
    )


def _calibration(**over):  # type: ignore[no-untyped-def]
    base = dict(
        category="SN",
        positives=10,
        negatives=10,
        precision=0.9,
        recall=0.8,
        precision_ci_low=0.7,
        precision_ci_high=0.95,
        recall_ci_low=0.6,
        recall_ci_high=0.9,
        meets_gate=True,
        issuance_path=IssuancePath.JUDGE_MET_GATE,
        judge_model="family-b/judge-1",
        rubric_version="rubric-v1",
    )
    base.update(over)
    return CalibrationRecord(**base)  # type: ignore[arg-type]


# --- V1: what an issuer signs, an auditor can read -----------------------------------------------
def test_a_rate_given_as_an_integer_in_python_is_stored_as_a_float() -> None:
    c = _calibration(precision=1, recall=0)
    assert isinstance(c.precision, float) and isinstance(c.recall, float)
    assert json.dumps(c.to_dict()["precision"]) == "1.0"


def test_every_bundle_sign_bundle_returns_loads_back_from_its_own_json() -> None:
    b = Bundle.from_dict(minimal_bundle_dict())
    b = dataclasses.replace(
        b, methodology=dataclasses.replace(b.methodology, calibration=[_calibration(precision=1)])
    )
    signed = sign_bundle(b, SIGNER)
    again = Bundle.from_json(json.dumps(signed.to_dict()))
    assert again == signed and verify_bundle(again, SIGNER)


def test_sign_bundle_refuses_a_bundle_that_would_not_load_back() -> None:
    """The guarantee is structural, not a list of known cases: whatever slips past construction
    and would be refused on load is refused at signing, where the issuer can still fix it."""
    b = Bundle.from_dict(minimal_bundle_dict())
    bad = dataclasses.replace(b.issuance, review_decisions=True)  # a bool where an int belongs
    with pytest.raises(ValueError, match="would not load"):
        sign_bundle(dataclasses.replace(b, issuance=bad), SIGNER)


# --- V2: an identifier that looks the same is the same -------------------------------------------
@pytest.mark.parametrize(
    "lookalike",
    [
        "f-br-001",  # case
        "F-BR-001 ",  # trailing space
        "Ｆ-BR-001",  # fullwidth F
        "F​-BR-001",  # zero-width space
        "F-ВR-001",  # Cyrillic Ve for B
        "F-BR-001́",  # combining mark
        "F‐BR-001",  # Unicode hyphen U+2010
        "F−BR-001",  # minus sign U+2212
        "F-BR-001⠀",  # braille blank U+2800
        "А-01",  # all Cyrillic: one script, and still the twin of a Latin "A-01"
    ],
)
def test_an_id_that_a_reader_cannot_tell_from_another_is_refused(lookalike: str) -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(), finding_dict(finding_id=lookalike, severity="low")]
    with pytest.raises(ValueError, match="identifier|duplicate"):
        bundle_from(d)


def test_ordinary_identifiers_including_statute_citations_are_accepted() -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(finding_id="F-BR-001"), finding_dict(finding_id="F-BR-Od7c1b8c6")]
    d["requirements"].append(
        {"citation": "§21812(d)(5)(A)(i)(II)", "status": "observed", "note": ""}
    )
    assert len(bundle_from(d).findings) == 2


def test_an_amendment_appends_findings_and_never_reorders_or_inserts_ahead() -> None:
    before = sign_bundle(
        bundle_from(
            {
                **minimal_bundle_dict(),
                "findings": [finding_dict(finding_id="F-1"), finding_dict(finding_id="F-2")],
            }
        ),
        SIGNER,
    )
    new = dataclasses.replace(before.findings[0], finding_id="F-0")
    with pytest.raises(ValueError, match="order"):
        _amend(before, lambda b: dataclasses.replace(b, findings=[new, *b.findings]))
    with pytest.raises(ValueError, match="order"):
        _amend(before, lambda b: dataclasses.replace(b, findings=b.findings[::-1]))
    after = _amend(before, lambda b: dataclasses.replace(b, findings=[*b.findings, new]))
    assert [f.finding_id for f in after.findings] == ["F-1", "F-2", "F-0"]


# --- V3: references resolve -----------------------------------------------------------------
@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["findings"][0].__setitem__("related_findings", ["F-GHOST"]),
        lambda d: d["change_attribution"].append(
            {"finding_id": "F-GHOST", "cause": "target_behavior", "note": ""}
        ),
    ],
)
def test_a_reference_to_a_finding_that_is_not_in_the_bundle_is_refused(mutate) -> None:  # type: ignore[no-untyped-def]
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict()]
    mutate(d)
    with pytest.raises(ValueError, match="F-GHOST"):
        bundle_from(d)


# --- V4, V5 ------------------------------------------------------------------------------------
def test_an_amendment_that_changes_nothing_is_refused() -> None:
    before = sign_bundle(Bundle.from_dict(minimal_bundle_dict()), SIGNER)
    with pytest.raises(ValueError, match="changes nothing"):
        _amend(before, lambda b: b)


def test_an_excerpt_is_a_quotation_not_a_place_to_write_at_length() -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(excerpt_redacted="[target] " + "x" * 20000)]
    with pytest.raises(ValueError, match="excerpt"):
        bundle_from(d)
