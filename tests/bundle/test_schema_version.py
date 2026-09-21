"""The signed format carries its own version. Without one, any later change to the bundle's shape
silently breaks every verifier already in the field; with one, it is a managed migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from covered_evidence.bundle.schema import SCHEMA_VERSION, Bundle, bundle_json_schema
from covered_evidence.bundle.signing import HmacSigner, sign_bundle, verify_bundle
from tests.bundle.factories import minimal_bundle_dict

ROOT = Path(__file__).resolve().parents[2]


def test_a_bundle_states_the_schema_version_it_was_written_in() -> None:
    b = Bundle.from_dict(minimal_bundle_dict())
    assert b.schema_version == SCHEMA_VERSION == "1"
    assert b.to_dict()["schema_version"] == "1"


def test_a_bundle_without_a_schema_version_is_refused_not_assumed_current() -> None:
    d = minimal_bundle_dict()
    del d["schema_version"]
    with pytest.raises(ValueError, match="schema_version"):
        Bundle.from_dict(d)


@pytest.mark.parametrize("version", ["0", "2", "1.0", ""])
def test_a_version_this_library_does_not_read_is_refused_by_name(version: str) -> None:
    d = minimal_bundle_dict()
    d["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported bundle schema version"):
        Bundle.from_dict(d)


def test_the_version_is_inside_the_signed_bytes() -> None:
    signer = HmacSigner(b"k")
    signed = sign_bundle(Bundle.from_dict(minimal_bundle_dict()), signer)
    assert verify_bundle(signed, signer)
    d = signed.to_dict()
    assert '"schema_version":"1"' in json.dumps(d, separators=(",", ":"))
    # a verifier must not be talked into reading the same bytes under another version
    object.__setattr__(signed, "schema_version", "2")
    assert not verify_bundle(signed, signer)


def test_the_json_schema_names_itself_and_pins_the_version() -> None:
    s = bundle_json_schema()
    assert s["$id"] == "urn:covered:evidence-bundle:1"
    assert s["properties"]["schema_version"] == {"const": "1"}
    assert "schema_version" in s["required"]


def test_the_checked_in_json_schema_is_exactly_what_the_code_generates() -> None:
    path = ROOT / "schemas" / "evidence-bundle-1.schema.json"
    assert json.loads(path.read_text()) == bundle_json_schema(), (
        "regenerate with: uv run python -m covered_evidence.bundle.schema > "
        "schemas/evidence-bundle-1.schema.json"
    )
