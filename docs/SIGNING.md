# Signing and canonical bytes

A bundle's signature lives at `issuance.signature`. It covers the **canonical bytes** of the
bundle with that one field set to `null`. Everything else is signed, including `schema_version`
and `issuance.key_id`.

## The key is authenticated, not just named

The signature string names a key, but that string is the one field outside the signed bytes, so
on its own the name proves nothing. `issuance.key_id` is inside them: `hmac-sha256`, or
`kms-ec-p256-sha256:<key version name>`. A verifier requires the two to agree and reports the
authenticated one. `key_id` is `null` exactly when the bundle is unsigned.

## Canonical bytes (version 0)

1. Serialise the bundle to its JSON object form (`Bundle.to_dict()`): enumerations as their string
   values, absent optionals as `null`, lists in their stored order.
2. Set `issuance.signature` to `null`.
3. Encode as UTF-8 JSON with object keys sorted by Unicode code point at every level, no
   insignificant whitespace (separators `,` and `:`), and non-ASCII characters emitted literally,
   not `\u`-escaped.

In Python this is exactly:

```python
json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
```

This is **not** RFC 8785 (JCS). The known difference is number formatting: a bundle may carry
floating-point values (calibration precision and recall), and Python's shortest-repr float
formatting is what is signed. A verifier in another language must reproduce it. Moving to
RFC 8785, or removing floats from the signed form, is planned before 1.0 and will be a new
canonicalisation version.

## Schemes

Distinguished by prefix. They never cross-verify.

| Prefix | Signature string | Use |
|---|---|---|
| `kms-ec-p256-sha256` | `kms-ec-p256-sha256:<key version name>:<base64 DER ECDSA signature>` | Issuance. ECDSA over P-256 with SHA-256. Verified offline with the key version's PEM public key. The key version name may contain `:`; the signature is everything after the last one. Only the **low-S** form is accepted (`s <= n/2`), because `(r, s)` and `(r, n - s)` both verify and a signature string should identify one signature; signers normalise with `low_s`. A key on any other curve is refused. |
| `hmac-sha256` | `hmac-sha256:<hex>` | Local development, demos and tests. A shared secret proves nothing to a third party. |

A bundle whose signature is `null` is unsigned and never verifies.

## Reading a bundle

Use `Bundle.from_json`. Duplicate object keys are an error (a last-key-wins parser and a human
reader would otherwise see different documents), `NaN` and `Infinity` are errors, every field is
required, unknown fields are errors, and a float field takes a float token (`1.0`, not `1`). A writer
should emit the canonical form; a reader canonicalises what it loaded before it checks the
signature, so `1.0` and `1e0` in a file are the same document, not two. Nothing is defaulted on load.

## Amendments

An issued bundle changes only through `amend`, which re-signs it and appends a record carrying
`supersedes_sha256`, the SHA-256 of the canonical bytes it replaced, and `changes`, a
machine-generated list of what differs. An amendment corrects the record; it never removes what was found or upgrades the evidence. It
may not change identity, scope or methodology; add or remove a planned cell; remove a finding, a
requirement or an open risk; change a requirement's evidence status or a cell's terminal state;
lower a severity or a reproduction count; un-confirm a finding; or mark a finding not observed
without a new build. An amendment that changes nothing is refused, findings are appended and
never reordered, and an existing verification row can be neither removed nor rewritten. The
amending callback works on a copy of its own, so the caller's issued bundle is unchanged
whether the amendment is accepted or refused; every comparison, and the superseded hash, read a
second copy taken after the signature verified. The HTML render prints each amendment's computed
`changes` and `supersedes_sha256` beside the issuer's description, so a reader can check the
description against what happened. What an
amendment MAY still do, each recorded in `changes` (a new verification row only as
`verification`): append findings, requirements, verification rows and change-attribution rows
(an existing attribution, like an existing verification row, can be neither removed nor rewritten);
raise a reproduction count; and change a finding's
excerpt, review disposition and status (to under remediation or risk accepted), a severity upward, a requirement's note, a blocked cell's
reason, and an open risk's text.

## Identifiers

Every id that keys a record must be NFKC-normalised, contain no whitespace, control, format or
combining characters, and use letters of one script. Ids the issuer mints (finding, risk,
amendment) are further restricted to ASCII `[A-Za-z0-9._:/-]+` and are unique ignoring case, so
invisible, compatibility-form, punctuation and other-script lookalikes are all refused there.
What is NOT refused: ids that differ only by similar ASCII characters (a letter `O` for a zero),
and same-script lookalikes in citations and cell ids. An added record is always listed in the
amendment's `changes`; read them. References (`related_findings`, `change_attribution`) must resolve.
