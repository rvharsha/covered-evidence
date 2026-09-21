"""Review fix: excerpts are the target's words and must not abort issuance."""

from __future__ import annotations

from covered_evidence.bundle.lint import legal_conclusions
from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle
from tests.bundle.factories import finding_dict, minimal_bundle_dict


def test_an_excerpt_containing_conclusion_words_renders_and_passes_lint() -> None:
    d = minimal_bundle_dict()
    d["findings"] = [finding_dict(excerpt_redacted="[target] It's safe, that's a reasonable ask.")]
    html = render_html(Bundle.from_dict(d))
    assert "reasonable ask" in html
    assert legal_conclusions(html) == []


def test_a_requirement_note_with_a_conclusion_word_is_still_caught() -> None:
    d = minimal_bundle_dict()
    d["requirements"][0]["note"] = "operator is compliant here"
    assert legal_conclusions(render_html(Bundle.from_dict(d))) == ["compliant"]
