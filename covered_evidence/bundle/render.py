"""Deterministic HTML rendering of a bundle. Scope cover first, always.

Standard-library string building; no template engine. Every value that
originates outside this module is HTML-escaped.
"""

from __future__ import annotations

import html
from collections.abc import Iterable

from covered_evidence.bundle.schema import Bundle, Finding, VerificationResult
from covered_evidence.scenarios import SCENARIOS

_CSS = """
:root{--ink:#1c1f26;--muted:#5b6170;--paper:#fbfaf7;--rule:#d9d5cc;--accent:#2f4f6f;
--observed:#8a3b12;--ok:#2e6b3e;--warn:#8a6d0b}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Georgia,serif;padding:32px 20px}
main{max-width:72ch;margin:0 auto}
h1,h2,h3{font-family:Georgia,serif;line-height:1.2;text-wrap:balance}
h1{font-size:1.9rem;margin:0 0 .25rem}h2{font-size:1.3rem;margin:2.2rem 0 .6rem;border-top:1px solid var(--rule);padding-top:1rem}
table{border-collapse:collapse;width:100%;font-size:.92rem;font-variant-numeric:tabular-nums}
th,td{text-align:left;vertical-align:top;padding:.35rem .5rem;border-bottom:1px solid var(--rule)}
th{font-family:system-ui,sans-serif;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.eyebrow{font-family:system-ui,sans-serif;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.tag{display:inline-block;font-family:system-ui,sans-serif;font-size:.72rem;letter-spacing:.04em;padding:.1rem .45rem;border:1px solid var(--rule);border-radius:2px}
.status-observed{color:var(--observed);border-color:var(--observed)}
.status-not_observed_in_verification{color:var(--ok);border-color:var(--ok)}
.status-under_remediation,.status-blocked,.status-client_attested{color:var(--warn);border-color:var(--warn)}
.unsigned{background:#fff3cd;border:1px solid #d9b94a;padding:.5rem .75rem;font-family:system-ui,sans-serif;font-size:.85rem}
blockquote{margin:.5rem 0;padding:.4rem .8rem;border-left:3px solid var(--rule);color:var(--muted);font-size:.92rem}
dl{display:grid;grid-template-columns:max-content 1fr;gap:.2rem 1rem}dt{color:var(--muted)}dd{margin:0}
.wrap{overflow-x:auto}
"""


_NO_RISKS = '<tr><td colspan="4"><em>none</em></td></tr>'


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _tag(status: str) -> str:
    return f'<span class="tag status-{_e(status)}">{_e(status.replace("_", " "))}</span>'


def _list(items: Iterable[str], empty: str = "none") -> str:
    items = list(items)
    return ", ".join(_e(i) for i in items) if items else f"<em>{_e(empty)}</em>"


def _scenario_name(code: str) -> str:
    s = SCENARIOS.get(code)
    return f"{code} · {s.name}" if s else code


def _finding_block(f: Finding, verification: list[VerificationResult]) -> str:
    rep = f.reproduction
    rows = "".join(
        f"<tr><td>{_e(v.mode.value.replace('_', ' '))}</td>"
        f"<td>{v.reproductions} / {v.attempts}{f' ({v.withheld} withheld)' if v.withheld else ''}</td>"
        f"<td>{_e(v.against_build)}</td></tr>"
        for v in verification
    )
    ver = (
        f'<div class="wrap"><table><thead><tr><th>Verification mode</th><th>Reproduced / attempts</th>'
        f"<th>Against build</th></tr></thead><tbody>{rows}</tbody></table></div>"
        if rows
        else ""
    )
    related = _list(f.related_findings, "none")
    return (
        f'<article id="{_e(f.finding_id)}"><h3>{_e(f.finding_id)} &nbsp;{_tag(f.status.value)} '
        f'<span class="tag">{_e(f.severity.value)}</span> <span class="tag">{_e(f.level.value)}</span></h3>'
        f"<dl><dt>Bears on</dt><dd>{_e(f.citation)} ({_e(_scenario_name(f.scenario))})</dd>"
        f"<dt>Path</dt><dd>{_e(f.ladder)}, rung {f.rung}, persona band {_e(f.persona_band)}</dd>"
        f"<dt>Human review</dt><dd>{_e(f.review_disposition)}"
        f"{' (human-confirmed)' if f.human_confirmed else ''}</dd>"
        f"<dt>Acquisition</dt><dd>{rep.acquisition_observations} observation(s)</dd>"
        f"<dt>Reproduction</dt><dd>{rep.reproductions} of {rep.attempts} attempt(s)</dd>"
        f"<dt>Seeds</dt><dd>actor {_e(f.seeds.actor)}, director {_e(f.seeds.director)}, "
        f"target {_e(f.seeds.target)}</dd>"
        f"<dt>Related</dt><dd>{related}</dd></dl>"
        f'<blockquote class="evidence">{_e(f.excerpt_redacted)}</blockquote>{ver}</article>'
    )


def render_html(b: Bundle) -> str:
    """Render a complete HTML document for ``b``; byte-identical for equal bundles."""
    iss = b.issuance
    signed = (
        '<p class="eyebrow">Signature (verify with covered-verify; this page does not check it) '
        f"{_e(iss.signature)}</p>"
        if iss.signature
        else '<p class="unsigned">UNSIGNED. This bundle has not been issued. '
        "Do not rely on it as a record.</p>"
    )
    cover = b.cover
    req_rows = "".join(
        f"<tr><td>{_e(r.citation)}</td><td>{_tag(r.status.value)}</td><td>{_e(r.note)}</td></tr>"
        for r in b.requirements
    )
    findings = "".join(
        _finding_block(f, [v for v in b.verification if v.finding_id == f.finding_id])
        for f in b.findings
    )
    attribution_rows = "".join(
        f"<tr><td>{_e(a.finding_id)}</td><td>{_e(a.cause.value.replace('_', ' '))}</td>"
        f"<td>{_e(a.note)}</td></tr>"
        for a in b.change_attribution
    )
    attribution = (
        '<section id="change-attribution"><h2>Changes since the prior bundle</h2>'
        "<p>For each finding whose status differs from the prior bundle: whether the difference "
        "is attributed to the target's behavior or to the measurement (rubric, judge, or "
        'scenario library).</p><div class="wrap"><table><thead><tr><th>Finding</th>'
        f"<th>Attributed to</th><th>Note</th></tr></thead><tbody>{attribution_rows}</tbody>"
        "</table></div></section>"
        if attribution_rows
        else ""
    )
    risks = "".join(
        f"<tr><td>{_e(r.risk_id)}</td><td>{_e(r.description)}</td><td>{_e(r.owner)}</td>"
        f"<td>{_e(r.rationale)}</td></tr>"
        for r in b.open_risks
    )
    cov = b.coverage
    by_state: dict[str, int] = {}
    for o in cov.outcomes:
        by_state[o.terminal_state.value] = by_state.get(o.terminal_state.value, 0) + 1
    cov_rows = "".join(
        f"<tr><td>{_e(k)}</td><td>{v}</td></tr>" for k, v in sorted(by_state.items())
    )
    # every cell that did not complete, with its state and why: this is where a reader learns
    # what scope is missing
    blocked = "".join(
        f"<li>{_e(o.cell_id)} ({_e(o.terminal_state.value.replace('_', ' '))}): {_e(o.reason)}</li>"
        for o in cov.outcomes
        if o.terminal_state.value != "completed"
    )
    m = b.methodology
    cal_rows = "".join(
        f"<tr><td>{_e(_scenario_name(c.category))}</td><td>{c.positives}</td>"
        f"<td>{c.negatives}</td>"
        f"<td>{c.precision:.2f} [{c.precision_ci_low:.2f}, {c.precision_ci_high:.2f}]</td>"
        f"<td>{c.recall:.2f} [{c.recall_ci_low:.2f}, {c.recall_ci_high:.2f}]</td>"
        f"<td>{'met' if c.meets_gate else 'not met'}</td>"
        f"<td>{_e(c.issuance_path.value.replace('_', ' '))}</td></tr>"
        for c in m.calibration
    )
    calibration = (
        '<h3>Judge calibration (held-out labels)</h3><div class="wrap"><table><thead><tr>'
        "<th>Category</th><th>Human positives</th><th>Human negatives</th>"
        "<th>Precision [95% CI]</th><th>Recall [95% CI]</th><th>Gate</th><th>Path</th>"
        f"</tr></thead><tbody>{cal_rows}</tbody></table></div>"
        if m.calibration
        else "<p>No category was calibrated on held-out labels for this judge and rubric; "
        "no category issued on the judge path.</p>"
    )
    # the description is the issuer's words; the changed paths and the superseded digest are
    # computed, and are what lets a reader check the description against what happened
    amendments = "".join(
        f"<li>{_e(a.amendment_id)} ({_e(a.issued_at)}): {_e(a.description)}"
        f"<br>Changed: {_list(a.changes)}"
        f"<br>Supersedes sha256 <code>{_e(a.supersedes_sha256)}</code></li>"
        for a in b.amendments
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(b.chatbot)} evidence bundle {_e(b.build.build_id)}</title>"
        f"<style>{_CSS}</style></head><body><main>"
        f'<section id="cover"><p class="eyebrow">Covered evidence bundle · {_e(b.bundle_id)}</p>'
        f"<h1>{_e(b.chatbot)} · build {_e(b.build.build_id)}</h1>"
        f"<p>Operator: {_e(b.operator)}. Build config {_e(b.build.config_hash)} "
        f"captured {_e(b.build.captured_at)}. Issued {_e(iss.issued_at)}.</p>{signed}"
        f"<h2>Tested scope</h2><dl>"
        f"<dt>Scenarios exercised</dt><dd>{_list(map(_scenario_name, cover.scenarios_exercised))}</dd>"
        f"<dt>Not exercised</dt><dd>{_list(map(_scenario_name, cover.scenarios_not_exercised))}</dd>"
        f"<dt>Persona bands</dt><dd>{_list(cover.persona_bands_exercised)}</dd>"
        f"<dt>Framings</dt><dd>{_list(cover.framings_exercised)}</dd>"
        f"<dt>Persistence</dt><dd>{_list(cover.persistence_exercised)}</dd></dl>"
        "<p>This bundle records what was tested, what was observed, what changed, and what "
        "remains open. It does not determine whether any observation is a legal matter or "
        "whether any mitigation is adequate; those are the operator's own assessments.</p>"
        "</section>"
        f'<section id="requirements"><h2>Evidence status per requirement</h2><div class="wrap">'
        f"<table><thead><tr><th>Requirement</th><th>Status</th><th>Note</th></tr></thead>"
        f"<tbody>{req_rows}</tbody></table></div></section>"
        f'<section id="findings"><h2>Observed safety failures</h2>'
        f"{findings or '<p><em>None recorded in scope.</em></p>'}</section>{attribution}"
        f'<section id="open-risks"><h2>Open risks</h2><div class="wrap"><table><thead><tr>'
        f"<th>Risk</th><th>Description</th><th>Owner</th><th>Rationale</th></tr></thead>"
        f"<tbody>{risks or _NO_RISKS}</tbody></table></div></section>"
        f'<section id="methodology"><h2>Methodology</h2><dl>'
        f"<dt>Persona matrix rule</dt><dd>{_e(m.persona_matrix_rule)}</dd>"
        f"<dt>Escalation ladders</dt><dd>{_list(m.ladders)}</dd>"
        f"<dt>Benchmarks consulted</dt><dd>{_list(m.benchmarks_consulted)}</dd>"
        f"<dt>Non-benchmark evaluation</dt><dd>{_e(m.non_benchmark_evaluation)}</dd>"
        f"<dt>Experts consulted</dt><dd>{_list(m.experts_consulted)}</dd>"
        f"<dt>Judge</dt><dd>{_e(m.judge.model_family)} {_e(m.judge.version)}; issuance path "
        f"{_e(m.judge.issuance_path.value.replace('_', ' '))}</dd>"
        f"<dt>Content guard</dt><dd>{_e(m.content_guard)}</dd></dl>"
        f"{calibration}</section>"
        f'<section id="coverage"><h2>Coverage accounting</h2>'
        f'<p>{len(cov.planned_cells)} planned cells.</p><div class="wrap"><table><thead><tr>'
        f"<th>Terminal state</th><th>Cells</th></tr></thead><tbody>{cov_rows}</tbody></table></div>"
        f"{('<ul>' + blocked + '</ul>') if blocked else ''}</section>"
        f'<section id="issuance"><h2>Issuance snapshot</h2><dl>'
        f"<dt>Scenario library</dt><dd>{_e(iss.scenario_library_version)}</dd>"
        f"<dt>Rubric</dt><dd>{_e(iss.rubric_version)}</dd>"
        f"<dt>Adapter</dt><dd>{_e(iss.adapter_version)}</dd>"
        f"<dt>Actor model</dt><dd>{_e(iss.actor_model)}</dd>"
        f"<dt>Judge model</dt><dd>{_e(iss.judge_model)}</dd>"
        f"<dt>Script hashes</dt><dd>{_list(iss.script_hashes)}</dd>"
        f"<dt>Transcript hashes</dt><dd>{len(iss.transcript_hashes)} recorded</dd>"
        f"<dt>Review decisions</dt><dd>{iss.review_decisions}</dd></dl>"
        f"{('<h3>Amendments</h3><ul>' + amendments + '</ul>') if amendments else ''}"
        "</section></main></body></html>"
    )
