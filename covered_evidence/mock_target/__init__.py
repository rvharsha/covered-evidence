"""The reference Mode B target. Used by every contract, runner, and end-to-end test.

It exhibits the semantics the fidelity checklist requires:
idempotent side effects, persistent versus ephemeral memory, usage sessions
distinct from conversation threads, a parent-notification sink, a build
identity that can change mid-run, and configurable faults in non-restricted
scenarios. It contains no restricted text.
"""
