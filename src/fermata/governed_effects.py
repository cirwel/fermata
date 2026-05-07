"""Governed effect runtime primitives for v0 file and memory adapters.

The module is intentionally small: one scope type, one proposal/intent shape,
two local adapters, and enough trace evidence to make "committed" a runtime fact
rather than an agent claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal


SCHEMA_VERSION = "0.1"


class EffectState(str, Enum):
    PROPOSAL = "proposal"
    INTENT = "intent"
    ADMISSIBLE = "admissible"
    VERIFIED = "verified"
    APPROVED = "approved"
    COMMITTED = "committed"
    REJECTED = "rejected"
    PAUSED = "paused"


SpeechAct = Literal["need", "claim", "doubt", "intend", "remember", "boundary"]


@dataclass(frozen=True)
class Scope:
    """Human-authored runtime boundary."""

    scope_id: str
    sandbox_root: Path
    capabilities: frozenset[str]
    approval_required_for: frozenset[str] = field(default_factory=frozenset)
    max_bytes: int = 4096


@dataclass(frozen=True)
class Intent:
    """Typed effect shape emitted by an agent proposal."""

    intent_id: str
    proposal_id: str
    adapter: str
    operation: str
    target: str
    input: dict[str, Any]
    required_capability: str


@dataclass(frozen=True)
class Proposal:
    """Agent-authored public speech act."""

    proposal_id: str
    actor: str
    speech_act: SpeechAct
    reason: str | None
    confidence: float | None
    evidence: list[str]
    intent: Intent | None = None


@dataclass
class Trace:
    """Append-only runtime trace."""

    trace_id: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def add(self, event_type: str, **fields: Any) -> None:
        """Append an event with a real runtime timestamp."""

        self.events.append({"type": event_type, "at": now_timestamp(), **fields})

    def to_record(self) -> dict[str, Any]:
        """Return the canonical JSON-Schema trace record."""

        return {
            "schema_version": SCHEMA_VERSION,
            "record_type": "trace",
            "trace_id": self.trace_id,
            "events": to_jsonable(self.events),
        }


@dataclass(frozen=True)
class EffectResult:
    """Final state returned by the evaluator."""

    state: EffectState
    trace_id: str
    effect_id: str
    intent_id: str | None
    scope_id: str
    acknowledgement: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    rejection_reason: str | None = None
    required_input: str | None = None
    committed_at: str | None = None

    def to_record(self) -> dict[str, Any]:
        """Return the canonical JSON-Schema effect record."""

        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "effect",
            "effect_id": self.effect_id,
            "state": self.state.value,
            "scope_id": self.scope_id,
            "trace_id": self.trace_id,
        }
        optional_fields = {
            "intent_id": self.intent_id,
            "acknowledgement": self.acknowledgement,
            "verification": self.verification,
            "rejection_reason": self.rejection_reason,
            "required_input": self.required_input,
            "committed_at": self.committed_at,
        }
        for key, value in optional_fields.items():
            if value is not None:
                record[key] = to_jsonable(value)
        return record


def now_timestamp() -> str:
    """Return a current UTC timestamp in JSON Schema date-time format."""

    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_bytes(data: bytes) -> str:
    """Return a SHA-256 hex digest for bytes."""

    return hashlib.sha256(data).hexdigest()


def normalize_target(scope: Scope, target: str) -> Path:
    """Resolve target relative to the scope sandbox."""

    raw = Path(target)
    if raw.is_absolute():
        return raw.resolve()
    return (scope.sandbox_root / raw).resolve()


def is_inside(parent: Path, child: Path) -> bool:
    """Return true if child is inside parent after resolution."""

    try:
        child.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def ensure_private_directory(path: Path, *, root: Path) -> None:
    """Create an internal adapter directory tree with owner read/write/search."""

    path.mkdir(parents=True, exist_ok=True)
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and not is_inside(resolved_root, resolved_path):
        raise ValueError("directory_outside_private_root")

    current = resolved_root
    os.chmod(current, 0o700)
    if resolved_path == resolved_root:
        return
    for part in resolved_path.relative_to(resolved_root).parts:
        current = current / part
        os.chmod(current, 0o700)


def reject(
    trace: Trace,
    scope: Scope,
    intent_id: str | None,
    reason: str,
    **fields: Any,
) -> EffectResult:
    """Emit a rejection result."""

    trace.add("effect.rejected", reason=reason, **fields)
    return EffectResult(
        state=EffectState.REJECTED,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=intent_id,
        scope_id=scope.scope_id,
        rejection_reason=reason,
    )


def pause(
    trace: Trace,
    scope: Scope,
    intent_id: str,
    required_input: str,
    **fields: Any,
) -> EffectResult:
    """Emit a pause result."""

    trace.add("effect.paused", required_input=required_input, **fields)
    return EffectResult(
        state=EffectState.PAUSED,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=intent_id,
        scope_id=scope.scope_id,
        required_input=required_input,
    )


def evaluate_file_write(
    scope: Scope,
    proposal: Proposal,
    *,
    approval_granted: bool = False,
    _stop_at_approval: bool = False,
) -> tuple[EffectResult, Trace]:
    """Evaluate one governed file-write proposal end to end.

    When ``_stop_at_approval`` is True, the evaluator runs pure admission,
    verification, and approval phases and stops before any adapter commit —
    returning an ``EffectState.APPROVED`` result whose trace ends at
    ``approval.granted``. The filesystem is never touched. Used by
    ``interpret`` to expose the state-machine spine without world effects.
    """

    trace = Trace(trace_id=f"trace_{uuid.uuid4().hex[:8]}")
    trace.add(
        "proposal.received",
        proposal_id=proposal.proposal_id,
        actor=proposal.actor,
        speech_act=proposal.speech_act,
        confidence=proposal.confidence,
    )

    if proposal.speech_act != "intend" or proposal.intent is None:
        return reject(trace, scope, None, "proposal_is_not_an_intent"), trace

    intent = proposal.intent
    trace.add(
        "intent.created",
        intent_id=intent.intent_id,
        adapter=intent.adapter,
        operation=intent.operation,
        target=intent.target,
    )

    if intent.adapter != "file" or intent.operation != "write":
        return reject(trace, scope, intent.intent_id, "unsupported_adapter_operation"), trace

    operation_capability = "file.write"
    if intent.required_capability != operation_capability:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "unsupported_capability_for_operation",
            declared_capability=intent.required_capability,
            required_capability=operation_capability,
        ), trace

    if operation_capability not in scope.capabilities:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "missing_capability",
            required_capability=operation_capability,
        ), trace

    if not isinstance(intent.target, str):
        return reject(
            trace,
            scope,
            intent.intent_id,
            "target_missing_or_not_string",
        ), trace

    if not isinstance(intent.input, dict):
        return reject(
            trace,
            scope,
            intent.intent_id,
            "input_missing_or_not_object",
        ), trace

    target_path = normalize_target(scope, intent.target)
    if not is_inside(scope.sandbox_root, target_path):
        return reject(
            trace,
            scope,
            intent.intent_id,
            "path_outside_scope",
            target=str(target_path),
            sandbox_root=str(scope.sandbox_root),
        ), trace

    raw_target = Path(intent.target)
    candidate_path = (
        raw_target if raw_target.is_absolute() else scope.sandbox_root / raw_target
    )
    sandbox_root_resolved = scope.sandbox_root.resolve()
    walker = candidate_path
    visited: set[Path] = set()
    while walker not in visited:
        visited.add(walker)
        if walker.is_symlink():
            reason = (
                "target_is_symlink"
                if walker == candidate_path
                else "path_component_is_symlink"
            )
            return reject(
                trace,
                scope,
                intent.intent_id,
                reason,
                symlink_path=str(walker),
            ), trace
        if walker == walker.parent:
            break
        walker = walker.parent
        try:
            if walker.resolve() == sandbox_root_resolved:
                break
        except OSError:
            break

    content = intent.input.get("content")
    if not isinstance(content, str):
        return reject(
            trace,
            scope,
            intent.intent_id,
            "content_missing_or_not_string",
        ), trace

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > scope.max_bytes:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "input_too_large",
            bytes=len(content_bytes),
            max_bytes=scope.max_bytes,
        ), trace

    if target_path.exists() and target_path.is_dir():
        return reject(
            trace,
            scope,
            intent.intent_id,
            "target_is_directory",
            target=str(target_path),
        ), trace

    overwrite_requested = bool(intent.input.get("overwrite"))
    if target_path.exists() and not target_path.is_dir() and not overwrite_requested:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "target_exists_no_overwrite",
            target=str(target_path),
        ), trace

    input_hash = sha256_bytes(content_bytes)
    trace.add(
        "policy.checked",
        result="allowed",
        checks=["capability:file.write", "inside_scope", "bytes_under_limit"],
    )
    trace.add(
        "dry_run.rendered",
        summary=f"Write {len(content_bytes)} bytes to {target_path}",
        input_sha256=input_hash,
    )

    if "file.write" in scope.approval_required_for and not approval_granted:
        trace.add("approval.requested", authority="human", effect_kind="file.write")
        return pause(
            trace,
            scope,
            intent.intent_id,
            "human_approval",
            reason="approval_required_before_commit",
        ), trace

    trace.add("approval.granted", authority="human" if approval_granted else "runtime")

    if _stop_at_approval:
        return EffectResult(
            state=EffectState.APPROVED,
            trace_id=trace.trace_id,
            effect_id=f"effect_{uuid.uuid4().hex[:8]}",
            intent_id=intent.intent_id,
            scope_id=scope.scope_id,
        ), trace

    trace.add("adapter.commit.started", adapter="file", target=str(target_path))

    temp_path: Path | None = None
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as temp_file:
            os.fchmod(temp_file.fileno(), 0o600)
            temp_file.write(content_bytes)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        readback = temp_path.read_bytes()
        output_hash = sha256_bytes(readback)
        if output_hash != input_hash:
            raise ValueError("read_back_hash_mismatch")
        temp_path.replace(target_path)
    except (OSError, ValueError) as exc:
        trace.add(
            "adapter.commit.failed",
            error_type=exc.__class__.__name__,
            target=str(target_path),
        )
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                trace.add("adapter.temp_cleanup.failed", target=str(temp_path))
        return reject(
            trace,
            scope,
            intent.intent_id,
            "adapter_commit_failed",
            error_type=exc.__class__.__name__,
        ), trace

    try:
        parent_fd = os.open(target_path.parent, os.O_DIRECTORY)
    except OSError:
        pass
    else:
        try:
            os.fsync(parent_fd)
        except OSError:
            pass
        finally:
            os.close(parent_fd)

    try:
        final_bytes = target_path.read_bytes()
    except OSError as exc:
        trace.add(
            "verification.failed",
            error_type=exc.__class__.__name__,
            target=str(target_path),
        )
        return reject(
            trace,
            scope,
            intent.intent_id,
            "verification_read_failed",
            error_type=exc.__class__.__name__,
        ), trace

    final_hash = sha256_bytes(final_bytes)
    if final_hash != input_hash:
        trace.add(
            "verification.failed",
            target=str(target_path),
            input_sha256=input_hash,
            target_sha256=final_hash,
        )
        return reject(
            trace,
            scope,
            intent.intent_id,
            "verification_failed_post_commit",
            input_sha256=input_hash,
            target_sha256=final_hash,
        ), trace

    ack = {
        "adapter": "file",
        "target": str(target_path),
        "handle": str(target_path),
        "sha256": final_hash,
        "bytes": len(final_bytes),
    }
    verification = {
        "status": "verified",
        "method": "post_rename_read_back_sha256",
        "detail": {"sha256": final_hash, "bytes": len(final_bytes)},
    }
    committed_at = now_timestamp()
    trace.add(
        "effect.committed",
        acknowledgement=ack,
        verification=verification,
        committed_at=committed_at,
    )

    return EffectResult(
        state=EffectState.COMMITTED,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=intent.intent_id,
        scope_id=scope.scope_id,
        acknowledgement=ack,
        verification=verification,
        committed_at=committed_at,
    ), trace


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

    store_root = scope.sandbox_root / ".fermata-memory"
    ledger_path = store_root / raw.parent / f"{raw.name}.jsonl"
    resolved_store_root = store_root.resolve()
    resolved = ledger_path.resolve()
    if not is_inside(scope.sandbox_root, resolved) or not is_inside(
        resolved_store_root,
        resolved,
    ):
        raise ValueError("memory_target_outside_scope")
    return resolved


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


def evaluate_memory_write(
    scope: Scope,
    proposal: Proposal,
    *,
    approval_granted: bool = False,
    _stop_at_approval: bool = False,
) -> tuple[EffectResult, Trace]:
    """Evaluate one governed local memory-write proposal end to end.

    The v0 memory adapter is deliberately boring and credential-free: it appends a
    JSONL record under the scope sandbox, then reads the record back by ID and
    version. A committed memory write means the local memory ledger contains the
    proposed record and the runtime verified its SHA-256 evidence.

    When ``_stop_at_approval`` is True, the evaluator runs pure admission,
    verification, and approval phases and stops before any adapter commit —
    returning an ``EffectState.APPROVED`` result whose trace ends at
    ``approval.granted``. The memory ledger is never written. Used by
    ``interpret`` to expose the state-machine spine without world effects.
    """

    trace = Trace(trace_id=f"trace_{uuid.uuid4().hex[:8]}")
    trace.add(
        "proposal.received",
        proposal_id=proposal.proposal_id,
        actor=proposal.actor,
        speech_act=proposal.speech_act,
        confidence=proposal.confidence,
    )

    if proposal.speech_act != "intend" or proposal.intent is None:
        return reject(trace, scope, None, "proposal_is_not_an_intent"), trace

    intent = proposal.intent
    trace.add(
        "intent.created",
        intent_id=intent.intent_id,
        adapter=intent.adapter,
        operation=intent.operation,
        target=intent.target,
    )

    if intent.adapter != "memory" or intent.operation != "write":
        return reject(trace, scope, intent.intent_id, "unsupported_adapter_operation"), trace

    operation_capability = "memory.write"
    if intent.required_capability != operation_capability:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "unsupported_capability_for_operation",
            declared_capability=intent.required_capability,
            required_capability=operation_capability,
        ), trace

    if operation_capability not in scope.capabilities:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "missing_capability",
            required_capability=operation_capability,
        ), trace

    if not isinstance(intent.target, str):
        return reject(
            trace,
            scope,
            intent.intent_id,
            "target_missing_or_not_string",
        ), trace

    if not isinstance(intent.input, dict):
        return reject(
            trace,
            scope,
            intent.intent_id,
            "input_missing_or_not_object",
        ), trace

    try:
        ledger_path = memory_store_path(scope, intent.target)
    except ValueError as exc:
        return reject(trace, scope, intent.intent_id, str(exc), target=intent.target), trace

    content = intent.input.get("content")
    if not isinstance(content, str):
        return reject(
            trace,
            scope,
            intent.intent_id,
            "memory_content_missing_or_not_string",
        ), trace

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > scope.max_bytes:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "input_too_large",
            bytes=len(content_bytes),
            max_bytes=scope.max_bytes,
        ), trace

    provenance = intent.input.get("provenance", proposal.evidence)
    if not isinstance(provenance, list) or not all(
        isinstance(item, str) and item for item in provenance
    ):
        return reject(trace, scope, intent.intent_id, "memory_provenance_invalid"), trace

    lifespan = intent.input.get("lifespan", "session")
    if not isinstance(lifespan, str) or lifespan not in MEMORY_LIFESPANS:
        return reject(trace, scope, intent.intent_id, "memory_lifespan_invalid"), trace

    existing_records: list[dict[str, Any]] = []
    if ledger_path.exists():
        try:
            record_number = 0
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
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
                "memory_store_unreadable",
                error_type=exc.__class__.__name__,
            ), trace

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
            "memory_record_invalid",
            error_type=exc.__class__.__name__,
        ), trace
    record_hash = sha256_bytes(record_bytes)
    if len(record_bytes) > scope.max_bytes:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "input_too_large",
            bytes=len(record_bytes),
            max_bytes=scope.max_bytes,
            measured="memory_record",
        ), trace

    trace.add(
        "policy.checked",
        result="allowed",
        checks=[
            "capability:memory.write",
            "inside_scope",
            "content_bytes_under_limit",
            "record_bytes_under_limit",
        ],
    )
    trace.add(
        "dry_run.rendered",
        summary=f"Append memory record {record_id} version {version} to {intent.target}",
        input_sha256=input_hash,
        record_sha256=record_hash,
    )

    if "memory.write" in scope.approval_required_for and not approval_granted:
        trace.add("approval.requested", authority="human", effect_kind="memory.write")
        return pause(
            trace,
            scope,
            intent.intent_id,
            "human_approval",
            reason="approval_required_before_commit",
        ), trace

    trace.add("approval.granted", authority="human" if approval_granted else "runtime")

    if _stop_at_approval:
        return EffectResult(
            state=EffectState.APPROVED,
            trace_id=trace.trace_id,
            effect_id=f"effect_{uuid.uuid4().hex[:8]}",
            intent_id=intent.intent_id,
            scope_id=scope.scope_id,
        ), trace

    trace.add("adapter.commit.started", adapter="memory", target=intent.target)

    candidate_records = [*existing_records, memory_record]
    candidate_bytes = b"".join(
        (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        for record in candidate_records
    )
    temp_path = ledger_path.with_name(f".{ledger_path.name}.{uuid.uuid4().hex}.tmp")
    replaced = False
    try:
        memory_store_root = (scope.sandbox_root / ".fermata-memory").resolve()
        ensure_private_directory(ledger_path.parent, root=memory_store_root)
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as temp_ledger:
            os.fchmod(temp_ledger.fileno(), 0o600)
            temp_ledger.write(candidate_bytes)
            temp_ledger.flush()
            os.fsync(temp_ledger.fileno())

        readback_records: list[dict[str, Any]] = []
        record_number = 0
        for line in temp_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record_number += 1
            record = validate_memory_record(
                json.loads(line),
                expected_target=intent.target,
                expected_version=record_number,
            )
            readback_records.append(record)

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

        os.replace(temp_path, ledger_path)
        replaced = True
        try:
            dir_fd = os.open(ledger_path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            trace.add(
                "adapter.directory_fsync.failed",
                error_type=exc.__class__.__name__,
                target=intent.target,
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        if not replaced:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        trace.add(
            "adapter.commit.failed",
            error_type=exc.__class__.__name__,
            target=intent.target,
        )
        return reject(
            trace,
            scope,
            intent.intent_id,
            "adapter_commit_failed",
            error_type=exc.__class__.__name__,
        ), trace

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
        "detail": {"record_id": record_id, "version": version, "sha256": record_hash},
    }
    trace.add(
        "effect.committed",
        acknowledgement=ack,
        verification=verification,
        committed_at=committed_at,
    )

    return EffectResult(
        state=EffectState.COMMITTED,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=intent.intent_id,
        scope_id=scope.scope_id,
        acknowledgement=ack,
        verification=verification,
        committed_at=committed_at,
    ), trace


def interpret(
    scope: Scope,
    proposal: Proposal,
    *,
    approval_granted: bool = False,
) -> tuple[EffectResult, Trace]:
    """Run a proposal through the governed-effect state machine without committing.

    Returns an ``EffectResult`` in one of three terminal-for-pure-eval states:

    - ``REJECTED`` — the proposal failed admission, verification, or shape checks;
    - ``PAUSED`` — the proposal reached approval but approval was required and not
      granted; the runtime needs human input before proceeding;
    - ``APPROVED`` — the proposal cleared all pure-eval phases and would commit on
      the next call to a real adapter; no external effect has occurred.

    No adapter commit is performed. No file is written, no memory ledger is
    appended, no network is called. The trace stops at ``approval.granted`` (or
    earlier on rejection / pause). To actually commit, call the public
    adapter-specific entry point (``evaluate_file_write``, ``evaluate_memory_write``)
    with ``approval_granted=True``.

    The interpreter dispatches by ``intent.adapter``. Unsupported adapters are
    rejected with reason ``unsupported_adapter_for_interpret``; this is distinct
    from ``unsupported_adapter_operation`` returned by adapter-specific evaluators
    when called with the wrong adapter.
    """

    if proposal.speech_act != "intend" or proposal.intent is None:
        trace = Trace(trace_id=f"trace_{uuid.uuid4().hex[:8]}")
        trace.add(
            "proposal.received",
            proposal_id=proposal.proposal_id,
            actor=proposal.actor,
            speech_act=proposal.speech_act,
            confidence=proposal.confidence,
        )
        return reject(trace, scope, None, "proposal_is_not_an_intent"), trace

    intent = proposal.intent
    if intent.adapter == "file" and intent.operation == "write":
        return evaluate_file_write(
            scope,
            proposal,
            approval_granted=approval_granted,
            _stop_at_approval=True,
        )
    if intent.adapter == "memory" and intent.operation == "write":
        return evaluate_memory_write(
            scope,
            proposal,
            approval_granted=approval_granted,
            _stop_at_approval=True,
        )

    trace = Trace(trace_id=f"trace_{uuid.uuid4().hex[:8]}")
    trace.add(
        "proposal.received",
        proposal_id=proposal.proposal_id,
        actor=proposal.actor,
        speech_act=proposal.speech_act,
        confidence=proposal.confidence,
    )
    trace.add(
        "intent.created",
        intent_id=intent.intent_id,
        adapter=intent.adapter,
        operation=intent.operation,
        target=intent.target,
    )
    return reject(
        trace,
        scope,
        intent.intent_id,
        "unsupported_adapter_for_interpret",
        adapter=intent.adapter,
        operation=intent.operation,
    ), trace


def sample_proposal(target: str = "charter-note.txt") -> Proposal:
    """Build the canonical sample file-write proposal."""

    proposal_id = "prop_file_write_001"
    return Proposal(
        proposal_id=proposal_id,
        actor="agent:hermes",
        speech_act="intend",
        reason="record the charter chorus for the next kata",
        confidence=0.82,
        evidence=["user:proceed", "scope:charter_note_sandbox"],
        intent=Intent(
            intent_id="intent_file_write_001",
            proposal_id=proposal_id,
            adapter="file",
            operation="write",
            target=target,
            input={
                "content": "Agents may propose; only governed effects may commit.\n"
            },
            required_capability="file.write",
        ),
    )


def sample_scope(root: Path, *, approval_required: bool = True) -> Scope:
    """Build the canonical sample human-authored scope."""

    return Scope(
        scope_id="charter_note_sandbox",
        sandbox_root=root.resolve(),
        capabilities=frozenset({"file.read", "file.write"}),
        approval_required_for=(
            frozenset({"file.write"}) if approval_required else frozenset()
        ),
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


def to_jsonable(value: Any) -> Any:
    """Convert dataclasses/enums/paths into JSON-safe values."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (frozenset, set, tuple)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def run_self_tests() -> dict[str, Any]:
    """Run acceptance checks for the file-write adapter."""

    results: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="governed_effect_") as tmp:
        root = Path(tmp) / "sandbox"

        non_intent, non_intent_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_claim_001",
                actor="agent:hermes",
                speech_act="claim",
                reason="not an effect intent",
                confidence=0.7,
                evidence=[],
            ),
            approval_granted=True,
        )
        assert non_intent.state == EffectState.REJECTED
        assert non_intent.intent_id is None
        assert non_intent.rejection_reason == "proposal_is_not_an_intent"
        assert "adapter.commit.started" not in [
            event["type"] for event in non_intent_trace.events
        ]
        results["non_intent_rejected"] = non_intent.to_record()
        results["non_intent_trace"] = non_intent_trace.to_record()

        bad_content_proposal = Proposal(
            proposal_id="prop_bad_content_001",
            actor="agent:hermes",
            speech_act="intend",
            reason="malformed content should not reach the adapter",
            confidence=0.71,
            evidence=[],
            intent=Intent(
                intent_id="intent_bad_content_001",
                proposal_id="prop_bad_content_001",
                adapter="file",
                operation="write",
                target="bad-content.txt",
                input={},
                required_capability="file.write",
            ),
        )
        bad_content, bad_content_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            bad_content_proposal,
            approval_granted=True,
        )
        assert bad_content.state == EffectState.REJECTED
        assert bad_content.rejection_reason == "content_missing_or_not_string"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_content_trace.events
        ]
        results["content_missing_rejected"] = bad_content.to_record()
        results["content_missing_trace"] = bad_content_trace.to_record()

        directory_target = root / "already-a-directory"
        directory_target.mkdir(parents=True)
        directory_result, directory_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("already-a-directory"),
            approval_granted=True,
        )
        assert directory_result.state == EffectState.REJECTED
        assert directory_result.rejection_reason == "target_is_directory"
        assert "adapter.commit.started" not in [
            event["type"] for event in directory_trace.events
        ]
        assert not list(root.glob(".already-a-directory.*.tmp"))
        results["directory_target_rejected"] = directory_result.to_record()
        results["directory_target_trace"] = directory_trace.to_record()

        blocked_parent = root / "blocked-parent"
        blocked_parent.write_text("not a directory")
        adapter_error, adapter_error_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("blocked-parent/file.txt"),
            approval_granted=True,
        )
        assert adapter_error.state == EffectState.REJECTED
        assert adapter_error.rejection_reason == "adapter_commit_failed"
        adapter_error_events = [event["type"] for event in adapter_error_trace.events]
        assert "adapter.commit.started" in adapter_error_events
        assert "adapter.commit.failed" in adapter_error_events
        results["adapter_error_rejected"] = adapter_error.to_record()
        results["adapter_error_trace"] = adapter_error_trace.to_record()

        committed, committed_trace = evaluate_file_write(
            sample_scope(root, approval_required=True),
            sample_proposal(),
            approval_granted=True,
        )
        assert committed.state == EffectState.COMMITTED
        assert committed.acknowledgement is not None
        target = Path(committed.acknowledgement["target"])
        assert target.exists()
        assert committed.verification is not None
        assert committed.verification["status"] == "verified"
        assert committed.committed_at is not None
        results["allowed_write_commits"] = committed.to_record()
        results["allowed_write_trace"] = committed_trace.to_record()
        results["allowed_write_trace_events"] = [
            event["type"] for event in committed_trace.events
        ]

        old_umask = os.umask(0o444)
        try:
            restrictive_file, restrictive_file_trace = evaluate_file_write(
                sample_scope(root, approval_required=False),
                sample_proposal("restrictive-umask-file.txt"),
                approval_granted=True,
            )
        finally:
            os.umask(old_umask)
        assert restrictive_file.state == EffectState.COMMITTED
        restrictive_file_target = Path(restrictive_file.acknowledgement["target"])
        assert restrictive_file_target.read_text(encoding="utf-8") == (
            "Agents may propose; only governed effects may commit.\n"
        )
        assert "adapter.commit.failed" not in [
            event["type"] for event in restrictive_file_trace.events
        ]
        results["restrictive_umask_file_write_commits_verified"] = (
            restrictive_file.to_record()
        )
        results["restrictive_umask_file_write_trace"] = restrictive_file_trace.to_record()

        escaped, escaped_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("../outside-scope.txt"),
            approval_granted=True,
        )
        assert escaped.state == EffectState.REJECTED
        assert escaped.rejection_reason == "path_outside_scope"
        assert "adapter.commit.started" not in [
            event["type"] for event in escaped_trace.events
        ]
        results["path_escape_rejected"] = escaped.to_record()
        results["path_escape_trace"] = escaped_trace.to_record()

        no_cap_scope = Scope(
            scope_id="no_write_scope",
            sandbox_root=root.resolve(),
            capabilities=frozenset({"file.read"}),
            approval_required_for=frozenset(),
        )
        no_cap, no_cap_trace = evaluate_file_write(
            no_cap_scope,
            sample_proposal(),
            approval_granted=True,
        )
        assert no_cap.state == EffectState.REJECTED
        assert no_cap.rejection_reason == "missing_capability"
        assert "adapter.commit.started" not in [
            event["type"] for event in no_cap_trace.events
        ]
        results["missing_capability_rejected"] = no_cap.to_record()
        results["missing_capability_trace"] = no_cap_trace.to_record()

        spoofed_file_proposal = Proposal(
            proposal_id="prop_file_spoof_001",
            actor="agent:hermes",
            speech_act="intend",
            reason="adapter operation should derive its own capability",
            confidence=0.68,
            evidence=[],
            intent=Intent(
                intent_id="intent_file_spoof_001",
                proposal_id="prop_file_spoof_001",
                adapter="file",
                operation="write",
                target="spoofed-capability.txt",
                input={"content": "should not commit\n"},
                required_capability="memory.write",
            ),
        )
        spoofed_file, spoofed_file_trace = evaluate_file_write(
            Scope(
                scope_id="memory_only_scope",
                sandbox_root=root.resolve(),
                capabilities=frozenset({"memory.write"}),
                approval_required_for=frozenset(),
            ),
            spoofed_file_proposal,
            approval_granted=True,
        )
        assert spoofed_file.state == EffectState.REJECTED
        assert spoofed_file.rejection_reason == "unsupported_capability_for_operation"
        assert "adapter.commit.started" not in [
            event["type"] for event in spoofed_file_trace.events
        ]
        assert not (root / "spoofed-capability.txt").exists()
        results["capability_spoof_rejected"] = spoofed_file.to_record()
        results["capability_spoof_trace"] = spoofed_file_trace.to_record()

        bad_file_target, bad_file_target_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_file_bad_target_001",
                actor="agent:hermes",
                speech_act="intend",
                reason="malformed target should reject under governance",
                confidence=0.66,
                evidence=[],
                intent=Intent(
                    intent_id="intent_file_bad_target_001",
                    proposal_id="prop_file_bad_target_001",
                    adapter="file",
                    operation="write",
                    target=123,
                    input={"content": "should not commit\n"},
                    required_capability="file.write",
                ),
            ),
            approval_granted=True,
        )
        assert bad_file_target.state == EffectState.REJECTED
        assert bad_file_target.rejection_reason == "target_missing_or_not_string"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_file_target_trace.events
        ]
        results["target_not_string_rejected"] = bad_file_target.to_record()
        results["target_not_string_trace"] = bad_file_target_trace.to_record()

        bad_file_input, bad_file_input_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_file_bad_input_001",
                actor="agent:hermes",
                speech_act="intend",
                reason="malformed input should reject under governance",
                confidence=0.65,
                evidence=[],
                intent=Intent(
                    intent_id="intent_file_bad_input_001",
                    proposal_id="prop_file_bad_input_001",
                    adapter="file",
                    operation="write",
                    target="bad-input.txt",
                    input=None,
                    required_capability="file.write",
                ),
            ),
            approval_granted=True,
        )
        assert bad_file_input.state == EffectState.REJECTED
        assert bad_file_input.rejection_reason == "input_missing_or_not_object"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_file_input_trace.events
        ]
        assert not (root / "bad-input.txt").exists()
        results["input_not_object_rejected"] = bad_file_input.to_record()
        results["input_not_object_trace"] = bad_file_input_trace.to_record()

        paused, paused_trace = evaluate_file_write(
            sample_scope(root, approval_required=True),
            sample_proposal("needs-approval.txt"),
            approval_granted=False,
        )
        assert paused.state == EffectState.PAUSED
        assert paused.required_input == "human_approval"
        assert "adapter.commit.started" not in [
            event["type"] for event in paused_trace.events
        ]
        assert not (root / "needs-approval.txt").exists()
        results["approval_required_pauses"] = paused.to_record()
        results["approval_required_trace"] = paused_trace.to_record()

        symlink_target = root / "symlink-at-target.txt"
        symlink_decoy = root / "decoy-target.txt"
        symlink_decoy.write_text("decoy")
        os.symlink(symlink_decoy, symlink_target)
        symlink_at_target, symlink_at_target_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("symlink-at-target.txt"),
            approval_granted=True,
        )
        assert symlink_at_target.state == EffectState.REJECTED
        assert symlink_at_target.rejection_reason == "target_is_symlink"
        assert "adapter.commit.started" not in [
            event["type"] for event in symlink_at_target_trace.events
        ]
        assert symlink_decoy.read_text() == "decoy"
        results["target_is_symlink_rejected"] = symlink_at_target.to_record()
        results["target_is_symlink_trace"] = symlink_at_target_trace.to_record()

        symlink_dir_real = root / "real-subdir"
        symlink_dir_real.mkdir()
        symlink_dir_alias = root / "aliased-subdir"
        os.symlink(symlink_dir_real, symlink_dir_alias)
        path_component_link, path_component_link_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("aliased-subdir/inside.txt"),
            approval_granted=True,
        )
        assert path_component_link.state == EffectState.REJECTED
        assert path_component_link.rejection_reason == "path_component_is_symlink"
        assert "adapter.commit.started" not in [
            event["type"] for event in path_component_link_trace.events
        ]
        assert not (symlink_dir_real / "inside.txt").exists()
        results["path_component_is_symlink_rejected"] = path_component_link.to_record()
        results["path_component_is_symlink_trace"] = path_component_link_trace.to_record()

        existing_target = root / "existing-target.txt"
        existing_target.write_text("original content\n")
        original_bytes = existing_target.read_bytes()
        no_overwrite, no_overwrite_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("existing-target.txt"),
            approval_granted=True,
        )
        assert no_overwrite.state == EffectState.REJECTED
        assert no_overwrite.rejection_reason == "target_exists_no_overwrite"
        assert "adapter.commit.started" not in [
            event["type"] for event in no_overwrite_trace.events
        ]
        assert existing_target.read_bytes() == original_bytes
        results["target_exists_no_overwrite_rejected"] = no_overwrite.to_record()
        results["target_exists_no_overwrite_trace"] = no_overwrite_trace.to_record()

        overwrite_proposal = sample_proposal("existing-target.txt")
        assert overwrite_proposal.intent is not None
        overwrite_proposal = Proposal(
            proposal_id=overwrite_proposal.proposal_id,
            actor=overwrite_proposal.actor,
            speech_act=overwrite_proposal.speech_act,
            reason=overwrite_proposal.reason,
            confidence=overwrite_proposal.confidence,
            evidence=overwrite_proposal.evidence,
            intent=Intent(
                intent_id=overwrite_proposal.intent.intent_id,
                proposal_id=overwrite_proposal.intent.proposal_id,
                adapter=overwrite_proposal.intent.adapter,
                operation=overwrite_proposal.intent.operation,
                target=overwrite_proposal.intent.target,
                input={**overwrite_proposal.intent.input, "overwrite": True},
                required_capability=overwrite_proposal.intent.required_capability,
            ),
        )
        overwrote, overwrote_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            overwrite_proposal,
            approval_granted=True,
        )
        assert overwrote.state == EffectState.COMMITTED
        assert overwrote.acknowledgement is not None
        assert existing_target.read_text(encoding="utf-8") == (
            "Agents may propose; only governed effects may commit.\n"
        )
        assert "effect.committed" in [
            event["type"] for event in overwrote_trace.events
        ]
        results["target_exists_with_overwrite_commits"] = overwrote.to_record()
        results["target_exists_with_overwrite_trace"] = overwrote_trace.to_record()

        memory_committed, memory_committed_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=True),
            sample_memory_proposal(),
            approval_granted=True,
        )
        assert memory_committed.state == EffectState.COMMITTED
        assert memory_committed.acknowledgement is not None
        assert memory_committed.acknowledgement["adapter"] == "memory"
        assert memory_committed.acknowledgement["record_id"]
        assert memory_committed.acknowledgement["version"] == 1
        assert memory_committed.verification is not None
        assert memory_committed.verification["status"] == "verified"
        memory_store = Path(memory_committed.acknowledgement["store"])
        assert memory_store.exists()
        assert memory_committed.acknowledgement["record_id"] in memory_store.read_text()
        results["allowed_memory_write_commits"] = memory_committed.to_record()
        results["allowed_memory_write_trace"] = memory_committed_trace.to_record()
        results["allowed_memory_write_trace_events"] = [
            event["type"] for event in memory_committed_trace.events
        ]

        bad_memory_proposal = sample_memory_proposal()
        assert bad_memory_proposal.intent is not None
        bad_memory_proposal = Proposal(
            proposal_id="prop_bad_memory_001",
            actor=bad_memory_proposal.actor,
            speech_act="intend",
            reason="malformed memory content should not reach the adapter",
            confidence=0.72,
            evidence=bad_memory_proposal.evidence,
            intent=Intent(
                intent_id="intent_bad_memory_001",
                proposal_id="prop_bad_memory_001",
                adapter="memory",
                operation="write",
                target="project/bad-memory",
                input={},
                required_capability="memory.write",
            ),
        )
        bad_memory, bad_memory_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            bad_memory_proposal,
            approval_granted=True,
        )
        assert bad_memory.state == EffectState.REJECTED
        assert bad_memory.rejection_reason == "memory_content_missing_or_not_string"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_memory_trace.events
        ]
        results["memory_content_missing_rejected"] = bad_memory.to_record()
        results["memory_content_missing_trace"] = bad_memory_trace.to_record()

        no_memory_cap_scope = Scope(
            scope_id="no_memory_write_scope",
            sandbox_root=root.resolve(),
            capabilities=frozenset({"memory.read"}),
            approval_required_for=frozenset(),
        )
        no_memory_cap, no_memory_cap_trace = evaluate_memory_write(
            no_memory_cap_scope,
            sample_memory_proposal("project/no-capability"),
            approval_granted=True,
        )
        assert no_memory_cap.state == EffectState.REJECTED
        assert no_memory_cap.rejection_reason == "missing_capability"
        assert "adapter.commit.started" not in [
            event["type"] for event in no_memory_cap_trace.events
        ]
        results["memory_missing_capability_rejected"] = no_memory_cap.to_record()
        results["memory_missing_capability_trace"] = no_memory_cap_trace.to_record()

        spoofed_memory_proposal = Proposal(
            proposal_id="prop_memory_spoof_001",
            actor="agent:hermes",
            speech_act="intend",
            reason="memory writes must require memory.write regardless of proposal text",
            confidence=0.69,
            evidence=[],
            intent=Intent(
                intent_id="intent_memory_spoof_001",
                proposal_id="prop_memory_spoof_001",
                adapter="memory",
                operation="write",
                target="project/spoofed-capability",
                input={
                    "content": "should not commit\n",
                    "provenance": ["test:capability-spoof"],
                },
                required_capability="file.write",
            ),
        )
        spoofed_memory, spoofed_memory_trace = evaluate_memory_write(
            Scope(
                scope_id="file_only_scope",
                sandbox_root=root.resolve(),
                capabilities=frozenset({"file.write"}),
                approval_required_for=frozenset(),
            ),
            spoofed_memory_proposal,
            approval_granted=True,
        )
        assert spoofed_memory.state == EffectState.REJECTED
        assert spoofed_memory.rejection_reason == "unsupported_capability_for_operation"
        assert "adapter.commit.started" not in [
            event["type"] for event in spoofed_memory_trace.events
        ]
        assert not memory_store_path(
            sample_memory_scope(root, approval_required=False),
            "project/spoofed-capability",
        ).exists()
        results["memory_capability_spoof_rejected"] = spoofed_memory.to_record()
        results["memory_capability_spoof_trace"] = spoofed_memory_trace.to_record()

        malformed_store_scope = sample_memory_scope(root, approval_required=False)
        malformed_store = memory_store_path(malformed_store_scope, "project/malformed")
        malformed_store.parent.mkdir(parents=True, exist_ok=True)
        malformed_store.write_text("1\n", encoding="utf-8")
        malformed_memory, malformed_memory_trace = evaluate_memory_write(
            malformed_store_scope,
            sample_memory_proposal("project/malformed"),
            approval_granted=True,
        )
        assert malformed_memory.state == EffectState.REJECTED
        assert malformed_memory.rejection_reason == "memory_store_unreadable"
        assert "adapter.commit.started" not in [
            event["type"] for event in malformed_memory_trace.events
        ]
        assert malformed_store.read_text(encoding="utf-8") == "1\n"
        results["memory_malformed_store_rejected"] = malformed_memory.to_record()
        results["memory_malformed_store_trace"] = malformed_memory_trace.to_record()

        malformed_shape_store_scope = sample_memory_scope(root, approval_required=False)
        malformed_shape_store = memory_store_path(
            malformed_shape_store_scope,
            "project/malformed-shape",
        )
        malformed_shape_store.parent.mkdir(parents=True, exist_ok=True)
        malformed_shape_store.write_text("{}\n", encoding="utf-8")
        malformed_shape_memory, malformed_shape_trace = evaluate_memory_write(
            malformed_shape_store_scope,
            sample_memory_proposal("project/malformed-shape"),
            approval_granted=True,
        )
        assert malformed_shape_memory.state == EffectState.REJECTED
        assert malformed_shape_memory.rejection_reason == "memory_store_unreadable"
        assert "adapter.commit.started" not in [
            event["type"] for event in malformed_shape_trace.events
        ]
        assert malformed_shape_store.read_text(encoding="utf-8") == "{}\n"
        results["memory_malformed_shape_store_rejected"] = (
            malformed_shape_memory.to_record()
        )
        results["memory_malformed_shape_store_trace"] = malformed_shape_trace.to_record()

        bad_lifespan, bad_lifespan_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal(
                "project/bad-lifespan",
                content="invalid lifespan should reject\n",
                provenance=["test:bad-lifespan"],
                lifespan={"not": "serializable-as-v0-lifespan"},
            ),
            approval_granted=True,
        )
        assert bad_lifespan.state == EffectState.REJECTED
        assert bad_lifespan.rejection_reason == "memory_lifespan_invalid"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_lifespan_trace.events
        ]
        assert not memory_store_path(
            sample_memory_scope(root, approval_required=False),
            "project/bad-lifespan",
        ).exists()
        results["memory_lifespan_invalid_rejected"] = bad_lifespan.to_record()
        results["memory_lifespan_invalid_trace"] = bad_lifespan_trace.to_record()

        too_large_scope = Scope(
            scope_id="tiny_memory_scope",
            sandbox_root=root.resolve(),
            capabilities=frozenset({"memory.write"}),
            approval_required_for=frozenset(),
            max_bytes=256,
        )
        too_large_memory, too_large_trace = evaluate_memory_write(
            too_large_scope,
            sample_memory_proposal(
                "project/too-large-record",
                content="x",
                provenance=["p" * 600],
                lifespan="project",
            ),
            approval_granted=True,
        )
        assert too_large_memory.state == EffectState.REJECTED
        assert too_large_memory.rejection_reason == "input_too_large"
        assert "adapter.commit.started" not in [
            event["type"] for event in too_large_trace.events
        ]
        assert not memory_store_path(too_large_scope, "project/too-large-record").exists()
        results["memory_record_too_large_rejected"] = too_large_memory.to_record()
        results["memory_record_too_large_trace"] = too_large_trace.to_record()

        tampered_hash_scope = sample_memory_scope(root, approval_required=False)
        tampered_hash_store = memory_store_path(
            tampered_hash_scope,
            "project/tampered-hash",
        )
        tampered_hash_store.parent.mkdir(parents=True, exist_ok=True)
        tampered_hash_store.write_text(
            json.dumps(
                {
                    "record_id": "mem_tampered001",
                    "version": 1,
                    "target": "project/tampered-hash",
                    "content": "tampered content\n",
                    "lifespan": "project",
                    "provenance": ["test:tampered-hash"],
                    "actor": "agent:hermes",
                    "proposal_id": "prop_tampered_001",
                    "intent_id": "intent_tampered_001",
                    "trace_id": "trace_tampered",
                    "input_sha256": "0" * 64,
                    "committed_at": now_timestamp(),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        tampered_hash_memory, tampered_hash_trace = evaluate_memory_write(
            tampered_hash_scope,
            sample_memory_proposal("project/tampered-hash"),
            approval_granted=True,
        )
        assert tampered_hash_memory.state == EffectState.REJECTED
        assert tampered_hash_memory.rejection_reason == "memory_store_unreadable"
        assert "adapter.commit.started" not in [
            event["type"] for event in tampered_hash_trace.events
        ]
        assert tampered_hash_store.read_text(encoding="utf-8").count("\n") == 1
        results["memory_tampered_hash_store_rejected"] = (
            tampered_hash_memory.to_record()
        )
        results["memory_tampered_hash_store_trace"] = tampered_hash_trace.to_record()

        reserved_suffix_memory, reserved_suffix_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal("project/foo.jsonl/bar"),
            approval_granted=True,
        )
        assert reserved_suffix_memory.state == EffectState.REJECTED
        assert reserved_suffix_memory.rejection_reason == "memory_target_reserved_suffix"
        assert "adapter.commit.started" not in [
            event["type"] for event in reserved_suffix_trace.events
        ]
        results["memory_reserved_suffix_target_rejected"] = (
            reserved_suffix_memory.to_record()
        )
        results["memory_reserved_suffix_target_trace"] = reserved_suffix_trace.to_record()

        old_umask = os.umask(0o444)
        try:
            restrictive_umask_scope = sample_memory_scope(
                root,
                approval_required=False,
            )
            restrictive_umask_memory, restrictive_umask_trace = evaluate_memory_write(
                restrictive_umask_scope,
                sample_memory_proposal("project/restrictive-umask"),
                approval_granted=True,
            )
        finally:
            os.umask(old_umask)
        assert restrictive_umask_memory.state == EffectState.COMMITTED
        restrictive_store = memory_store_path(
            restrictive_umask_scope,
            "project/restrictive-umask",
        )
        assert restrictive_store.read_text(encoding="utf-8").count("\n") == 1
        assert "adapter.commit.failed" not in [
            event["type"] for event in restrictive_umask_trace.events
        ]
        results["memory_restrictive_umask_commits_verified"] = (
            restrictive_umask_memory.to_record()
        )
        results["memory_restrictive_umask_trace"] = restrictive_umask_trace.to_record()

        bad_memory_target, bad_memory_target_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_memory_bad_target_001",
                actor="agent:hermes",
                speech_act="intend",
                reason="malformed target should reject under governance",
                confidence=0.64,
                evidence=[],
                intent=Intent(
                    intent_id="intent_memory_bad_target_001",
                    proposal_id="prop_memory_bad_target_001",
                    adapter="memory",
                    operation="write",
                    target=123,
                    input={
                        "content": "should not commit\n",
                        "provenance": ["test:bad-target"],
                    },
                    required_capability="memory.write",
                ),
            ),
            approval_granted=True,
        )
        assert bad_memory_target.state == EffectState.REJECTED
        assert bad_memory_target.rejection_reason == "target_missing_or_not_string"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_memory_target_trace.events
        ]
        results["memory_target_not_string_rejected"] = bad_memory_target.to_record()
        results["memory_target_not_string_trace"] = bad_memory_target_trace.to_record()

        bad_memory_input, bad_memory_input_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_memory_bad_input_001",
                actor="agent:hermes",
                speech_act="intend",
                reason="malformed input should reject under governance",
                confidence=0.63,
                evidence=[],
                intent=Intent(
                    intent_id="intent_memory_bad_input_001",
                    proposal_id="prop_memory_bad_input_001",
                    adapter="memory",
                    operation="write",
                    target="project/bad-input",
                    input=None,
                    required_capability="memory.write",
                ),
            ),
            approval_granted=True,
        )
        assert bad_memory_input.state == EffectState.REJECTED
        assert bad_memory_input.rejection_reason == "input_missing_or_not_object"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_memory_input_trace.events
        ]
        assert not memory_store_path(
            sample_memory_scope(root, approval_required=False),
            "project/bad-input",
        ).exists()
        results["memory_input_not_object_rejected"] = bad_memory_input.to_record()
        results["memory_input_not_object_trace"] = bad_memory_input_trace.to_record()

        memory_paused, memory_paused_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=True),
            sample_memory_proposal("project/needs-approval"),
            approval_granted=False,
        )
        assert memory_paused.state == EffectState.PAUSED
        assert memory_paused.required_input == "human_approval"
        assert "adapter.commit.started" not in [
            event["type"] for event in memory_paused_trace.events
        ]
        assert not memory_store_path(
            sample_memory_scope(root, approval_required=True),
            "project/needs-approval",
        ).exists()
        results["memory_approval_required_pauses"] = memory_paused.to_record()
        results["memory_approval_required_trace"] = memory_paused_trace.to_record()

        for result_key, rejected_target in {
            "memory_empty_target_rejected": "",
            "memory_dot_target_rejected": ".",
            "memory_path_escape_rejected": "../outside-scope",
        }.items():
            rejected_memory, rejected_memory_trace = evaluate_memory_write(
                sample_memory_scope(root, approval_required=False),
                sample_memory_proposal(rejected_target),
                approval_granted=True,
            )
            assert rejected_memory.state == EffectState.REJECTED
            assert rejected_memory.rejection_reason == "memory_target_outside_scope"
            assert "adapter.commit.started" not in [
                event["type"] for event in rejected_memory_trace.events
            ]
            results[result_key] = rejected_memory.to_record()
            results[f"{result_key}_trace"] = rejected_memory_trace.to_record()

        plain_target, plain_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal("project/collision"),
            approval_granted=True,
        )
        suffix_target, suffix_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal("project/collision.txt"),
            approval_granted=True,
        )
        assert plain_target.state == EffectState.COMMITTED
        assert suffix_target.state == EffectState.COMMITTED
        assert plain_target.acknowledgement is not None
        assert suffix_target.acknowledgement is not None
        assert plain_target.acknowledgement["store"] != suffix_target.acknowledgement[
            "store"
        ]
        results["memory_distinct_targets_do_not_collide"] = suffix_target.to_record()
        results["memory_distinct_targets_first_trace"] = plain_trace.to_record()
        results["memory_distinct_targets_second_trace"] = suffix_trace.to_record()

        interpret_target = root / "interpret-untouched.txt"
        assert not interpret_target.exists()
        interpret_file_approved, interpret_file_approved_trace = interpret(
            sample_scope(root, approval_required=False),
            sample_proposal("interpret-untouched.txt"),
            approval_granted=True,
        )
        assert interpret_file_approved.state == EffectState.APPROVED
        assert interpret_file_approved.acknowledgement is None
        assert interpret_file_approved.committed_at is None
        assert not interpret_target.exists()
        approved_event_types = [
            event["type"] for event in interpret_file_approved_trace.events
        ]
        assert "approval.granted" in approved_event_types
        assert "adapter.commit.started" not in approved_event_types
        assert "effect.committed" not in approved_event_types
        results["interpret_file_write_approved_without_committing"] = (
            interpret_file_approved.to_record()
        )
        results["interpret_file_write_approved_trace"] = (
            interpret_file_approved_trace.to_record()
        )
        results["interpret_file_write_approved_trace_events"] = approved_event_types

        interpret_pause_target = root / "interpret-pause.txt"
        assert not interpret_pause_target.exists()
        interpret_file_paused, interpret_file_paused_trace = interpret(
            sample_scope(root, approval_required=True),
            sample_proposal("interpret-pause.txt"),
        )
        assert interpret_file_paused.state == EffectState.PAUSED
        assert interpret_file_paused.required_input == "human_approval"
        assert not interpret_pause_target.exists()
        paused_event_types = [
            event["type"] for event in interpret_file_paused_trace.events
        ]
        assert "approval.requested" in paused_event_types
        assert "adapter.commit.started" not in paused_event_types
        results["interpret_file_write_paused_without_committing"] = (
            interpret_file_paused.to_record()
        )
        results["interpret_file_write_paused_trace"] = (
            interpret_file_paused_trace.to_record()
        )

        interpret_reject_target = root / ".." / "outside-interpret-scope.txt"
        interpret_file_rejected, interpret_file_rejected_trace = interpret(
            sample_scope(root, approval_required=False),
            sample_proposal("../outside-interpret-scope.txt"),
            approval_granted=True,
        )
        assert interpret_file_rejected.state == EffectState.REJECTED
        assert interpret_file_rejected.rejection_reason == "path_outside_scope"
        rejected_event_types = [
            event["type"] for event in interpret_file_rejected_trace.events
        ]
        assert "adapter.commit.started" not in rejected_event_types
        results["interpret_file_write_rejected"] = interpret_file_rejected.to_record()
        results["interpret_file_write_rejected_trace"] = (
            interpret_file_rejected_trace.to_record()
        )

        interpret_non_intent, interpret_non_intent_trace = interpret(
            sample_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_interpret_non_intent_001",
                actor="agent:hermes",
                speech_act="claim",
                reason="not an effect intent",
                confidence=0.5,
                evidence=[],
            ),
            approval_granted=True,
        )
        assert interpret_non_intent.state == EffectState.REJECTED
        assert interpret_non_intent.rejection_reason == "proposal_is_not_an_intent"
        non_intent_events = [
            event["type"] for event in interpret_non_intent_trace.events
        ]
        assert "adapter.commit.started" not in non_intent_events
        results["interpret_non_intent_rejected"] = interpret_non_intent.to_record()
        results["interpret_non_intent_trace"] = interpret_non_intent_trace.to_record()

        interpret_unknown_adapter_proposal = Proposal(
            proposal_id="prop_interpret_unknown_adapter_001",
            actor="agent:hermes",
            speech_act="intend",
            reason="unsupported adapter for interpret",
            confidence=0.6,
            evidence=[],
            intent=Intent(
                intent_id="intent_interpret_unknown_adapter_001",
                proposal_id="prop_interpret_unknown_adapter_001",
                adapter="network",
                operation="post",
                target="https://example.invalid/",
                input={"body": ""},
                required_capability="network.post",
            ),
        )
        interpret_unknown, interpret_unknown_trace = interpret(
            sample_scope(root, approval_required=False),
            interpret_unknown_adapter_proposal,
            approval_granted=True,
        )
        assert interpret_unknown.state == EffectState.REJECTED
        assert (
            interpret_unknown.rejection_reason == "unsupported_adapter_for_interpret"
        )
        results["interpret_unsupported_adapter_rejected"] = (
            interpret_unknown.to_record()
        )
        results["interpret_unsupported_adapter_trace"] = (
            interpret_unknown_trace.to_record()
        )

        memory_ledger_root = root / ".fermata-memory"
        memory_files_before = (
            sorted(p.name for p in memory_ledger_root.glob("**/*.jsonl"))
            if memory_ledger_root.exists()
            else []
        )
        interpret_memory_approved, interpret_memory_approved_trace = interpret(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal("project/interpret-only.txt"),
            approval_granted=True,
        )
        assert interpret_memory_approved.state == EffectState.APPROVED
        assert interpret_memory_approved.acknowledgement is None
        memory_files_after = (
            sorted(p.name for p in memory_ledger_root.glob("**/*.jsonl"))
            if memory_ledger_root.exists()
            else []
        )
        assert memory_files_after == memory_files_before
        memory_approved_events = [
            event["type"] for event in interpret_memory_approved_trace.events
        ]
        assert "approval.granted" in memory_approved_events
        assert "adapter.commit.started" not in memory_approved_events
        results["interpret_memory_write_approved_without_committing"] = (
            interpret_memory_approved.to_record()
        )
        results["interpret_memory_write_approved_trace"] = (
            interpret_memory_approved_trace.to_record()
        )

        from fermata.policy_parser import (
            parse_agent_proposal_json,
            parse_policy_block,
            PolicyParseError,
        )

        human_policy_text = (
            "scope charter_note_sandbox {\n"
            '  resource file "./sandbox/charter-note.txt"\n'
            '  capability file.read on "./sandbox/**"\n'
            '  capability file.write on "./sandbox/**"\n'
            "  policy deny if path.outside_scope\n"
            '  approval require human if effect.kind == "file.write"\n'
            "  audit retain trace, input_hash, output_hash, actor, approval\n"
            "}\n"
        )
        scope_record = parse_policy_block(human_policy_text)
        assert scope_record["record_type"] == "scope"
        assert scope_record["scope_id"] == "charter_note_sandbox"
        assert len(scope_record["resources"]) == 1
        assert scope_record["resources"][0]["kind"] == "file"
        assert {c["name"] for c in scope_record["capabilities"]} == {
            "file.read",
            "file.write",
        }
        assert scope_record["policies"][0]["effect"] == "deny"
        assert scope_record["approvals"][0]["authority"] == "human"
        assert "trace" in scope_record["audit"]["retain"]
        results["human_policy_parses_to_scope_record"] = scope_record

        agent_json = (
            "{\n"
            '  "schema_version": "0.1",\n'
            '  "record_type": "proposal",\n'
            '  "proposal_id": "prop_surface_test_001",\n'
            '  "actor": "agent:hermes",\n'
            '  "speech_act": "intend",\n'
            '  "reason": "split-surfaces kata",\n'
            '  "confidence": 0.81,\n'
            '  "evidence": ["scope:charter_note_sandbox"],\n'
            '  "payload": {"utterance": "intend file.write target:\\"./sandbox/note.txt\\""},\n'
            '  "intent": {\n'
            '    "intent_id": "intent_surface_test_001",\n'
            '    "proposal_id": "prop_surface_test_001",\n'
            '    "adapter": "file",\n'
            '    "operation": "write",\n'
            '    "target": "./sandbox/note.txt",\n'
            '    "input": {"content": "boring proof\\n"},\n'
            '    "required_capability": "file.write"\n'
            "  }\n"
            "}\n"
        )
        proposal_record = parse_agent_proposal_json(agent_json)
        assert proposal_record["record_type"] == "proposal"
        assert proposal_record["speech_act"] == "intend"
        assert proposal_record["intent"]["adapter"] == "file"
        assert proposal_record["intent"]["target"] == "./sandbox/note.txt"
        assert "state" not in proposal_record
        assert "acknowledgement" not in proposal_record
        results["agent_json_parses_to_proposal_record"] = proposal_record

        injected_agent_json = (
            "{\n"
            '  "schema_version": "0.1",\n'
            '  "record_type": "proposal",\n'
            '  "proposal_id": "prop_surface_inject_001",\n'
            '  "actor": "agent:hermes",\n'
            '  "speech_act": "claim",\n'
            '  "payload": {"utterance": "claim something"},\n'
            '  "state": "committed",\n'
            '  "acknowledgement": {"adapter": "file", "target": "x", "handle": "x"}\n'
            "}\n"
        )
        injected_record = parse_agent_proposal_json(injected_agent_json)
        results["agent_cannot_inject_committed_state"] = {
            "record_with_injection": injected_record,
        }

        try:
            parse_policy_block(
                "scope evil { resource file \"./x\" capability file.write on \"./x\""
                "\n  approval grant human always\n}"
            )
        except PolicyParseError as exc:
            results["human_policy_cannot_inline_grant"] = {
                "rejected": True,
                "error": str(exc),
            }
        else:
            raise AssertionError(
                "human policy parser must reject 'approval grant ...' — the "
                "human surface declares requirements, not granted approvals"
            )

    return results


def main() -> None:
    """Run the spike self-tests and print JSON evidence."""

    results = run_self_tests()
    print(json.dumps(results, indent=2, sort_keys=True))
