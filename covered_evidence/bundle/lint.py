"""Legal-conclusion lint (principle 7).

The bundle says what was tested and observed. It never says the operator is
compliant, that something is a violation, that a mitigation is reasonable,
or that the chatbot is safe. Quoted statute text inside
``<q class="statute">...</q>`` is exempt because the statute itself uses
these words, and quoted evidence inside ``<blockquote class="evidence">``
is exempt because those are the target's words, not the bundle's.
"""

from __future__ import annotations

import re
import unicodedata

LEGAL_CONCLUSION_TERMS: frozenset[str] = frozenset(
    {
        "compliant",
        "noncompliant",
        "non-compliant",
        "compliance",
        "violation",
        "violations",
        "violates",
        "violated",
        "reasonable",
        "unreasonable",
        "safe",
        "unlawful",
        "lawful",
        "liable",
    }
)

#: Inflections and neighbours of the terms above. Kept apart so the documented list stays the
#: statute-shaped core; both sets are forbidden. "safety", "safeguard" and "unsafe by rubric"
#: name a field or a rubric outcome, not a verdict on the operator, and stay allowed.
_STEMS: frozenset[str] = frozenset(
    {
        "comply",
        "complies",
        "complied",
        "complying",
        "noncompliance",
        "violate",
        "violating",
        "illegal",
        "illegally",
        "negligent",
        "negligently",
        "negligence",
        "safer",
        "safest",
        "safely",
        "liability",
        "unreasonably",
        "lawfully",
        "unlawfully",
        "legality",
        "illegality",
        "violative",
    }
)
_FORBIDDEN = {t for t in LEGAL_CONCLUSION_TERMS if "-" not in t} | _STEMS


class LegalConclusionError(ValueError):
    """The bundle states a legal conclusion (principle 7). It is refused, not signed."""


_STATUTE_QUOTE = re.compile(r'<q class="statute">.*?</q>', re.DOTALL)
_EVIDENCE_QUOTE = re.compile(r'<blockquote class="evidence">.*?</blockquote>', re.DOTALL)
_WORD = re.compile(r"[^\W\d_]+")  # runs of letters; hyphens and underscores separate words


def _scripts(word: str) -> set[str]:
    return {unicodedata.name(ch, "?").split(" ")[0] for ch in word}


def legal_conclusions(text: str) -> list[str]:
    """Forbidden terms found in ``text``, lower-cased, in order of appearance.

    The text is compared the way a reader sees it: compatibility forms are folded (fullwidth
    letters), invisible format characters are removed (soft hyphen, zero-width space), and a
    hyphen or underscore separates words, so ``safe-by-design`` and ``safe_mode`` are caught.
    A word that mixes scripts is reported as ``mixed-script:<word>``: a Cyrillic or Greek
    lookalike inside a Latin word is how a forbidden term hides from a word list."""
    stripped = _EVIDENCE_QUOTE.sub("", _STATUTE_QUOTE.sub("", text))
    folded = unicodedata.normalize("NFKC", stripped)
    # format characters, and combining marks and variation selectors that survive composition:
    # none of them is visible inside a word, and each would split it
    folded = "".join(ch for ch in folded if unicodedata.category(ch) not in ("Cf", "Mn", "Me"))
    hits: list[str] = []
    for m in _WORD.finditer(folded):
        word = m.group(0)
        lower = word.lower()
        if lower in _FORBIDDEN:
            hits.append(lower)
        elif len(_scripts(word)) > 1 and "LATIN" in _scripts(word):
            hits.append(f"mixed-script:{word}")
    return hits


#: The target's and the simulated user's own words. They are evidence, not the bundle's voice.
_EXEMPT_FIELDS = frozenset({"excerpt_redacted"})


def legal_conclusions_in(document: object, path: str = "") -> list[str]:
    """Forbidden terms in ANY string of a bundle's JSON form, as ``path: term``. The render shows
    only some fields; a verdict in one it does not show (a coverage reason, a version string, an
    identifier) would otherwise be signed unread."""
    hits: list[str] = []
    if isinstance(document, dict):
        for key, value in document.items():
            if key not in _EXEMPT_FIELDS:
                hits += legal_conclusions_in(value, f"{path}.{key}" if path else str(key))
    elif isinstance(document, list):
        for i, value in enumerate(document):
            hits += legal_conclusions_in(value, f"{path}[{i}]")
    elif isinstance(document, str):
        hits += [f"{path}: {term}" for term in legal_conclusions(document)]
    return hits
