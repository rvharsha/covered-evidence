"""deterministic HTML render with the scope cover first."""

from __future__ import annotations

from covered_evidence.bundle.lint import legal_conclusions
from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle
from tests.bundle.factories import clean_verification, finding_dict, minimal_bundle_dict


def _bundle() -> Bundle:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict()]
    return Bundle.from_dict(d)


def test_render_is_byte_identical_across_calls() -> None:
    b = _bundle()
    assert render_html(b) == render_html(b)


def test_scope_cover_precedes_findings_in_the_document() -> None:
    html = render_html(_bundle())
    assert html.index('id="cover"') < html.index('id="findings"')


def test_unsigned_bundle_is_labelled_unsigned() -> None:
    assert "UNSIGNED" in render_html(_bundle())


def test_render_escapes_html_in_excerpts() -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(excerpt_redacted="<script>x</script>")]
    html = render_html(Bundle.from_dict(d))
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_rendered_output_contains_no_legal_conclusion_terms() -> None:
    assert legal_conclusions(render_html(_bundle())) == []


def _attributed_and_signed() -> Bundle:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(status="not_observed_in_verification")]
    d["verification"] = clean_verification()
    d["change_attribution"] = [
        {
            "finding_id": "F-BR-001",
            "cause": "measurement",
            "note": "rubric <v2> changed; prior evidence rescored",
        }
    ]
    d["issuance"]["signature"] = "hmac-sha256:" + "ab" * 32
    return Bundle.from_dict(d)


def test_change_attribution_is_rendered_with_its_finding_cause_and_note() -> None:
    """Rule 10: the page must say whether a change came from the target or the measurement."""
    html = render_html(_attributed_and_signed())
    section = html[html.index('id="change-attribution"') :]
    row = section[: section.index("</tr>", section.index("<tbody>"))]
    assert "F-BR-001" in row and "measurement" in row
    assert "rubric &lt;v2&gt; changed; prior evidence rescored" in row


def test_a_bundle_without_change_attribution_has_no_such_section() -> None:
    assert 'id="change-attribution"' not in render_html(_bundle())


def test_the_signature_line_says_this_page_does_not_check_the_signature() -> None:
    """A bare "Signature ..." read as if the render had verified it; any string got that line."""
    html = render_html(_attributed_and_signed())
    line = html[html.index("Signature") : html.index("</p>", html.index("Signature"))]
    assert "this page does not check it" in line and "covered-verify" in line
    assert "hmac-sha256:" + "ab" * 32 in line


def test_render_with_attribution_and_signature_contains_no_legal_conclusion_terms() -> None:
    assert legal_conclusions(render_html(_attributed_and_signed())) == []
