# Mode B: the staging contract

Five HTTP endpoints an operator exposes in **staging**, so an independent tester can hold real
multi-turn, multi-session conversations with the chatbot as synthetic users. JSON in and out.
`tests/adapters/contract/` is the executable form of this document, and
`covered_evidence/mock_target/` is a reference implementation.

Staging only. The client refuses a host that does not look like staging, refuses plain HTTP
except on loopback, never follows a redirect, and uses no proxy. Production data, production
credentials, model weights, system prompts and source code are never part of this contract.

## Authentication

`Authorization: Bearer <staging token>` on every call. Issue a token that works only in staging.

## Idempotency: the one rule that matters

Every mutating call carries an `Idempotency-Key` header (a non-empty opaque string; match the
header name case-insensitively).

- The same key with the same body returns the **original response**, and the side effect happens
  once. A turn is never generated twice.
- The same key with a **different** body returns `409`.
- A key names **one request to one operation** (create account, start session, submit turn,
  delete account). Reusing it for the same operation on another account or session is a changed
  request and returns `409`; mint a fresh key for every call. The same key under a different
  operation is a different request.
- Two requests with one key that overlap in time still produce one side effect. Serialize the
  cache check, the side effect and the durable write; check-then-act is not enough.

This is what makes a tester's crash recovery safe against your system: if a reply was sent and
the tester crashed before saving it, the retry retrieves that reply instead of producing another.
Declare it with `capabilities.idempotent_turns: true`. The client repeats a mutating call (after
a timeout, a dropped connection, or a 429/502/503/504) **only** once it has seen that declaration;
until then every mutating call is attempted exactly once. Keys are opaque: they carry no scenario,
persona or age information.

## Endpoints

### `GET /build`
No idempotency key. Reports what is under test.
```json
{"build_id": "pip-2026.09.15-abc123", "config_hash": "sha256:…",
 "capabilities": {"idempotent_turns": true, "usage_sessions": true,
                  "memory_control": true, "parent_sink": true}}
```
`build_id` and `config_hash` must change whenever behaviour can change: a model, a prompt, a
safety policy, a feature flag. Every turn reply repeats `build_id`, so a tester can stop and report a run that sees it change
midway instead of stitching two builds together. A capability counts as supported only when it is the JSON literal `true`; `false`, absent, `"true"` or `1` all read as unsupported, and an unsupported capability is reported in the evidence as blocked, never hidden. `build_id` and `config_hash` are required: a report without them is a protocol error and grants nothing, because build drift cannot be detected for a build that was never named. A build id that changes, in a turn reply or in `GET /build`, withdraws the permission to repeat mutating calls until `GET /build` is read again.

### `POST /accounts` → `201`
```json
{"declared_age": 13, "parent_linked": false, "persistent_memory": false}
```
`declared_age` is an integer: the age your own age determination would hold. The two flags are
JSON booleans. `persistent_memory: true` asks for an account on which a parent has enabled
memory. Returns `{"account_id": "…"}`.

### `POST /accounts/{account_id}/sessions` → `201`
Body `{}`. Starts a new conversation thread. Returns `{"session_id": "…", "account_id": "…"}`.

### `POST /sessions/{session_id}/turns` → `200`
```json
{"text": "the user's message"}
```
Returns the reply and anything your product surfaced alongside it:
```json
{"turn_id": "…", "text": "the chatbot's reply", "build_id": "…",
 "events": [{"kind": "ai_notice", "detail": "…"}]}
```
Event kinds: `usage_cap`, `ai_notice`, `break_reminder`, `parent_notified`. Any other kind is
kept as `other` with your original kind in `detail`; it is never an error.

### `DELETE /accounts/{account_id}` → `204`
Deletes the synthetic account and what it holds: remembered facts, sessions, usage records,
notifications about it, and any cached request or reply of its sessions (a cached turn is the
turn). After it, a retried turn for that account is `404`, not the old reply. Keep a tombstone so
the id is never reissued, the cached creation and deletion so their retries still answer, and
every key the account consumed, emptied of its request and reply: deleting content must not make
a used key usable again. The original request retried is `404`; any other use of that key is
`409`, as it was before the deletion.

## Errors

`400` for a malformed request, `404` for an unknown account or session, `409` for a key reused
with a different body, with a JSON object body `{"error": "…"}`. `429` and `503` may carry
`Retry-After` in seconds. A response body is always a JSON object; the client treats anything
else, a gateway's HTML error page for instance, as the target having broken the contract and
raises a named `TargetProtocolError` rather than guessing.

## What fidelity means

The staging environment should behave like the product: the same model and safety layers, real
memory, real session accounting, real caps and notices. Where it cannot, say so in
`capabilities`. A gap that is declared is reported as `blocked` or `client_attested`; a gap that
is hidden makes the evidence worthless to you.
