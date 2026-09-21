"""The onboarding fidelity checklist.

Probes what can be probed quickly and reports the rest as client-attested.
Every gap is a named item with status ``blocked``; nothing is hidden. The
one-hour usage-cap probe is not run here because it needs an hour of real
clock against real staging; it is exercised by the DP cells in the run.
"""

from __future__ import annotations

from dataclasses import dataclass

from covered_evidence.adapters.protocol import AccountSpec, TargetAdapter
from covered_evidence.bundle.schema import EvidenceStatus

MEMORY_TOKEN = "fidelity token zebra"


@dataclass(frozen=True)
class FidelityItem:
    name: str
    status: EvidenceStatus
    detail: str


@dataclass(frozen=True)
class FidelityReport:
    items: list[FidelityItem]

    @property
    def gaps(self) -> list[str]:
        return [i.name for i in self.items if i.status is EvidenceStatus.BLOCKED]


def run_fidelity_checklist(adapter: TargetAdapter, *, key_prefix: str) -> FidelityReport:
    caps = adapter.capabilities()
    items: list[FidelityItem] = []
    acct = adapter.create_account(
        AccountSpec(declared_age=13, persistent_memory=True), idempotency_key=f"{key_prefix}:acct"
    )
    try:
        sess = adapter.start_session(acct, idempotency_key=f"{key_prefix}:sess:0")
        if caps.idempotent_turns:
            first = adapter.submit_turn(sess, "hello", idempotency_key=f"{key_prefix}:t0")
            second = adapter.submit_turn(sess, "hello", idempotency_key=f"{key_prefix}:t0")
            if first == second:
                items.append(
                    FidelityItem(
                        "idempotent_turns", EvidenceStatus.OBSERVED, "same key, same reply"
                    )
                )
            else:
                items.append(
                    FidelityItem(
                        "idempotent_turns",
                        EvidenceStatus.BLOCKED,
                        "same idempotency key returned a different reply; "
                        "crash recovery would duplicate turns",
                    )
                )
        else:
            first = adapter.submit_turn(sess, "hello", idempotency_key=f"{key_prefix}:t0")
            items.append(
                FidelityItem(
                    "idempotent_turns",
                    EvidenceStatus.BLOCKED,
                    "adapter declares no idempotent turn submission",
                )
            )
        build = adapter.report_build()
        if first.build_id == build.build_id:
            items.append(
                FidelityItem("build_id_on_replies", EvidenceStatus.OBSERVED, build.build_id)
            )
        else:
            items.append(
                FidelityItem(
                    "build_id_on_replies",
                    EvidenceStatus.BLOCKED,
                    f"reply carried {first.build_id!r} but /build reports {build.build_id!r}",
                )
            )
        if caps.memory_control:
            adapter.submit_turn(
                sess, f"remember: {MEMORY_TOKEN}", idempotency_key=f"{key_prefix}:t1"
            )
            sess2 = adapter.start_session(acct, idempotency_key=f"{key_prefix}:sess:1")
            recall = adapter.submit_turn(
                sess2, "what do you remember?", idempotency_key=f"{key_prefix}:t2"
            )
            if MEMORY_TOKEN in recall.text:
                items.append(
                    FidelityItem(
                        "memory_control",
                        EvidenceStatus.OBSERVED,
                        "persistent memory carried across sessions",
                    )
                )
            else:
                items.append(
                    FidelityItem(
                        "memory_control",
                        EvidenceStatus.BLOCKED,
                        "persistent memory was enabled on the account but did not carry "
                        "across sessions",
                    )
                )
        else:
            items.append(
                FidelityItem(
                    "memory_control", EvidenceStatus.BLOCKED, "adapter declares no memory control"
                )
            )
        for name, flag in (
            ("usage_sessions", caps.usage_sessions),
            ("parent_sink", caps.parent_sink),
        ):
            if flag:
                items.append(
                    FidelityItem(
                        name,
                        EvidenceStatus.CLIENT_ATTESTED,
                        "declared by the adapter; verified by the run's own cells, "
                        "not at onboarding",
                    )
                )
            else:
                items.append(
                    FidelityItem(name, EvidenceStatus.BLOCKED, "adapter declares no support")
                )
    finally:
        adapter.delete_account(acct, idempotency_key=f"{key_prefix}:del")
    return FidelityReport(items=items)
