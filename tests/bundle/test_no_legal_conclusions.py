"""the bundle never states a legal conclusion."""

from __future__ import annotations

import pytest

from covered_evidence.bundle.lint import LEGAL_CONCLUSION_TERMS, legal_conclusions


@pytest.mark.parametrize("term", sorted(LEGAL_CONCLUSION_TERMS))
def test_each_forbidden_term_is_detected_as_a_whole_word(term: str) -> None:
    # a hyphen separates words, so "non-compliant" is reported as its forbidden word
    assert legal_conclusions(f"The chatbot is {term}.") == [term.split("-")[-1]]


def test_detection_is_case_insensitive() -> None:
    assert legal_conclusions("COMPLIANT") == ["compliant"]


def test_safety_and_unsafe_are_not_flagged_as_safe() -> None:
    assert legal_conclusions("safety screen; the output was unsafe by rubric") == []


def test_reasonably_is_not_flagged_as_reasonable() -> None:
    assert legal_conclusions("the persona reasonably asked for a break") == []


def test_quoted_statute_text_is_exempt() -> None:
    text = '<q class="statute">reasonable measures to prevent</q> were tested'
    assert legal_conclusions(text) == []


def test_multiple_hits_are_returned_in_order_of_appearance() -> None:
    assert legal_conclusions("a violation; not compliant") == ["violation", "compliant"]


def test_quoted_evidence_is_exempt_because_it_is_the_targets_words_not_ours() -> None:
    text = (
        '<blockquote class="evidence">That is a reasonable question and it is safe.</blockquote>'
        " observed"
    )
    assert legal_conclusions(text) == []


def test_bundle_prose_around_evidence_is_still_linted() -> None:
    text = '<blockquote class="evidence">fine</blockquote> the operator is compliant'
    assert legal_conclusions(text) == ["compliant"]


@pytest.mark.parametrize(
    "text, hit",
    [
        ("the operator complies with the chapter", "complies"),
        ("they did not comply", "comply"),
        ("the reply may violate the rule", "violate"),
        ("violating the default", "violating"),
        ("this is illegal", "illegal"),
        ("the operator was negligent", "negligent"),
        ("a safer build", "safer"),
        ("safe-by-design", "safe"),
        ("safe_mode is on", "safe"),
        ("com­pliant", "compliant"),  # soft hyphen
        ("com​pliant", "compliant"),  # zero-width space
        ("ｓａｆｅ", "safe"),  # fullwidth letters
    ],
)
def test_stems_joiners_and_invisible_characters_do_not_slip_a_conclusion_through(
    text: str, hit: str
) -> None:
    assert legal_conclusions(text) == [hit]


def test_a_word_mixing_scripts_is_reported_because_it_is_how_a_lookalike_hides() -> None:
    assert legal_conclusions("the chatbot is ѕafe") == ["mixed-script:ѕafe"]


def test_safety_stays_allowed_because_it_names_the_field_not_a_verdict() -> None:
    assert legal_conclusions("child safety; common safety screen; safeguards") == []


@pytest.mark.parametrize(
    "text",
    [
        "a breach of the usage cap was observed",
        "the legally required notice was shown",
        "conformity with the product's own labels",
    ],
)
def test_words_an_honest_author_needs_are_not_refused(text: str) -> None:
    """Third review pass: these stems produced false positives on legitimate evidence prose."""
    assert legal_conclusions(text) == []
