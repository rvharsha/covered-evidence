# Security policy

This project verifies evidence that may be relied on in audits and litigation, and defines a
client that holds a staging credential. We treat the following as security issues:

- a bundle that verifies after its content was changed, or any signature bypass;
- two different bundles with the same canonical bytes;
- the Mode B client sending a bearer token anywhere other than the validated staging host
  (redirects, downgrade to plain HTTP, host confusion);
- evaluator-only data (age band, scenario, rung) recoverable from anything sent to a target;
- a way to make the client repeat a non-idempotent call.

**Please report privately** through GitHub's "Report a vulnerability" on this repository, not
in a public issue. Include a minimal reproduction. We aim to acknowledge within three working
days. Do not include restricted-category content in a report; describe it instead.

Supported versions: the latest release only, until 1.0.
