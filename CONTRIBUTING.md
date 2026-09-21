# Contributing

Thank you for helping. A few things are different here from most projects.

**Never submit restricted content.** No self-harm, sexual, romantic, isolation, or
emotional-dependency user-side text, real or invented, in code, tests, fixtures, samples,
issues, or pull requests (principle 1 in `docs/PRINCIPLES.md`). Use placeholder strings and
their hashes. A pull request that contains such text will be closed and its history removed.

**Fictional operators only.** Never name a real company or product as a test target.

**Test first.** Every behaviour change starts with a failing test that names the behaviour as a
sentence (`test_a_repeated_key_returns_the_original_response`). Unit tests make no network
calls and read no clock. Never skip or `xfail` a test to get green.

**The contract suite is the spec.** A change to the Mode B contract changes
`tests/adapters/contract/` and `docs/MODE_B.md` in the same pull request.

**Format changes are breaking until 1.0 and need a changelog entry.** A change to the signed
form of a bundle must say how existing signed bundles are still verified.

Before you push: `scripts/check.sh` (pytest, ruff, format check, strict mypy) must pass.
