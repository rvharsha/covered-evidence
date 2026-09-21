"""Issuance signature over the canonical bundle (principle 10).

Two schemes, distinguishable by prefix and never cross-verifying:

- ``hmac-sha256:<hex>`` from ``HmacSigner`` (local development, the demo);
- ``kms-ec-p256-sha256:<key version resource name>:<base64 DER signature>``
  from ``an issuer's key-management service``, which an auditor verifies offline with
  ``PublicKeyVerifier`` and the key version's public key.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import hmac
import json
from typing import Protocol

from covered_evidence.bundle.schema import Bundle

HMAC_PREFIX = "hmac-sha256"
KMS_PREFIX = "kms-ec-p256-sha256"


#: Order of the P-256 group. ECDSA signatures are malleable: (r, s) and (r, n - s) both verify.
#: Only the low-S form is accepted, so a signature string identifies one signature.
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


class Signer(Protocol):
    def sign(self, payload: bytes) -> str: ...

    def verify(self, payload: bytes, signature: str) -> bool: ...


def key_id_of(signature: str) -> str:
    """The signer identity a signature string claims: everything before the signature value.
    ``hmac-sha256`` or ``kms-ec-p256-sha256:<key version name>``. It is a CLAIM until it is
    compared with ``issuance.key_id``, which is inside the signed bytes."""
    return signature.rpartition(":")[0]


class HmacSigner:
    key_id = HMAC_PREFIX

    def __init__(self, key: bytes) -> None:
        self._key = key

    def sign(self, payload: bytes) -> str:
        return f"{HMAC_PREFIX}:" + hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload).encode(), signature.encode())


def split_kms_signature(signature: str) -> tuple[str, bytes] | None:
    """(key version name, DER signature) for a KMS signature string, else None."""
    prefix, sep, rest = signature.partition(":")
    if not sep or prefix != KMS_PREFIX:
        return None
    key_version, sep, encoded = rest.rpartition(":")
    if not sep or not key_version or not encoded:
        return None
    try:
        return key_version, base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


class PublicKeyVerifier:
    """Verifies KMS signatures with a PEM public key and nothing else; it cannot sign."""

    def __init__(self, pem: str, *, key_version: str | None = None) -> None:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        self._key = load_pem_public_key(pem.encode())
        self._key_version = key_version

    def sign(self, payload: bytes) -> str:
        raise NotImplementedError("a public key verifies; it does not sign")

    def verify(self, payload: bytes, signature: str) -> bool:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        parts = split_kms_signature(signature)
        if parts is None:
            return False
        key_version, der = parts
        if self._key_version is not None and key_version != self._key_version:
            return False
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

        if not isinstance(self._key, ec.EllipticCurvePublicKey):
            return False
        if not isinstance(self._key.curve, ec.SECP256R1):
            return False  # the scheme says P-256; a key on another curve is not this scheme
        try:
            _, s_value = decode_dss_signature(der)
        except ValueError:
            return False
        if s_value > _P256_ORDER // 2:
            return False  # high-S twin of a valid signature; see _P256_ORDER
        try:
            self._key.verify(der, payload, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            return False
        return True


def canonical_bytes(bundle: Bundle) -> bytes:
    d = bundle.to_dict()
    d["issuance"]["signature"] = None
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def low_s(der: bytes) -> bytes:
    """The low-S form of a DER ECDSA P-256 signature. Signers normalise with this; a key service
    may return either twin."""
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature,
        encode_dss_signature,
    )

    r_value, s_value = decode_dss_signature(der)
    if s_value > _P256_ORDER // 2:
        s_value = _P256_ORDER - s_value
    return encode_dss_signature(r_value, s_value)


def sign_bundle(bundle: Bundle, signer: Signer) -> Bundle:
    """Sign a bundle. The signer's key id goes INSIDE the signed bytes first, and a bundle that
    states a legal conclusion is refused (principle 7): the lint is part of issuing, not a courtesy
    of whoever calls this."""
    from covered_evidence.bundle.coverage import check_coverage
    from covered_evidence.bundle.lint import (
        LegalConclusionError,
        legal_conclusions,
        legal_conclusions_in,
    )
    from covered_evidence.bundle.render import render_html

    key_id = getattr(signer, "key_id", None)
    if not isinstance(key_id, str) or not key_id:
        raise ValueError("a signer must state its key_id; it is part of the signed bytes")
    named = dataclasses.replace(
        bundle, issuance=dataclasses.replace(bundle.issuance, key_id=key_id, signature=None)
    )
    check_coverage(named.coverage)  # every planned cell in exactly one terminal state (principle 5)
    # every string in the bundle, and the render's own fixed prose around them
    hits = legal_conclusions_in(named.to_dict()) + legal_conclusions(render_html(named))
    if hits:
        raise LegalConclusionError(f"bundle states legal-conclusion terms: {hits}")
    # What an issuer signs, an auditor must be able to read. Python construction is looser than
    # loading (an int where a float belongs, a bool where an int belongs), so prove it here,
    # where the issuer can still fix it, rather than at every auditor's desk.
    try:
        reloaded = Bundle.from_json(json.dumps(named.to_dict()))
    except ValueError as e:
        raise ValueError(f"this bundle would not load back from its own JSON: {e}") from None
    if reloaded != named:
        raise ValueError("this bundle would not load back from its own JSON unchanged")
    sig = signer.sign(canonical_bytes(named))
    if key_id_of(sig) != key_id:
        raise ValueError(f"signer produced a signature for {key_id_of(sig)!r}, not {key_id!r}")
    return dataclasses.replace(named, issuance=dataclasses.replace(named.issuance, signature=sig))


def verify_bundle(bundle: Bundle, signer: Signer) -> bool:
    signature = bundle.issuance.signature
    if signature is None or bundle.issuance.key_id is None:
        return False
    if key_id_of(signature) != bundle.issuance.key_id:
        return False  # the key named next to the signature is not the key that was signed for
    return signer.verify(canonical_bytes(bundle), signature)
