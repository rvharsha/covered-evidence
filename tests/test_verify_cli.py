"""`covered-verify`: what an auditor runs. It needs the bundle and a public key, nothing else."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from covered_evidence.bundle.schema import Bundle
from covered_evidence.bundle.signing import HmacSigner, sign_bundle
from covered_evidence.verify_cli import main

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "fernwood-pip"
PEM = SAMPLES / "test-public-key.pem"


@pytest.mark.parametrize("name", ["build-1.signed.json", "build-2.signed.json"])
def test_the_signed_samples_verify_with_the_published_public_key(name: str, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([str(SAMPLES / name), "--public-key", str(PEM)]) == 0
    out = capsys.readouterr().out
    assert "signature verifies" in out
    assert "key: kms-ec-p256-sha256:samples/fernwood-pip/test-key/" in out
    assert "sha256 of signed bytes: " in out


def test_a_bundle_changed_after_signing_does_not_verify(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([str(SAMPLES / "build-1.tampered.json"), "--public-key", str(PEM)]) == 1
    assert "does NOT verify" in capsys.readouterr().err


def test_the_tampered_sample_differs_from_the_signed_one_only_in_a_findings_severity() -> None:
    good = json.loads((SAMPLES / "build-1.signed.json").read_text())
    bad = json.loads((SAMPLES / "build-1.tampered.json").read_text())
    assert good["issuance"]["signature"] == bad["issuance"]["signature"]
    assert good["findings"][0]["severity"] != bad["findings"][0]["severity"]
    good["findings"][0]["severity"] = bad["findings"][0]["severity"]
    assert good == bad


def test_an_unsigned_bundle_never_verifies() -> None:
    assert main([str(SAMPLES / "build-1.json"), "--public-key", str(PEM)]) == 1


def test_the_wrong_public_key_does_not_verify(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    other = ec.generate_private_key(ec.SECP256R1()).public_key()
    pem = tmp_path / "other.pem"
    pem.write_bytes(
        other.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    assert main([str(SAMPLES / "build-1.signed.json"), "--public-key", str(pem)]) == 1


def test_an_hmac_bundle_verifies_with_the_shared_key_from_the_environment(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    bundle = Bundle.from_json((SAMPLES / "build-1.json").read_text())
    path = tmp_path / "b.json"
    path.write_text(json.dumps(sign_bundle(bundle, HmacSigner(b"k1")).to_dict()))
    monkeypatch.setenv("DEMO_KEY", "k1")
    assert main([str(path), "--hmac-key-env", "DEMO_KEY"]) == 0
    monkeypatch.setenv("DEMO_KEY", "k2")
    assert main([str(path), "--hmac-key-env", "DEMO_KEY"]) == 1


def test_it_says_what_is_missing_rather_than_guessing(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([str(SAMPLES / "build-1.signed.json")]) == 3
    assert "--public-key" in capsys.readouterr().err
    junk = tmp_path / "junk.json"
    junk.write_text('{"not": "a bundle"}')
    assert main([str(junk), "--public-key", str(PEM)]) == 3


def test_an_unknown_field_is_an_error_not_a_default() -> None:
    d = json.loads((SAMPLES / "build-1.json").read_text())
    d["surprise"] = 1
    with pytest.raises((ValueError, KeyError, TypeError)):
        Bundle.from_dict(d)


def test_a_file_that_shows_one_value_and_carries_another_is_refused(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """json.loads keeps the LAST duplicate key while a reader sees the first."""
    text = (SAMPLES / "build-1.signed.json").read_text()
    doctored = tmp_path / "doctored.json"
    doctored.write_text(
        text.replace('"operator": "', '"operator": "Shown To The Reader", "operator": "', 1)
    )
    assert main([str(doctored), "--public-key", str(PEM)]) == 3
    assert "duplicate key" in capsys.readouterr().err


def test_another_issuers_key_name_swapped_into_the_signature_does_not_verify(
    tmp_path: Path,
) -> None:
    d = json.loads((SAMPLES / "build-1.signed.json").read_text())
    d["issuance"]["signature"] = d["issuance"]["signature"].replace(
        "samples/fernwood-pip", "projects/evil-issuer"
    )
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(d))
    assert main([str(forged), "--public-key", str(PEM)]) == 1


def test_a_stripped_field_is_an_unreadable_bundle_not_a_verified_one(tmp_path: Path) -> None:
    d = json.loads((SAMPLES / "build-1.signed.json").read_text())
    del d["amendments"]
    stripped = tmp_path / "stripped.json"
    stripped.write_text(json.dumps(d))
    assert main([str(stripped), "--public-key", str(PEM)]) == 3


def test_the_expected_key_version_can_be_required() -> None:
    sample = str(SAMPLES / "build-1.signed.json")
    good = "samples/fernwood-pip/test-key/cryptoKeyVersions/1"
    assert main([sample, "--public-key", str(PEM), "--key-version", good]) == 0
    assert main([sample, "--public-key", str(PEM), "--key-version", good[:-1] + "2"]) == 1


def test_a_missing_or_malformed_key_file_is_could_not_run_never_not_verified(
    tmp_path: Path,
) -> None:
    sample = str(SAMPLES / "build-1.signed.json")
    assert main([sample, "--public-key", str(tmp_path / "nope.pem")]) == 3
    bad = tmp_path / "bad.pem"
    bad.write_text("not a pem")
    assert main([sample, "--public-key", str(bad)]) == 3
