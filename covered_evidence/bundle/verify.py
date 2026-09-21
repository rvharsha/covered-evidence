"""Verify a bundle file, offline. One implementation, shared by every command-line front end.

Exit status is a contract a script can act on:
  0  the signature verifies, for the key named inside the signed bytes
  1  the check ran and the signature does not verify
  3  the check could not run (missing key, unreadable or malformed bundle, bad arguments)
A condition that stops the check from running is never reported as 1.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import TextIO

from covered_evidence.bundle.schema import Bundle
from covered_evidence.bundle.signing import (
    KMS_PREFIX,
    HmacSigner,
    PublicKeyVerifier,
    Signer,
    canonical_bytes,
    verify_bundle,
)

VERIFIED, NOT_VERIFIED, COULD_NOT_RUN = 0, 1, 3


def verify_file(
    bundle_path: Path,
    *,
    public_key: Path | None = None,
    hmac_key_env: str | None = None,
    key_version: str | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    try:
        signer: Signer
        if public_key is not None:
            signer = PublicKeyVerifier(public_key.read_text())
        elif hmac_key_env is not None:
            key = os.environ.get(hmac_key_env)
            if not key:
                print(f"environment variable {hmac_key_env} is not set", file=err)
                return COULD_NOT_RUN
            signer = HmacSigner(key.encode())
        else:
            print("give --public-key PEM or --hmac-key-env NAME", file=err)
            return COULD_NOT_RUN
        bundle = Bundle.from_json(bundle_path.read_text())
        payload = canonical_bytes(bundle)
    except (OSError, ValueError, KeyError, TypeError, RecursionError, ArithmeticError) as e:
        print(f"cannot verify {bundle_path}: {type(e).__name__}: {e}", file=err)
        return COULD_NOT_RUN
    expected = None if key_version is None else f"{KMS_PREFIX}:{key_version}"
    try:
        ok = verify_bundle(bundle, signer) and (
            expected is None or bundle.issuance.key_id == expected
        )
    except (ValueError, TypeError, UnicodeError):
        ok = False  # a malformed signature value is a signature that does not verify
    if not ok:
        print(f"{bundle.bundle_id}: signature does NOT verify", file=err)
        return NOT_VERIFIED
    # Only authenticated facts are printed: the key id and the hash are inside or derived from
    # the signed bytes. The signature string itself is not echoed as if it proved something.
    print(f"{bundle.bundle_id}: signature verifies", file=out)
    print(f"  key: {bundle.issuance.key_id}", file=out)
    print(f"  sha256 of signed bytes: {hashlib.sha256(payload).hexdigest()}", file=out)
    return VERIFIED
