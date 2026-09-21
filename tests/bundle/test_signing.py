"""the issuance snapshot is signed; a modified bundle fails verification."""

from __future__ import annotations

from covered_evidence.bundle.schema import Bundle
from covered_evidence.bundle.signing import HmacSigner, sign_bundle, verify_bundle
from tests.bundle.factories import finding_dict, minimal_bundle_dict


def test_signed_bundle_verifies() -> None:
    signer = HmacSigner(key=b"test-key")
    b = sign_bundle(Bundle.from_dict(minimal_bundle_dict()), signer)
    assert b.issuance.signature is not None
    assert verify_bundle(b, signer) is True


def test_any_modification_after_signing_fails_verification() -> None:
    signer = HmacSigner(key=b"test-key")
    b = sign_bundle(Bundle.from_dict(minimal_bundle_dict()), signer)
    d = b.to_dict()
    d["findings"] = [finding_dict()]
    assert verify_bundle(Bundle.from_dict(d), signer) is False


def test_a_different_key_fails_verification() -> None:
    b = sign_bundle(Bundle.from_dict(minimal_bundle_dict()), HmacSigner(key=b"k1"))
    assert verify_bundle(b, HmacSigner(key=b"k2")) is False


def test_signature_is_over_canonical_json_so_key_order_does_not_matter() -> None:
    signer = HmacSigner(key=b"k")
    b = sign_bundle(Bundle.from_dict(minimal_bundle_dict()), signer)
    reordered = dict(reversed(list(b.to_dict().items())))
    assert verify_bundle(Bundle.from_dict(reordered), signer) is True


def test_unsigned_bundle_does_not_verify() -> None:
    assert verify_bundle(Bundle.from_dict(minimal_bundle_dict()), HmacSigner(key=b"k")) is False
