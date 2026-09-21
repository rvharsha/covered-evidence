"""PDF rendering.

The PDF is a print of the deterministic HTML render, produced by a ``Printer``.
The signature covers the bundle JSON, not the PDF; the render already carries
the bundle id and signature so a reader can tie the paper to the signed record.
``ChromiumPrinter`` uses Playwright's bundled Chromium and imports it lazily; it
is exercised in the issuance job, not in the unit suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle


class Printer(Protocol):
    def print_html(self, html: str, out: Path) -> None: ...


def render_pdf(bundle: Bundle, out: Path, printer: Printer) -> Path:
    if bundle.issuance.signature is None:
        raise ValueError("only a signed bundle is printed; sign it first")
    out.parent.mkdir(parents=True, exist_ok=True)
    printer.print_html(render_html(bundle), out)
    return out


class ChromiumPrinter:
    """Print through headless Chromium. Requires the ``pdf`` extra (Playwright)."""

    def __init__(self, *, executable_path: str | None = None) -> None:
        self._executable_path = executable_path

    def print_html(self, html: str, out: Path) -> None:
        from playwright.sync_api import sync_playwright  # deliberate lazy import

        with sync_playwright() as p:
            browser = (
                p.chromium.launch(executable_path=self._executable_path)
                if self._executable_path
                else p.chromium.launch()
            )
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                page.pdf(path=str(out), format="A4", print_background=True)
            finally:
                browser.close()
