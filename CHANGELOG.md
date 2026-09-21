# Changelog

## 0.1.0 (unreleased)

First public extraction: evidence bundle schema (version 1), signing and the offline verifier
(`covered-verify`), deterministic HTML render, the Mode B staging contract with its contract
test suite, the reference target, the statute crosswalk, and signed sample bundles.

Hardened before release. A readiness audit found the reference target loading its state file
with pickle. Four passes of an independent review then reproduced, and this version closes:
a duplicate JSON key that showed one value and verified another; a key name in the signature
string that was not authenticated; fields silently defaulted on load; an amendment that could
rewrite what was found, upgrade evidence, or slip in a demoted copy of a finding under an
existing id or an invisible, punctuation or other-script lookalike of one; a bundle that signed
in Python but could not be loaded by a verifier; a legal-conclusion lint the library did not enforce; verifier exit
codes that reported "could not run" as "not verified"; a staging client that could crash on a
non-JSON body, repeat a call against a non-idempotent target, or attach its token to a crafted
path; and a lint that read only the fields the render happens to show. A review of the final
changes then found, and this version also closes: an amendment callback that altered the verified
bundle in place and was compared with its own alteration; verification rows that could be
rewritten or could name no finding; capability flags read loosely; and not-assessed reasons
missing from the human-readable render.

An outside review of the extracted repository then found, and this version closes: verification
that read as complete with nothing graded, and a reproduced finding recorded as not observed;
impossible counts and calibration statistics that loaded and signed; change attribution that an
amendment could delete; amendments whose computed change list the render did not show; a refused
amendment that still altered the caller's bundle; retry permission granted by a `/build` that
named no build; a reference target that started two sessions for one key under concurrency and
kept a deleted account's contents (and, once that was fixed, freed the keys the account had
consumed); a not-observed claim that could be signed with no graded verification beside it; and a diff that credited the target when the actor, adapter
or scripts had changed, or when the operator had simply recorded a decision (new cause
`operator_decision`). Dependency floors moved to patched releases (`cryptography>=50.0.1`,
`pytest>=9.0.3`); CI now builds the wheel, verifies a sample from it, and audits the lock.
Added `docs/READING.md` (how to interpret a bundle) and `examples/workflow.py` (sign, verify,
render, diff, amend), which a test runs.
