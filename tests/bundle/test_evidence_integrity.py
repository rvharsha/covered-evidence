"""ways a bundle could say one thing and verify as another. Each
test is an attack that worked before the fix."""

from __future__ import annotations

import dataclasses
import json

import pytest

from covered_evidence.bundle.amend import amend
from covered_evidence.bundle.schema import Bundle, FindingStatus, Severity
from covered_evidence.bundle.signing import HmacSigner, sign_bundle, verify_bundle
from tests.bundle.factories import finding_dict, minimal_bundle_dict

SIGNER = HmacSigner(b"k1")


def _signed(**over) -> Bundle:  # type: ignore[no-untyped-def]
    d = minimal_bundle_dict()
    d.update(over)
    return sign_bundle(Bundle.from_dict(d), SIGNER)


# --- P0-1: duplicate JSON keys -------------------------------------------------------------
def test_a_document_with_a_duplicate_key_is_refused_not_resolved_last_one_wins() -> None:
    """`json.loads` keeps the last duplicate. A reader, or a first-key-wins parser, sees the
    first. A file could show severity "low" and verify as "high"."""
    text = json.dumps(_signed(findings=[finding_dict()]).to_dict())
    doctored = text.replace('"severity": "', '"severity": "low", "severity": "', 1)
    assert doctored != text
    with pytest.raises(ValueError, match="duplicate key"):
        Bundle.from_json(doctored)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_not_json_and_are_refused(token: str) -> None:
    text = json.dumps(_signed().to_dict()).replace(
        '"review_decisions": 0', f'"review_decisions": {token}'
    )
    with pytest.raises(ValueError):
        Bundle.from_json(text)


def test_from_json_round_trips_a_signed_bundle() -> None:
    b = _signed(findings=[finding_dict()])
    again = Bundle.from_json(json.dumps(b.to_dict()))
    assert again == b and verify_bundle(again, SIGNER)


# --- P0-3: fields silently defaulted on load -----------------------------------------------
@pytest.mark.parametrize("path", [("amendments",), ("change_attribution",)])
def test_a_missing_top_level_list_is_an_error_not_an_empty_default(path: tuple[str, ...]) -> None:
    """Two different documents must not share canonical bytes: `amendments` could be stripped
    from a file and it still verified, because the loader filled the default."""
    d = _signed().to_dict()
    del d[path[0]]
    with pytest.raises(ValueError, match="missing required field"):
        Bundle.from_dict(d)


def test_a_missing_nested_field_with_a_python_default_is_an_error_on_load() -> None:
    d = _signed(findings=[finding_dict()]).to_dict()
    del d["findings"][0]["related_findings"]
    with pytest.raises(ValueError, match="related_findings"):
        Bundle.from_dict(d)


def test_the_json_schema_requires_every_field() -> None:
    from covered_evidence.bundle.schema import bundle_json_schema

    s = bundle_json_schema()
    assert set(s["required"]) == set(s["properties"])


def test_python_construction_may_still_use_defaults() -> None:
    b = _signed()
    assert b.amendments == [] and b.change_attribution == []


# --- P0-2: the key named in the signature is authenticated ---------------------------------
def test_the_signers_key_id_is_inside_the_signed_bytes() -> None:
    b = _signed()
    assert b.issuance.key_id == "hmac-sha256"
    moved = dataclasses.replace(
        b, issuance=dataclasses.replace(b.issuance, key_id="hmac-sha256:other")
    )
    assert not verify_bundle(moved, SIGNER)


def test_an_unsigned_bundle_has_no_key_id_and_a_signed_one_must() -> None:
    unsigned = Bundle.from_dict(minimal_bundle_dict())
    assert unsigned.issuance.key_id is None and unsigned.issuance.signature is None
    b = _signed()
    stripped = dataclasses.replace(b, issuance=dataclasses.replace(b.issuance, key_id=None))
    assert not verify_bundle(stripped, SIGNER)


# --- P0-4: amendments ---------------------------------------------------------------------
def _amend(bundle: Bundle, change):  # type: ignore[no-untyped-def]
    return amend(
        bundle,
        amendment_id="amd-1",
        issued_at="2026-09-17T00:00:00Z",
        description="typo fix",
        change=change,
        signer=SIGNER,
    )


def _confirmed_high() -> Bundle:
    return _signed(
        findings=[
            finding_dict(finding_id="F-BR-001", severity="high", human_confirmed=True),
            finding_dict(finding_id="F-BR-002"),
        ]
    )


@pytest.mark.parametrize(
    "name, change",
    [
        ("operator", lambda b: dataclasses.replace(b, operator="Someone Else LLC")),
        ("chatbot", lambda b: dataclasses.replace(b, chatbot="Other Bot")),
        ("remove a finding", lambda b: dataclasses.replace(b, findings=b.findings[:1])),
        ("empty the requirements", lambda b: dataclasses.replace(b, requirements=[])),
        (
            "lower a severity",
            lambda b: dataclasses.replace(
                b,
                findings=[
                    dataclasses.replace(b.findings[0], severity=Severity.LOW),
                    *b.findings[1:],
                ],
            ),
        ),
        (
            "unconfirm a finding",
            lambda b: dataclasses.replace(
                b,
                findings=[
                    dataclasses.replace(b.findings[0], human_confirmed=False),
                    *b.findings[1:],
                ],
            ),
        ),
        (
            "mark not observed without a new build",
            lambda b: dataclasses.replace(
                b,
                findings=[
                    dataclasses.replace(
                        b.findings[0], status=FindingStatus.NOT_OBSERVED_IN_VERIFICATION
                    ),
                    *b.findings[1:],
                ],
            ),
        ),
        (
            "drop planned cells",
            lambda b: dataclasses.replace(
                b,
                coverage=dataclasses.replace(
                    b.coverage,
                    planned_cells=b.coverage.planned_cells[:1],
                    outcomes=b.coverage.outcomes[:1],
                ),
            ),
        ),
        (
            "change the scope cover",
            lambda b: dataclasses.replace(
                b, cover=dataclasses.replace(b.cover, scenarios_exercised=["BR"])
            ),
        ),
    ],
)
def test_an_amendment_cannot_rewrite_what_was_found_or_who_it_was_about(name, change) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        _amend(_confirmed_high(), change)


def test_an_amendment_may_correct_a_note_and_records_what_it_superseded_and_changed() -> None:
    import hashlib

    from covered_evidence.bundle.signing import canonical_bytes

    before = _confirmed_high()
    after = _amend(
        before,
        lambda b: dataclasses.replace(
            b,
            findings=[
                dataclasses.replace(b.findings[0], review_disposition="confirmed by reviewer 2"),
                *b.findings[1:],
            ],
        ),
    )
    assert verify_bundle(after, SIGNER)
    (record,) = after.amendments
    assert record.supersedes_sha256 == hashlib.sha256(canonical_bytes(before)).hexdigest()
    assert record.changes == ["findings[F-BR-001].review_disposition"]


def test_an_amendment_may_raise_a_severity_or_confirm_a_finding() -> None:
    before = _signed(findings=[finding_dict(finding_id="F-1", severity="medium")])
    after = _amend(
        before,
        lambda b: dataclasses.replace(
            b,
            findings=[
                dataclasses.replace(b.findings[0], severity=Severity.HIGH, human_confirmed=True)
            ],
        ),
    )
    assert after.findings[0].severity is Severity.HIGH and verify_bundle(after, SIGNER)


# --- P1-5: the lint is enforced by the library, not only by its callers -------------------
def test_a_bundle_that_states_a_legal_conclusion_cannot_be_signed() -> None:
    from covered_evidence.bundle.lint import LegalConclusionError

    d = minimal_bundle_dict()
    d["requirements"][0]["note"] = "The operator is compliant."
    with pytest.raises(LegalConclusionError, match="compliant"):
        sign_bundle(Bundle.from_dict(d), SIGNER)
