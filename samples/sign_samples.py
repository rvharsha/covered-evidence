"""Sign the sample bundles with a throwaway key, and write a tampered copy that must not verify.

    uv run python samples/sign_samples.py

A fresh ECDSA P-256 key is generated on every run and only its PUBLIC half is written; the
private key is never stored. So the signed samples prove the verifier works, and nobody, the
authors included, can sign anything else as "the sample issuer".
"""

from __future__ import annotations

import base64
import dataclasses
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle, Severity
from covered_evidence.bundle.signing import KMS_PREFIX, low_s, sign_bundle

HERE = Path(__file__).resolve().parent / "fernwood-pip"
KEY_VERSION = "samples/fernwood-pip/test-key/cryptoKeyVersions/1"


class ThrowawaySigner:
    #: goes inside the signed bytes, so the key a signature names is authenticated
    key_id = f"{KMS_PREFIX}:{KEY_VERSION}"

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())

    def sign(self, payload: bytes) -> str:
        # verifiers accept only the low-S twin of an ECDSA signature
        der = low_s(self._key.sign(payload, ec.ECDSA(hashes.SHA256())))
        return f"{KMS_PREFIX}:{KEY_VERSION}:{base64.b64encode(der).decode()}"

    def verify(self, payload: bytes, signature: str) -> bool:
        raise NotImplementedError("verify with the written public key")

    def public_pem(self) -> str:
        return (
            self._key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )


def _write(path: Path, bundle: Bundle) -> None:
    path.write_text(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    signer = ThrowawaySigner()
    (HERE / "test-public-key.pem").write_text(signer.public_pem())
    signed = {}
    for name in ("build-1", "build-2"):
        bundle = Bundle.from_json((HERE / f"{name}.json").read_text())
        signed[name] = sign_bundle(bundle, signer)
        _write(HERE / f"{name}.signed.json", signed[name])
        (HERE / f"{name}.signed.html").write_text(render_html(signed[name]))
    # the tampered copy keeps build-1's valid signature but quietly downgrades one finding
    b = signed["build-1"]
    first, *rest = b.findings
    lower = Severity.LOW if first.severity is not Severity.LOW else Severity.MEDIUM
    _write(
        HERE / "build-1.tampered.json",
        dataclasses.replace(b, findings=[dataclasses.replace(first, severity=lower), *rest]),
    )
    print(f"signed {len(signed)} sample(s); wrote test-public-key.pem and build-1.tampered.json")


if __name__ == "__main__":
    main()
