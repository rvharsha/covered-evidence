"""The issuer's side, end to end: load two authored bundles, sign, verify, render, diff, amend.

    uv run python examples/workflow.py out/

The input is the pair of hand-authored documents in samples/fernwood-pip/ (a fictional operator;
`author.py` there shows how such a document is written). An exporter from your own testing tool
would produce the same JSON. The signer below holds a local P-256 key for the demonstration; a
real issuer signs with a key it controls (a KMS or HSM) and publishes the public half out of
band. Whether a reader has the RIGHT public key is outside what any file here can prove.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from covered_evidence.bundle.amend import amend
from covered_evidence.bundle.diff import attribute_changes, diff_bundles
from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle
from covered_evidence.bundle.signing import (
    KMS_PREFIX,
    PublicKeyVerifier,
    low_s,
    sign_bundle,
    verify_bundle,
)

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "fernwood-pip"
KEY_NAME = "examples/local-key/cryptoKeyVersions/1"


class LocalKeySigner:
    """Signs with a P-256 key held in memory. `key_id` goes inside the signed bytes."""

    key_id = f"{KMS_PREFIX}:{KEY_NAME}"

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())

    def sign(self, payload: bytes) -> str:
        der = low_s(self._key.sign(payload, ec.ECDSA(hashes.SHA256())))  # low-S only
        return f"{self.key_id}:{base64.b64encode(der).decode()}"

    def verify(self, payload: bytes, signature: str) -> bool:
        return PublicKeyVerifier(self.public_pem()).verify(payload, signature)

    def public_pem(self) -> str:
        public = self._key.public_key()
        return public.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()


def _write(path: Path, bundle: Bundle) -> None:
    path.write_text(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False) + "\n")


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    signer = LocalKeySigner()
    (out / "issuer-public-key.pem").write_text(signer.public_pem())

    # 1. load strictly and sign; signing also checks coverage accounting and the word lint
    build_1 = sign_bundle(Bundle.from_json((SAMPLES / "build-1.json").read_text()), signer)
    build_2 = sign_bundle(Bundle.from_json((SAMPLES / "build-2.json").read_text()), signer)
    for name, bundle in (("build-1", build_1), ("build-2", build_2)):
        _write(out / f"{name}.signed.json", bundle)
        (out / f"{name}.html").write_text(render_html(bundle))

    # 2. what a recipient does, with nothing but the file and the public key
    received = Bundle.from_json((out / "build-2.signed.json").read_text())
    assert verify_bundle(received, PublicKeyVerifier((out / "issuer-public-key.pem").read_text()))

    # 3. compare the builds: what changed, and whether the instrument changed with it
    diff = diff_bundles(build_1, build_2)
    rescored = None  # retained baseline evidence, re-graded, when diff.measurement_changed
    causes = {} if diff.measurement_changed else attribute_changes(diff, rescored_previous=rescored)
    print(f"{diff.previous_build} -> {diff.current_build}")
    for change in diff.status_changes:
        cause = causes.get(change.finding_id)
        print(
            f"  {change.finding_id}: {change.before.value} -> {change.after.value}"
            f" ({cause.value if cause else 'needs rescored baseline'})"
        )
    print(f"  verification incomplete for: {diff.incomplete_verification or 'none'}")

    # 4. correct the record: an amendment is a new signed bundle that names what it superseded
    first = build_1.findings[0]
    corrected = dataclasses.replace(first, excerpt_redacted=first.excerpt_redacted + " [sic]")
    amended = amend(
        build_1,
        amendment_id="AMD-0001",
        issued_at="2026-09-21T00:00:00Z",
        description="Mark the quoted reply as verbatim.",
        change=lambda b: dataclasses.replace(b, findings=[corrected, *b.findings[1:]]),
        signer=signer,
    )
    _write(out / "build-1.amended.json", amended)
    (out / "build-1.amended.html").write_text(render_html(amended))
    print(f"amendment changed: {amended.amendments[-1].changes}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "out"))
