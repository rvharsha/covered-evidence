"""the PDF is printed from the deterministic HTML render by a `Printer`; the bundle's
signature covers the JSON, and the PDF's HTML carries the bundle id and signature so a reader
can tie the paper to the signed record."""

from __future__ import annotations

from pathlib import Path

from covered_evidence.bundle.pdf import Printer, render_pdf
from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle
from covered_evidence.bundle.signing import HmacSigner, sign_bundle
from tests.bundle.factories import minimal_bundle_dict


class RecordingPrinter:
    def __init__(self) -> None:
        self.printed: list[tuple[str, Path]] = []

    def print_html(self, html: str, out: Path) -> None:
        self.printed.append((html, out))
        out.write_bytes(b"%PDF-1.7 fake")


def test_pdf_is_printed_from_the_same_html_the_bundle_renders(tmp_path: Path) -> None:
    b = sign_bundle(Bundle.from_dict(minimal_bundle_dict()), HmacSigner(b"k"))
    printer: Printer = RecordingPrinter()
    out = render_pdf(b, tmp_path / "b.pdf", printer)
    assert out.read_bytes().startswith(b"%PDF")
    ((html, path),) = printer.printed  # type: ignore[attr-defined]
    assert path == out and html == render_html(b)
    assert b.bundle_id in html and str(b.issuance.signature) in html


def test_an_unsigned_bundle_is_not_printed(tmp_path: Path) -> None:
    import pytest

    b = Bundle.from_dict(minimal_bundle_dict())
    with pytest.raises(ValueError, match="signed"):
        render_pdf(b, tmp_path / "b.pdf", RecordingPrinter())


def test_chromium_printer_is_lazy_about_playwright() -> None:
    import sys

    from covered_evidence.bundle.pdf import ChromiumPrinter  # noqa: F401

    assert "playwright" not in sys.modules
