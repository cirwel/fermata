"""Governed local memory.write adapter."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from fermata.runtime_core import (
    anchored_atomic_write,
    ensure_private_directory,
    evaluate_with_adapter,
    is_inside,
    reject,
)
from fermata.runtime_ir import (
    AdapterPreparation,
    ApprovalDecision,
    CommitEvidence,
    EffectResult,
    Intent,
    Proposal,
    RejectionReason,
    Scope,
    Trace,
    now_timestamp,
    sha256_bytes,
)


def memory_store_path(scope: Scope, target: str) -> Path:
    """Return the local v0 memory ledger path for a scoped memory target."""

    target_text = target.strip()
    path_parts = target_text.split("/")
    if (
        not target_text
        or target_text != target
        or target_text.startswith("/")
        or target_text.endswith("/")
        or any(part in {"", ".", ".."} for part in path_parts)
    ):
        raise ValueError("memory_target_outside_scope")

    raw = Path(*path_parts)
    if raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts):
        raise ValueError("memory_target_outside_scope")
    if any(part.endswith(".jsonl") for part in raw.parts):
        raise ValueError("memory_target_reserved_suffix")

    # Resolve only the store root; the ledger subdirectories and ``.jsonl``
    # leaf are left unresolved so a symlink planted at any of those components
    # is not silently followed during path computation. The anchored
    # O_NOFOLLOW walk in prepare/commit is what rejects such symlinks.
    store_root = (scope.sandbox_root / ".fermata-memory").resolve()
    ledger_path = store_root / raw.parent / f"{raw.name}.jsonl"
    if not is_inside(scope.sandbox_root, ledger_path) or not is_inside(
        store_root,
        ledger_path,
    ):
        raise ValueError("memory_target_outside_scope")
    return ledger_path


MEMORY_LIFESPANS = frozenset({"session", "project", "durable"})
MEMORY_RECORD_STRING_FIELDS = frozenset(
    {
        "record_id",
        "target",
        "lifespan",
        "actor",
        "proposal_id",
        "intent_id",
        "trace_id",
        "input_sha256",
        "committed_at",
    }
)


def validate_memory_record(
    record: Any,
    *,
    expected_target: str,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Validate one local memory ledger record before trusting it."""

    if not isinstance(record, dict):
        raise ValueError("memory_record_not_object")
    for field in MEMORY_RECORD_STRING_FIELDS:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"memory_record_{field}_invalid")
    if record["target"] != expected_target:
        raise ValueError("memory_record_target_mismatch")
    version = record.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("memory_record_version_invalid")
    if expected_version is not None and version != expected_version:
        raise ValueError("memory_record_version_sequence_invalid")
    if not isinstance(record.get("content"), str):
        raise ValueError("memory_record_content_invalid")
    if record["input_sha256"] != sha256_bytes(record["content"].encode("utf-8")):
        raise ValueError("memory_record_input_hash_mismatch")
    provenance = record.get("provenance")
    if not isinstance(provenance, list) or not all(
        isinstance(item, str) and item for item in provenance
    ):
        raise ValueError("memory_record_provenance_invalid")
    input_hash = record["input_sha256"]
    if len(input_hash) != 64 or not all(
        char in "0123456789abcdef" for char in input_hash.lower()
    ):
        raise ValueError("memory_record_input_hash_invalid")
    if record["lifespan"] not in MEMORY_LIFESPANS:
        raise ValueError("memory_record_lifespan_invalid")
    return record


class MemoryWriteAdapter:
    """Local governed memory.write adapter."""

    adapter = "memory"
    operation = "write"
    capability = "memory.write"

    def prepare(
        self,
        scope: Scope,
        proposal: Proposal,
        intent: Intent,
        trace: Trace,
    ) -> AdapterPreparation | EffectResult:
        """Validate memory-write intent and build dry-run evidence."""

        try:
            ledger_path = memory_store_path(scope, intent.target)
        except ValueError as exc:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason(str(exc)),
                target=intent.target,
            )

        content = intent.input.get("content")
        if not isinstance(content, str):
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.MEMORY_CONTENT_MISSING_OR_NOT_STRING,
            )

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > scope.max_bytes:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.INPUT_TOO_LARGE,
                bytes=len(content_bytes),
                max_bytes=scope.max_bytes,
            )

        provenance = intent.input.get("provenance", proposal.evidence)
        if not isinstance(provenance, list) or not all(
            isinstance(item, str) and item for item in provenance
        ):
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.MEMORY_PROVENANCE_INVALID,
            )

        lifespan = intent.input.get("lifespan", "session")
        if not isinstance(lifespan, str) or lifespan not in MEMORY_LIFESPANS:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.MEMORY_LIFESPAN_INVALID,
            )

        existing_records: list[dict[str, Any]] = []
        # Read any existing ledger through an O_NOFOLLOW open so a symlink
        # planted at the leaf is refused (ELOOP) rather than followed to an
        # arbitrary file. No directory is created here; prepare stays a dry run.
        try:
            read_fd = os.open(ledger_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            read_fd = None
        except OSError as exc:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.MEMORY_STORE_UNREADABLE,
                error_type=exc.__class__.__name__,
            )
        if read_fd is not None:
            try:
                with os.fdopen(read_fd, "r", encoding="utf-8") as ledger_file:
                    existing_text = ledger_file.read()
                record_number = 0
                for line in existing_text.splitlines():
                    if not line.strip():
                        continue
                    record_number += 1
                    record = validate_memory_record(
                        json.loads(line),
                        expected_target=intent.target,
                        expected_version=record_number,
                    )
                    existing_records.append(record)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                return reject(
                    trace,
                    scope,
                    intent.intent_id,
                    RejectionReason.MEMORY_STORE_UNREADABLE,
                    error_type=exc.__class__.__name__,
                )

        input_hash = sha256_bytes(content_bytes)
        version = len(existing_records) + 1
        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        committed_at = now_timestamp()
        memory_record = {
            "record_id": record_id,
            "version": version,
            "target": intent.target,
            "content": content,
            "lifespan": lifespan,
            "provenance": provenance,
            "actor": proposal.actor,
            "proposal_id": proposal.proposal_id,
            "intent_id": intent.intent_id,
            "trace_id": trace.trace_id,
            "input_sha256": input_hash,
            "committed_at": committed_at,
        }
        try:
            validate_memory_record(
                memory_record,
                expected_target=intent.target,
                expected_version=version,
            )
            record_bytes = (json.dumps(memory_record, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        except (TypeError, ValueError) as exc:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.MEMORY_RECORD_INVALID,
                error_type=exc.__class__.__name__,
            )

        record_hash = sha256_bytes(record_bytes)
        if len(record_bytes) > scope.max_bytes:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.INPUT_TOO_LARGE,
                bytes=len(record_bytes),
                max_bytes=scope.max_bytes,
                measured="memory_record",
            )

        return AdapterPreparation(
            effect_kind=self.capability,
            commit_target=intent.target,
            checks=[
                "capability:memory.write",
                "inside_scope",
                "content_bytes_under_limit",
                "record_bytes_under_limit",
            ],
            dry_run_summary=(
                f"Append memory record {record_id} version {version} "
                f"to {intent.target}"
            ),
            dry_run_fields={"input_sha256": input_hash, "record_sha256": record_hash},
            payload={
                "ledger_path": ledger_path,
                "existing_records": existing_records,
                "memory_record": memory_record,
                "record_bytes": record_bytes,
                "record_hash": record_hash,
                "record_id": record_id,
                "version": version,
                "committed_at": committed_at,
            },
        )

    def commit(
        self,
        scope: Scope,
        proposal: Proposal,
        intent: Intent,
        trace: Trace,
        preparation: AdapterPreparation,
    ) -> CommitEvidence | EffectResult:
        """Commit a prepared local memory record and verify read-back."""

        ledger_path = preparation.payload["ledger_path"]
        existing_records = preparation.payload["existing_records"]
        memory_record = preparation.payload["memory_record"]
        record_bytes = preparation.payload["record_bytes"]
        record_hash = preparation.payload["record_hash"]
        record_id = preparation.payload["record_id"]
        version = preparation.payload["version"]
        committed_at = preparation.payload["committed_at"]

        candidate_records = [*existing_records, memory_record]
        candidate_bytes = b"".join(
            (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
            for record in candidate_records
        )
        memory_store_root = (scope.sandbox_root / ".fermata-memory").resolve()
        ensure_private_directory(ledger_path.parent, root=memory_store_root)

        def _verify_readback(readback: bytes) -> None:
            """Re-validate every read-back record and confirm ours is present."""

            readback_records: list[dict[str, Any]] = []
            record_number = 0
            for line in readback.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                record_number += 1
                readback_records.append(
                    validate_memory_record(
                        json.loads(line),
                        expected_target=intent.target,
                        expected_version=record_number,
                    )
                )
            matched = next(
                (
                    record
                    for record in readback_records
                    if record.get("record_id") == record_id
                    and record.get("version") == version
                ),
                None,
            )
            if matched != memory_record:
                raise ValueError("memory_read_back_mismatch")

        try:
            anchored_atomic_write(
                scope, ledger_path, candidate_bytes, verify=_verify_readback
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            trace.add(
                "adapter.commit.failed",
                error_type=exc.__class__.__name__,
                target=intent.target,
            )
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.ADAPTER_COMMIT_FAILED,
                error_type=exc.__class__.__name__,
            )

        ack = {
            "adapter": "memory",
            "target": intent.target,
            "handle": record_id,
            "record_id": record_id,
            "version": version,
            "sha256": record_hash,
            "bytes": len(record_bytes),
            "store": str(ledger_path),
        }
        verification = {
            "status": "verified",
            "method": "read_back_memory_record",
            "detail": {
                "record_id": record_id,
                "version": version,
                "sha256": record_hash,
            },
        }
        return CommitEvidence(
            acknowledgement=ack,
            verification=verification,
            committed_at=committed_at,
        )


def evaluate_memory_write(
    scope: Scope,
    proposal: Proposal,
    *,
    approval_granted: bool = False,
    approval: ApprovalDecision | None = None,
    _stop_at_approval: bool = False,
) -> tuple[EffectResult, Trace]:
    """Evaluate one governed local memory-write proposal end to end.

    The v0 memory adapter is deliberately boring and credential-free: it appends a
    JSONL record under the scope sandbox, then reads the record back by ID and
    version. A committed memory write means the local memory ledger contains the
    proposed record and the runtime verified its SHA-256 evidence.

    Prefer passing a typed ``ApprovalDecision`` when performer approval is
    required. ``approval_granted`` is retained only for legacy callers.

    When ``_stop_at_approval`` is True, the evaluator runs pure admission,
    verification, and approval phases and stops before any adapter commit —
    returning an ``EffectState.APPROVED`` result whose trace ends at
    ``approval.granted``. The memory ledger is never written. Used by
    ``interpret`` to expose the state-machine spine without world effects.
    """

    return evaluate_with_adapter(
        scope,
        proposal,
        MemoryWriteAdapter(),
        approval_granted=approval_granted,
        approval=approval,
        _stop_at_approval=_stop_at_approval,
    )

def sample_memory_proposal(
    target: str = "project/notes",
    *,
    content: str = "Proposal is not commit; memory writes need provenance.\n",
    provenance: list[str] | None = None,
    lifespan: Any = "project",
) -> Proposal:
    """Build the canonical sample memory-write proposal."""

    proposal_id = "prop_memory_write_001"
    return Proposal(
        proposal_id=proposal_id,
        actor="agent:hermes",
        speech_act="intend",
        reason="persist a governed-effect lesson with provenance",
        confidence=0.81,
        evidence=["issue:#2", "scope:local_memory_sandbox"],
        intent=Intent(
            intent_id="intent_memory_write_001",
            proposal_id=proposal_id,
            adapter="memory",
            operation="write",
            target=target,
            input={
                "content": content,
                "lifespan": lifespan,
                "provenance": (
                    provenance
                    if provenance is not None
                    else ["issue:#2", "golden:memory_write_adapter"]
                ),
            },
            required_capability="memory.write",
        ),
    )


def sample_memory_scope(root: Path, *, approval_required: bool = True) -> Scope:
    """Build the canonical local memory-write scope."""

    return Scope(
        scope_id="local_memory_sandbox",
        sandbox_root=root.resolve(),
        capabilities=frozenset({"memory.write"}),
        approval_required_for=(
            frozenset({"memory.write"}) if approval_required else frozenset()
        ),
    )
