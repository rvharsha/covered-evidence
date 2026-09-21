# Principles

The rules the evidence format and the staging contract encode. Source comments cite them by
number. A change that breaks one is wrong even if every test passes.

1. **No restricted content in this repository, ever.** No self-harm, sexual, romantic,
   isolation, or emotional-dependency user-side text in code, fixtures, tests, samples, docs,
   issues, or commit messages. Restricted test scripts are referenced by content hash only, and
   tests use hashes of synthetic placeholder strings.
2. **Restricted text never reaches a third-party model.** A bundle records script hashes for
   restricted sessions, not the text.
3. **Judge and actor are different model families**, and the judge differs from the target's
   family where that is determinable. Enforced in configuration validation, not by convention.
4. **Evaluator-only knowledge never reaches the target.** The persona's true age band, the
   scenario, the rung and the rubric are never sent in a turn, a header, or an idempotency key.
5. **Nothing is hidden.** A fidelity gap, a missing capability, a crashed session: each is
   reported as `blocked` or `client_attested`, never dropped. Coverage accounting balances.
6. **Severity and reproduction frequency are separate fields.** A human-confirmed finding is
   never demoted because it failed to reproduce.
7. **The bundle never states a legal conclusion.** It does not say *compliant*, *violation*,
   *reasonable*, or *safe*. Release decisions are recorded separately from evidence status.
8. **Staging only.** No model weights, system prompts, source code, production data, or
   production credentials. Anything that looks like production in a configuration is an error.
9. **Every side effect against a target is idempotent and checkpointed.** Account creation,
   session start and turn submission each carry an idempotency key.
10. **Issued bundles are immutable.** Rubric, judge, scenario, script, adapter and model
    versions are pinned in the issuance snapshot. Corrections are explicit amendments.
11. **Seeds are recorded separately** for actor, director and target, and a component that
    cannot be seeded says so.
12. **Tenant isolation is structural.** One operator's data never appears in another's
    bundles; a prior bundle from another operator or chatbot is refused.
