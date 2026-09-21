"""``covered-verify``: check an evidence bundle's signature, offline.

An auditor, opposing counsel, or an operator's own engineer needs only the bundle JSON and the
issuer's public key (a PEM). Nothing here contacts a network, a cloud service, or the issuer.

Exit status is a contract a script can act on: 0 the signature verifies, 1 the check ran and
the signature does not verify, 3 the check could not run. See ``covered_evidence.bundle.verify``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from covered_evidence.bundle.verify import verify_file


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="covered-verify", description="Verify an evidence bundle's signature, offline."
    )
    p.add_argument("bundle", type=Path, help="path to the bundle JSON")
    p.add_argument("--public-key", type=Path, default=None, help="issuer's public key, PEM")
    p.add_argument(
        "--key-version",
        default=None,
        help="require this key version name; it is inside the signed bytes, so it is authenticated",
    )
    p.add_argument(
        "--hmac-key-env",
        default=None,
        help="environment variable holding a shared HMAC key (demos and tests only)",
    )
    args = p.parse_args(argv)
    return verify_file(
        args.bundle,
        public_key=args.public_key,
        hmac_key_env=args.hmac_key_env,
        key_version=args.key_version,
    )


if __name__ == "__main__":
    sys.exit(main())
