# Reading a bundle

Test cases can stay private. What the numbers and words in a bundle mean cannot, or two bundles
could not be compared. This page defines them. Where the format does not yet pin a meaning down,
it says so.

## Evidence status, per requirement

| Status | Meaning |
|---|---|
| `observed` | The behaviour was exercised in conversation against the staging target and the outputs were graded. |
| `client_attested` | The operator says so. Nothing was tested. |
| `manually_inspected` | A person looked at a setting, screen or document. It was not exercised in conversation. |
| `not_assessed` | Out of scope for this bundle. The coverage section gives the reason. |
| `blocked` | It was in scope and could not be tested: a missing capability, an unsupported API, a crashed session. The reason is recorded. |

Most statutory requirements cannot be seen in a conversation. Expect many rows that are not
`observed`; a bundle in which everything is `observed` deserves suspicion, not comfort.

## Findings

A finding is an observed safety failure at one of three levels: a single `output`, a
`conversation`, or an `account_timeline` spanning sessions with memory carried over.

**Status** is one of `observed`, `under_remediation`, `not_observed_in_verification`,
`risk_accepted`. The second and fourth are decisions someone recorded. Only the third is a test
result, and it means exactly its name: not seen again under the verification that was run. It
does not mean fixed.

**Severity** is `critical`, `high`, `medium` or `low`. The format fixes the levels, their order,
and two rules: severity is a separate field from how often a finding reproduced, and an amendment
can raise it but never lower it. The format does **not** yet define criteria for each level.
Ask the issuer for its severity definitions; without them, severities from two issuers are not
comparable. Naming the severity scheme inside the bundle is a planned format change.

**Reproduction** counts three things separately. `acquisition_observations` is how many times
the original run saw the failure. `attempts` and `reproductions` are later tries to see it again.
A low reproduction rate says the failure is intermittent. It does not lower the severity.

## Fix verification: three modes, reported separately

Each row is one finding, against one earlier build, in one mode.

| Mode | What was done |
|---|---|
| `exact_replay` | The recorded user turns were sent again, word for word, on a rebuilt account (earlier sessions replayed first when the finding depends on memory). |
| `adaptive_replay` | The same objective and escalation path, driven afresh, so the wording differs and follows the target's new replies. |
| `held_out_variation` | The same objective by a different escalation path, not used when the finding was first found. |

A fix that only pattern-matches the original wording passes the first and fails the others, which
is why they are never summed.

**Denominators.** `attempts` is every try. `withheld` is the tries that were never graded: a
content guard routed the reply to a human, an evaluator refused, or nothing was sent because the
target does not declare idempotent turns. `reproductions` is graded tries that showed the failure
again. So graded tries are `attempts - withheld`, and a withheld try is **not** a clean one.

The rule the format expects: a finding is `not_observed_in_verification` only on a different
build, with all three modes attempted, every attempt graded, and zero reproductions. The library refuses to load or sign
a bundle that says otherwise: the three fully graded modes must be in the same bundle as the
claim. It cannot check the build. The diff adds two flags. `incomplete_verification` lists
findings whose move to not-observed was verified against a different baseline than the bundle
being compared. `reopened_unverified` lists findings an earlier bundle had as not-observed that
this one carries as `observed` with nothing new seen, because this build could not be verified;
that is an issuer keeping a finding open, not a regression. Both are `unattributed`.

## Why a status changed

`change_attribution` gives one cause per finding whose status differs from the prior bundle.

| Cause | Meaning |
|---|---|
| `target_behavior` | Same rubric, judge, scenario library, actor, adapter and scripts; the target's build or configuration differs. |
| `measurement` | The rubric, judge or scenario library changed, the retained baseline evidence was re-graded with the new ones, and the old finding would not have been a finding. The change is in the ruler. |
| `operator_decision` | The status is `under_remediation` or `risk_accepted`. Someone decided; nothing was observed. |
| `unattributed` | The actor, adapter or scripts changed, no baseline evidence was retained to re-grade, or the change is one the diff flags as unverified. The cause cannot be separated, so none is claimed. |

## Calibration

When a model grades outputs, `methodology.calibration` reports, per category, how that judge and
rubric did against human labels **held out** from rubric development: counts of human positives
and negatives, precision and recall with Wilson 95% intervals, and whether the issuer's gate was
met. `issuance_path` then says which path the category took: `judge_met_gate`,
`fully_human_reviewed`, or `review_pending`. The gate's thresholds are the issuer's, and are not
in the bundle; ask for them. An empty calibration list means no category was issued on the
judge's word.

## Coverage

Every planned persona cell ends in exactly one of `completed`, `blocked` or `not_assessed`, and
the two that are not `completed` carry a reason. The count of planned cells never changes by
amendment. Read the blocked list first: it is the part of the plan that produced no evidence.

## What the reviewer still has to do

Verify the signature with a key obtained from the issuer directly. Read the amendments and their
computed change lists. Check that the build under test is the build you care about. Ask for the
transcripts behind the hashes, the severity definitions, and the calibration gate. The bundle is
a record of testing. It is not a complete statutory audit, an assessment of internal controls,
or a legal determination, and it never uses the words that would make it sound like one.
