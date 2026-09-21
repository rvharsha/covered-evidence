# Covered Evidence

The open evidence format, offline verifier, and staging contract for child-safety testing of
companion chatbots.

When a chatbot that admits minors is tested for safety, someone eventually has to show what was
tested, what was observed, what was fixed, and what is still open, to an auditor, to counsel, or
in discovery. **Covered Evidence** is the part of that problem that should not be proprietary:

| | What it is | Where |
|---|---|---|
| **Evidence bundle** | A versioned, signed JSON record for one chatbot at one build: scope, methodology, findings at three levels, coverage accounting, fix verification against a prior build, and an issuance snapshot that pins every version that produced it. Deterministic HTML render. | `covered_evidence/bundle/` |
| **Offline verifier** | `covered-verify` checks a bundle's signature with the issuer's public key and nothing else. No network, no account, and no connection to the issuer's service. It authenticates the record; it does not vouch for the testing behind it. | `covered_evidence/verify_cli.py` |
| **Mode B contract** | The five HTTP endpoints an operator exposes in **staging** so an independent tester can drive real multi-turn, multi-session conversations, with idempotent, checkpointed side effects. A contract test suite is the spec. | `covered_evidence/adapters/`, `tests/adapters/contract/`, `docs/MODE_B.md` |
| **Reference target** | An in-process mock chatbot that implements the contract, with caps, memory, a parent sink, and switchable faults, so a client can be built and tested without a real product. | `covered_evidence/mock_target/` |
| **Statute crosswalk** | Scenario codes mapped to the subsections of California Bus. & Prof. Code §21812 et seq. they bear on, and which of them can be observed in conversation at all. | `covered_evidence/scenarios.py` |
| **Samples** | Two hand-built bundles for a fictional operator, signed, with a tampered copy that must fail. | `samples/fernwood-pip/` |

It does **not** include a test corpus, adversarial scenarios, rubrics, a judge, or an
orchestration engine. Those are how a tester measures; this repository is how the measurement is
recorded, exchanged, and checked. The split is deliberate: a public rubric can be tuned to, and
evidence is worth more when the party that produced it is not the party it describes.
Private test cases are not private definitions: what the severities, the three replay modes,
the counts and a withheld attempt mean is public, in [`docs/READING.md`](docs/READING.md).

> **Status: alpha.** The format will change before 1.0. See [Stability](#stability).

## Verify a bundle

```bash
uv sync
uv run covered-verify samples/fernwood-pip/build-1.signed.json \
  --public-key samples/fernwood-pip/test-public-key.pem
# bndl-fernwood-pip-0001: signature verifies
#   key: kms-ec-p256-sha256:samples/fernwood-pip/test-key/cryptoKeyVersions/1
#   sha256 of signed bytes: …

uv run covered-verify samples/fernwood-pip/build-1.tampered.json \
  --public-key samples/fernwood-pip/test-public-key.pem
# bndl-fernwood-pip-0001: signature does NOT verify          (exit status 1)
```

The exit status is a contract a script can act on:

| Status | Meaning |
|---|---|
| `0` | The signature verifies, for the key named **inside** the signed bytes |
| `1` | The check ran, and the signature does not verify |
| `3` | The check could not run: a missing or malformed key, an unreadable or malformed bundle |

On success the tool prints only authenticated facts: the key id, which is part of the signed
bytes, and the SHA-256 of those bytes. Add `--key-version NAME` to require a particular key.
Signatures are ECDSA over P-256 with SHA-256, low-S form only; the scheme and the canonical
bytes are specified in [`docs/SIGNING.md`](docs/SIGNING.md). An HMAC scheme exists for demos
and tests only.

From Python:

```python
from covered_evidence.bundle.schema import Bundle
from covered_evidence.bundle.signing import PublicKeyVerifier, verify_bundle

bundle = Bundle.from_json(open("bundle.json").read())
ok = verify_bundle(bundle, PublicKeyVerifier(open("issuer.pem").read()))
```

Read evidence with `Bundle.from_json`, not `json.loads`. It refuses duplicate keys, because
`json.loads` keeps the last one while a human reader sees the first, and the non-JSON tokens
`NaN` and `Infinity`. Loading is strict: every field must be present, an unknown field is an
error, a status outside its enumeration is an error, and a `schema_version` this library does
not read is refused by name. Nothing is defaulted on load, a float field takes a float token, and every identifier that
keys a record (finding, citation, risk, amendment, cell) must be unique and plainly readable: no
invisible characters, no lookalike letters from another script. Which record a lookup returns, and
which a reader sees, never depends on list order. `sign_bundle` proves a bundle loads back from
its own JSON before it signs, so what an issuer ships an auditor can read.

## What verification proves, and what it does not

`covered-verify` proves one thing: these exact bytes were signed by the holder of the key
whose public half you supplied. It does not prove that the tests happened, that the sample was
representative, that staging matched production, that a reviewer was qualified, or that the
public key you hold belongs to the issuer it claims to. Get the key from the issuer through a
channel you trust, and judge the measurements on the methodology the bundle records. Loading a
bundle adds consistency checks (coverage balances, references resolve, counts are possible, a
finding that reproduced is not marked not-observed), but a consistent record is still only as
good as the testing behind it.

## Issue a bundle

```bash
uv run python examples/workflow.py out/
```

[`examples/workflow.py`](examples/workflow.py) is the issuer's side end to end, and a test runs
it: load two authored documents strictly, sign with a P-256 key, verify as a recipient would,
render HTML, diff the builds with change attribution, and amend the record.
`samples/fernwood-pip/author.py` shows how a document is authored by hand; an exporter from
your own testing tool would write the same JSON. There is no such exporter in this repository
yet, and the only command-line tool is the verifier. Exchanging bundles does not require the
operator to implement Mode B; that contract matters when a tester needs controlled accounts
and sessions in staging.

## What a bundle says, and refuses to say

A bundle records what was tested, what was observed, what changed, and what is open. It never
states a legal conclusion: the words *compliant*, *violation*, *reasonable* and *safe* are
checked at signing (`covered_evidence/bundle/lint.py`): `sign_bundle` refuses a bundle in which
any string, rendered or not, contains a listed term. This is an editorial guardrail, not a
guarantee: a word list has false positives, and it catches the vocabulary of a verdict, not every
way to phrase one. Each statutory requirement carries one
of five evidence statuses, `observed`, `client_attested`, `manually_inspected`, `not_assessed`,
`blocked`, because most requirements cannot be seen in a conversation and a record that pretends
otherwise is worse than none. Coverage accounting must balance: every planned cell ends in
exactly one terminal state. See [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md).

## Implement the Mode B contract

Five endpoints, JSON, bearer token, **staging only**:

```
POST   /accounts                      create a synthetic account
POST   /accounts/{id}/sessions        start a session
POST   /sessions/{id}/turns           submit a user turn, get the reply
DELETE /accounts/{id}                 delete the account
GET    /build                         report build id, config hash, capabilities
```

Every mutating call carries an `Idempotency-Key`. Return the original response for a repeated
key, and `409` for a key reused with a different body. That one rule is what makes a tester's
crash recovery safe against your system: a turn is never submitted twice.
[`docs/MODE_B.md`](docs/MODE_B.md) is the specification, and `tests/adapters/contract/` is its
executable form, run here against the reference target.

The client treats the target as untrusted. It refuses anything that does not look like staging
(`covered_evidence/adapters/config.py`), attaches the token only after re-checking the final
URL's scheme and host, never follows a redirect, uses no proxy, caps response size, bounds each
attempt with a wall-clock deadline, and repeats a mutating call only after the target has
declared idempotent turns.

## Develop

```bash
uv sync --all-extras
scripts/check.sh        # pytest, ruff check, ruff format --check, mypy --strict
```

Python 3.11+. The only runtime dependency is `cryptography`. The `pdf` extra adds Playwright to
print a bundle's HTML render; it also needs a browser, installed once with
`uv run playwright install chromium`. The PDF path is tested here with a stand-in printer only,
not against a real browser. The JSON Schema ships in the wheel at
`covered_evidence/schemas/evidence-bundle-1.schema.json` and in this repository under `schemas/`. Unit tests use no network and no clock.

## Stability

Pre-1.0. The bundle carries a `schema_version` inside its signed bytes (today `"1"`), and the
JSON Schema for it is checked in at `schemas/evidence-bundle-1.schema.json` with a test that
keeps it identical to what the code generates. Known gaps we intend to close in a later version:

- Canonical bytes are Python's `json.dumps(sort_keys=True, separators=(",", ":"))`, not
  RFC 8785, and six calibration fields are floats. A verifier in another language must
  reproduce that exactly; see `docs/SIGNING.md`.
- The transport's per-attempt deadline bounds the response body only. DNS, connect, the TLS
  handshake and header receipt are limited per socket operation, so `max_block_seconds` is an
  expectation, not a hard bound: a target that drips its headers can exceed it.
- Quoted evidence excerpts are exempt from the legal-conclusion lint, as the target's words.
  They are capped at 8000 characters, but an issuer could still place prose there.
- An amendment may still rewrite a finding's excerpt and review disposition, a blocked cell's
  reason, and open-risk text. Each is recorded per field in the amendment's `changes`.
- The checked-in JSON Schema is necessary, not sufficient: the loader also enforces
  uniqueness, readable identifiers, resolvable references and strict JSON. Load with
  `Bundle.from_json`.
- Minted ids are ASCII, but `F-BR-O01` and `F-BR-001` are still two ids. A verification row
  added by amendment is recorded in `changes` only as `verification`.
- Passing a plain string where an enum is expected raises `AttributeError`, not `ValueError`.
- The lint is a word list. It refuses the vocabulary of a verdict, not every phrasing of one.
- The contract suite runs against the in-process reference target. Pointing it at a live
  staging URL is not supported yet, which limits it as an executable specification for an
  operator's own implementation.
- A finding carries an excerpt and the issuance snapshot a flat list of transcript hashes.
  Nothing yet ties a finding or a verification attempt to a particular transcript, session and
  turn span. Typed evidence references are the next format change we expect to make.
- No second implementation has verified a bundle. Until one does, and until conformance
  vectors are published, cross-language interoperability is a goal, not a property.
- No independent organisation has yet exchanged a bundle. This is a proposed format.

## Contributing, security, license

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md). This project never
accepts restricted-category test content (self-harm, sexual, romantic, or isolation user-side
text) in code, fixtures, issues, or pull requests; see principle 1.

Apache-2.0. Fernwood Friends, Inc. and its chatbot "Pip" are fictional.
