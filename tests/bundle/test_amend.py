"""Issued bundles are immutable; corrections are explicit, signed amendments (principle 10)."""

from __future__ import annotations

import dataclasses

import pytest

from covered_evidence.bundle.amend import amend
from covered_evidence.bundle.schema import Bundle, OpenRisk
from covered_evidence.bundle.signing import HmacSigner, sign_bundle, verify_bundle
from tests.bundle.factories import minimal_bundle_dict

SIGNER = HmacSigner(key=b"k")


def _issued() -> Bundle:
    return sign_bundle(Bundle.from_dict(minimal_bundle_dict()), SIGNER)


def _add_risk(b: Bundle) -> Bundle:
    risk = OpenRisk("R-9", "late-reported staging gap", "operator", "found after issuance")
    return dataclasses.replace(b, open_risks=[*b.open_risks, risk])


def test_amendment_produces_a_new_signed_bundle_and_leaves_the_original_valid() -> None:
    original = _issued()
    amended = amend(
        original,
        amendment_id="A-1",
        issued_at="2026-09-23T10:00:00Z",
        description="add R-9",
        change=_add_risk,
        signer=SIGNER,
    )
    assert verify_bundle(original, SIGNER) and verify_bundle(amended, SIGNER)
    assert amended.issuance.signature != original.issuance.signature
    assert [a.amendment_id for a in amended.amendments] == ["A-1"]
    assert original.amendments == [] and original.open_risks == []


def test_amendment_records_the_hash_of_what_it_superseded_and_what_changed() -> None:
    original = _issued()
    amended = amend(
        original,
        amendment_id="A-1",
        issued_at="t",
        description="d",
        change=_add_risk,
        signer=SIGNER,
    )
    # ECDSA signature strings are malleable, so the link is the hash of what was superseded
    import hashlib

    from covered_evidence.bundle.signing import canonical_bytes

    assert (
        amended.amendments[0].supersedes_sha256
        == hashlib.sha256(canonical_bytes(original)).hexdigest()
    )
    assert amended.amendments[0].changes == [
        "open_risks[R-9].description",
        "open_risks[R-9].owner",
        "open_risks[R-9].rationale",
        "open_risks[R-9].risk_id",
    ]


def test_amending_an_unsigned_bundle_is_refused() -> None:
    with pytest.raises(ValueError, match="unsigned"):
        amend(
            Bundle.from_dict(minimal_bundle_dict()),
            amendment_id="A-1",
            issued_at="t",
            description="d",
            change=_add_risk,
            signer=SIGNER,
        )


def test_amendment_ids_must_be_unique() -> None:
    first = amend(
        _issued(),
        amendment_id="A-1",
        issued_at="t",
        description="d",
        change=_add_risk,
        signer=SIGNER,
    )
    with pytest.raises(ValueError, match="A-1"):
        amend(
            first,
            amendment_id="A-1",
            issued_at="t",
            description="d",
            change=_add_risk,
            signer=SIGNER,
        )


def test_an_amendment_may_not_change_the_bundle_id_or_build() -> None:
    def rebrand(b: Bundle) -> Bundle:
        return dataclasses.replace(b, bundle_id="other")

    with pytest.raises(ValueError, match="bundle_id"):
        amend(
            _issued(),
            amendment_id="A-1",
            issued_at="t",
            description="d",
            change=rebrand,
            signer=SIGNER,
        )


def test_a_bundle_whose_signature_no_longer_verifies_cannot_be_amended() -> None:
    tampered = dataclasses.replace(_issued(), operator="someone else")
    with pytest.raises(ValueError, match="does not verify"):
        amend(
            tampered,
            amendment_id="A-1",
            issued_at="t",
            description="d",
            change=lambda b: b,
            signer=SIGNER,
        )


def test_an_amendment_may_not_drop_earlier_amendments() -> None:
    first = amend(
        _issued(),
        amendment_id="A-1",
        issued_at="t",
        description="d",
        change=_add_risk,
        signer=SIGNER,
    )

    def erase(b: Bundle) -> Bundle:
        return dataclasses.replace(b, amendments=[])

    with pytest.raises(ValueError, match="amendments"):
        amend(
            first, amendment_id="A-2", issued_at="t", description="d", change=erase, signer=SIGNER
        )


def test_an_amendment_may_not_change_the_issuance_pins() -> None:
    def repin(b: Bundle) -> Bundle:
        return dataclasses.replace(
            b, issuance=dataclasses.replace(b.issuance, rubric_version="rubric-v9")
        )

    with pytest.raises(ValueError, match="issuance"):
        amend(
            _issued(),
            amendment_id="A-1",
            issued_at="t",
            description="d",
            change=repin,
            signer=SIGNER,
        )
