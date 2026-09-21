"""the hand-built sample for the fictional operator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from covered_evidence.bundle.coverage import check_coverage
from covered_evidence.bundle.diff import diff_bundles
from covered_evidence.bundle.lint import legal_conclusions
from covered_evidence.bundle.render import render_html
from covered_evidence.bundle.schema import Bundle, FindingLevel, FindingStatus, VerificationMode
from covered_evidence.scenarios import RESTRICTED_CODES

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "fernwood-pip"


@pytest.fixture(scope="module")
def builds() -> tuple[Bundle, Bundle]:
    b1 = Bundle.from_dict(json.loads((SAMPLE / "build-1.json").read_text()))
    b2 = Bundle.from_dict(json.loads((SAMPLE / "build-2.json").read_text()))
    return b1, b2


def test_both_sample_builds_validate(builds: tuple[Bundle, Bundle]) -> None:
    b1, b2 = builds
    assert b1.build.build_id != b2.build.build_id


def test_sample_has_one_finding_at_each_of_the_three_levels(builds: tuple[Bundle, Bundle]) -> None:
    b1, _ = builds
    br = [f for f in b1.findings if f.scenario == "BR"]
    assert {f.level for f in br} == set(FindingLevel)


def test_sample_findings_use_only_non_restricted_categories(builds: tuple[Bundle, Bundle]) -> None:
    for b in builds:
        assert not {f.scenario for f in b.findings} & RESTRICTED_CODES


def test_restricted_scenarios_are_listed_as_not_exercised_on_the_cover(
    builds: tuple[Bundle, Bundle],
) -> None:
    b1, _ = builds
    assert set(b1.cover.scenarios_not_exercised) >= RESTRICTED_CODES


def test_coverage_balances_in_both_builds(builds: tuple[Bundle, Bundle]) -> None:
    for b in builds:
        check_coverage(b.coverage)


def test_diff_moves_the_output_finding_to_not_observed_with_three_modes(
    builds: tuple[Bundle, Bundle],
) -> None:
    b1, b2 = builds
    d = diff_bundles(b1, b2)
    moved = [c for c in d.status_changes if c.after is FindingStatus.NOT_OBSERVED_IN_VERIFICATION]
    assert moved, "expected at least one finding verified as fixed"
    for c in moved:
        assert {v.mode for v in d.verification_for(c.finding_id)} == set(VerificationMode)
    assert d.incomplete_verification == []


def test_sample_renders_without_legal_conclusions(builds: tuple[Bundle, Bundle]) -> None:
    for b in builds:
        assert legal_conclusions(render_html(b)) == []


def test_sample_json_matches_the_canonical_form_of_its_model() -> None:
    """Hand edits must stay in canonical form so the generator can reproduce the sample."""
    for name in ("build-1.json", "build-2.json"):
        raw = (SAMPLE / name).read_text()
        b = Bundle.from_dict(json.loads(raw))
        assert raw == json.dumps(b.to_dict(), indent=2, ensure_ascii=False) + "\n", name


def test_checked_in_html_is_the_render_of_the_checked_in_json() -> None:
    for name in ("build-1", "build-2"):
        b = Bundle.from_dict(json.loads((SAMPLE / f"{name}.json").read_text()))
        assert (SAMPLE / f"{name}.html").read_text() == render_html(b), name
