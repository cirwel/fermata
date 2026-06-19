"""Shared governed-effect evaluator and local audit helpers."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fermata.runtime_ir import (
    AdapterPreparation,
    ApprovalDecision,
    ApprovalStatus,
    EffectResult,
    EffectState,
    GovernedAdapter,
    Intent,
    Proposal,
    RejectionReason,
    Scope,
    Trace,
    approval_for,
    approval_rejection_reason,
    enum_value,
    intent_sha256,
    sha256_bytes,
)


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


def anchored_atomic_write(
    scope: Scope,
    target_path: Path,
    content_bytes: bytes,
    *,
    verify: Callable[[bytes], None],
) -> None:
    """Atomically write ``content_bytes`` to ``target_path``, symlink-safe.

    The shared anchored-write primitive used by the memory and network adapters.
    It reaches the target's parent directory by the file adapter's O_NOFOLLOW
    walk from the sandbox, creates a temp file in that directory fd
    (``O_EXCL | O_NOFOLLOW``), fsyncs it, reads it back through the same fd, and
    calls ``verify(readback_bytes)`` — which must raise to abort *before* any
    replace. Only then does it rename the temp over the target and fsync the
    directory. No symlink at any path component can redirect the write or the
    read-back.

    Raises ``OSError`` / ``ValueError`` on any failure or verify rejection; the
    temp file is removed on failure. Callers map the exception to a governed
    rejection. The best-effort directory fsync after replace never fails the
    write (matching the file adapter).
    """

    # Local import: file_adapter imports runtime_core, so importing it at module
    # scope would be circular. open_file_parent_fd is the shared anchored walk.
    from fermata.file_adapter import open_file_parent_fd

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    target_name = target_path.name
    temp_name = f".{target_name}.{uuid.uuid4().hex}.tmp"
    replaced = False
    parent_fd = open_file_parent_fd(scope, target_path)
    try:
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(fd, "wb") as temp_file:
            os.fchmod(temp_file.fileno(), 0o600)
            temp_file.write(content_bytes)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        read_fd = os.open(temp_name, os.O_RDONLY | nofollow, dir_fd=parent_fd)
        with os.fdopen(read_fd, "rb") as temp_file:
            readback = temp_file.read()
        verify(readback)

        os.replace(
            temp_name,
            target_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        replaced = True
        try:
            os.fsync(parent_fd)
        except OSError:
            pass
    finally:
        if not replaced:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


def idempotency_store_path(scope: Scope) -> Path:
    """Scoped local idempotency ledger path (sandbox root resolved, leaf not)."""

    return scope.sandbox_root.resolve() / ".fermata-idempotency" / "keys.jsonl"


def idempotency_lookup(scope: Scope, key: str) -> dict[str, Any] | None:
    """Return the most recent committed record stored under (scope, key), or None.

    Reads the scoped idempotency ledger through an O_NOFOLLOW open so a symlink
    planted at the ledger leaf is refused rather than followed. A missing ledger
    means no prior commit under this key.

    Local-alpha limitation: the ledger is append-only and never compacted, and
    this lookup re-reads and re-parses the whole file on every commit — O(n) in
    the number of prior commits under the scope. Fine for the single-writer
    alpha; a long-lived or high-volume scope would want an index or rotation.
    """

    ledger_path = idempotency_store_path(scope)
    if not is_inside(scope.sandbox_root, ledger_path):
        raise ValueError(RejectionReason.PATH_OUTSIDE_SCOPE.value)
    try:
        read_fd = os.open(ledger_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    with os.fdopen(read_fd, "r", encoding="utf-8") as ledger_file:
        text = ledger_file.read()
    found: dict[str, Any] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if (
            record.get("idempotency_key") == key
            and record.get("scope_id") == scope.scope_id
        ):
            found = record
    return found


def _append_jsonl_record(scope: Scope, ledger_path: Path, record: dict[str, Any]) -> None:
    """Append one JSON record line to a scoped JSONL ledger, symlink-safe.

    Shared by the idempotency and rate-budget ledgers. Reaches the ledger
    directory with the file adapter's O_NOFOLLOW anchored walk so no symlink at
    any path component can redirect the append; the write is fsynced.
    """

    ensure_private_directory(ledger_path.parent, root=ledger_path.parent.resolve())

    from fermata.file_adapter import open_file_parent_fd

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    line = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    parent_fd = open_file_parent_fd(scope, ledger_path)
    try:
        fd = os.open(
            ledger_path.name,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | nofollow,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(fd, "ab") as ledger_file:
            os.fchmod(ledger_file.fileno(), 0o600)
            ledger_file.write(line)
            ledger_file.flush()
            os.fsync(ledger_file.fileno())
        try:
            os.fsync(parent_fd)
        except OSError:
            pass
    finally:
        os.close(parent_fd)


def idempotency_record(scope: Scope, record: dict[str, Any]) -> None:
    """Append one idempotency record to the scoped ledger, symlink-safe."""

    _append_jsonl_record(scope, idempotency_store_path(scope), record)


def rate_store_path(scope: Scope) -> Path:
    """Scoped local rate-budget ledger path (sandbox root resolved, leaf not)."""

    return scope.sandbox_root.resolve() / ".fermata-rate" / "events.jsonl"


def _rate_now() -> float:
    """Monotonic-enough wall clock (epoch seconds) for rate-window arithmetic.

    Factored out so tests can drive the window deterministically.
    """

    return time.time()


def rate_count_recent(scope: Scope, *, now: float, window_seconds: float) -> int:
    """Count committed-effect events for this scope within the trailing window.

    Reads the scoped rate ledger through an O_NOFOLLOW open. A missing ledger
    means no prior effects. Events at or after ``now - window_seconds`` count;
    older events have aged out of the window. A corrupt/unparseable line is
    skipped rather than raised — an approximate undercount is preferable to
    failing an otherwise-permitted effect on a torn historical line.

    Local-alpha limitation: like the idempotency and trace ledgers, this file is
    append-only and never compacted — aged-out events are skipped on read but
    not pruned, and the whole ledger is re-read per commit (O(n)). Fine for the
    single-writer alpha; rotation/pruning is future work.
    """

    ledger_path = rate_store_path(scope)
    if not is_inside(scope.sandbox_root, ledger_path):
        raise ValueError(RejectionReason.PATH_OUTSIDE_SCOPE.value)
    try:
        read_fd = os.open(ledger_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return 0
    with os.fdopen(read_fd, "r", encoding="utf-8") as ledger_file:
        text = ledger_file.read()
    threshold = now - window_seconds
    count = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = record.get("ts")
        if isinstance(ts, (int, float)) and ts >= threshold:
            count += 1
    return count


def rate_record(scope: Scope, record: dict[str, Any]) -> None:
    """Append one committed-effect timestamp record to the scoped rate ledger."""

    _append_jsonl_record(scope, rate_store_path(scope), record)


def reject(
    trace: Trace,
    scope: Scope,
    intent_id: str | None,
    reason: str | RejectionReason,
    approval: dict[str, Any] | None = None,
    **fields: Any,
) -> EffectResult:
    """Emit a rejection result."""

    reason_text = enum_value(reason)
    trace.add("effect.rejected", reason=reason_text, **fields)
    return EffectResult(
        state=EffectState.REJECTED,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=intent_id,
        scope_id=scope.scope_id,
        approval=approval,
        rejection_reason=reason_text,
    )


def pause(
    trace: Trace,
    scope: Scope,
    intent_id: str,
    required_input: str,
    approval: dict[str, Any] | None = None,
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
        approval=approval,
        required_input=required_input,
    )


def approved_result(
    trace: Trace,
    scope: Scope,
    intent: Intent,
    approval: ApprovalDecision,
) -> EffectResult:
    """Return a pure approved result without adapter commit evidence."""

    return EffectResult(
        state=EffectState.APPROVED,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=intent.intent_id,
        scope_id=scope.scope_id,
        approval=approval.to_record(),
    )


def trace_ledger_path(scope: Scope) -> Path:
    """Return the scoped local trace ledger path.

    Only the sandbox root is resolved; the ``.fermata-traces`` directory and
    ``traces.jsonl`` leaf are left unresolved so a symlink planted at either
    component is not silently followed during path computation. The anchored
    O_NOFOLLOW walk in ``append_trace_ledger`` is what rejects such symlinks.
    """

    return scope.sandbox_root.resolve() / ".fermata-traces" / "traces.jsonl"


def append_trace_ledger(scope: Scope, trace: Trace) -> dict[str, Any]:
    """Append a trace record to a scoped durable JSONL audit ledger.

    This is explicit rather than automatic so pure interpretation remains free of
    external side effects. The ledger write is local, fsynced, and verified by
    reading back the appended trace by ID and line hash.

    Local-alpha limitation: like the idempotency ledger, this file is append-only
    and never compacted, and the read-back re-reads and re-parses the whole
    ledger on every append (O(n) in prior traces). Acceptable for the
    single-writer alpha; rotation or an index is future work.
    """

    ledger_path = trace_ledger_path(scope)
    ledger_root = ledger_path.parent.resolve()
    if not is_inside(scope.sandbox_root, ledger_path):
        raise ValueError(RejectionReason.PATH_OUTSIDE_SCOPE.value)

    trace_record = trace.to_record()
    record_bytes = (json.dumps(trace_record, sort_keys=True) + "\n").encode("utf-8")
    if len(record_bytes) > scope.max_bytes:
        raise ValueError(RejectionReason.INPUT_TOO_LARGE.value)

    record_hash = sha256_bytes(record_bytes)
    ensure_private_directory(ledger_path.parent, root=ledger_root)

    # The audit ledger is the integrity record of governance decisions, so it
    # is held to the same symlink-safety bar as governed content. Walk to the
    # ledger directory with O_NOFOLLOW at every component (reusing the file
    # adapter's anchored walk) and open the ledger file relative to that
    # directory fd with O_NOFOLLOW, so neither the write nor the read-back can
    # be redirected through a symlink planted at the ledger path.
    from fermata.file_adapter import open_file_parent_fd

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    ledger_name = ledger_path.name
    parent_fd = open_file_parent_fd(scope, ledger_path)
    try:
        fd = os.open(
            ledger_name,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | nofollow,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(fd, "ab") as ledger_file:
            os.fchmod(ledger_file.fileno(), 0o600)
            ledger_file.write(record_bytes)
            ledger_file.flush()
            os.fsync(ledger_file.fileno())

        try:
            os.fsync(parent_fd)
        except OSError:
            pass

        read_fd = os.open(ledger_name, os.O_RDONLY | nofollow, dir_fd=parent_fd)
        with os.fdopen(read_fd, "rb") as ledger_read:
            ledger_text = ledger_read.read().decode("utf-8")
    finally:
        os.close(parent_fd)

    matched_record: dict[str, Any] | None = None
    for line in ledger_text.splitlines():
        if not line.strip():
            continue
        # A corrupt historical line (e.g. a torn write from an earlier crash)
        # must not break verification of the record we just appended: skip it
        # rather than raise. Our own line is well-formed, so the match below
        # still finds it. The read-back guarantee is "the record I wrote is on
        # disk intact", not "every prior line is parseable".
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        line_hash = sha256_bytes((line + "\n").encode("utf-8"))
        if parsed.get("trace_id") == trace.trace_id and line_hash == record_hash:
            matched_record = parsed
            break
    if matched_record != trace_record:
        raise ValueError("trace_ledger_read_back_mismatch")

    ack = {
        "adapter": "trace_ledger",
        "target": str(ledger_path),
        "handle": trace.trace_id,
        "trace_id": trace.trace_id,
        "sha256": record_hash,
        "bytes": len(record_bytes),
    }
    verification = {
        "status": "verified",
        "method": "read_back_trace_record",
        "detail": {"trace_id": trace.trace_id, "sha256": record_hash},
    }
    return {"acknowledgement": ack, "verification": verification}


def evaluate_with_adapter(
    scope: Scope,
    proposal: Proposal,
    adapter: GovernedAdapter,
    *,
    approval_granted: bool = False,
    approval: ApprovalDecision | None = None,
    _stop_at_approval: bool = False,
) -> tuple[EffectResult, Trace]:
    """Run the shared proposal -> approval -> optional commit state machine.

    Required approvals should arrive as typed ``ApprovalDecision`` records.
    ``approval_granted`` remains as compatibility for older callers.
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
        return (
            reject(trace, scope, None, RejectionReason.PROPOSAL_IS_NOT_AN_INTENT),
            trace,
        )

    intent = proposal.intent
    trace.add(
        "intent.created",
        intent_id=intent.intent_id,
        adapter=intent.adapter,
        operation=intent.operation,
        target=intent.target,
    )

    if intent.adapter != adapter.adapter or intent.operation != adapter.operation:
        return reject(
            trace,
            scope,
            intent.intent_id,
            RejectionReason.UNSUPPORTED_ADAPTER_OPERATION,
        ), trace

    if intent.required_capability != adapter.capability:
        return reject(
            trace,
            scope,
            intent.intent_id,
            RejectionReason.UNSUPPORTED_CAPABILITY_FOR_OPERATION,
            declared_capability=intent.required_capability,
            required_capability=adapter.capability,
        ), trace

    if adapter.capability not in scope.capabilities:
        return reject(
            trace,
            scope,
            intent.intent_id,
            RejectionReason.MISSING_CAPABILITY,
            required_capability=adapter.capability,
        ), trace

    if not isinstance(intent.target, str):
        return reject(
            trace,
            scope,
            intent.intent_id,
            RejectionReason.TARGET_MISSING_OR_NOT_STRING,
        ), trace

    if not isinstance(intent.input, dict):
        return reject(
            trace,
            scope,
            intent.intent_id,
            RejectionReason.INPUT_MISSING_OR_NOT_OBJECT,
        ), trace

    # Idempotent replay: if this scope already committed an effect under the same
    # key, return the prior committed result instead of re-running the adapter.
    # Checked before prepare() so a replay short-circuits even when the adapter
    # would otherwise reject the redo (e.g. file.write target-exists). Only on
    # the real commit path — interpret() never commits, so it never replays. A
    # reused key with a different intent is a conflict, not a replay.
    if not _stop_at_approval and intent.idempotency_key:
        try:
            prior = idempotency_lookup(scope, intent.idempotency_key)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.ADAPTER_COMMIT_FAILED,
                error_type=exc.__class__.__name__,
            ), trace
        if prior is not None:
            if prior.get("intent_sha256") != intent_sha256(intent):
                trace.add(
                    "effect.idempotency_conflict",
                    idempotency_key=intent.idempotency_key,
                )
                return reject(
                    trace,
                    scope,
                    intent.intent_id,
                    RejectionReason.IDEMPOTENCY_KEY_CONFLICT,
                    idempotency_key=intent.idempotency_key,
                ), trace
            prior_effect = prior.get("effect", {})
            trace.add(
                "effect.idempotent_replay",
                idempotency_key=intent.idempotency_key,
                effect_id=prior_effect.get("effect_id"),
                committed_at=prior_effect.get("committed_at"),
            )
            # Approval is intentionally NOT re-evaluated on replay: the effect
            # already committed in the external world, so this is informational,
            # not a new authorization. The original approval record is carried
            # through unchanged so the replayed result keeps its audit binding.
            return EffectResult(
                state=EffectState.COMMITTED,
                trace_id=trace.trace_id,
                effect_id=prior_effect.get("effect_id")
                or f"effect_{uuid.uuid4().hex[:8]}",
                intent_id=intent.intent_id,
                scope_id=scope.scope_id,
                acknowledgement=prior_effect.get("acknowledgement"),
                verification=prior_effect.get("verification"),
                approval=prior_effect.get("approval"),
                committed_at=prior_effect.get("committed_at"),
            ), trace

    preparation = adapter.prepare(scope, proposal, intent, trace)
    if isinstance(preparation, EffectResult):
        return preparation, trace

    trace.add("policy.checked", result="allowed", checks=preparation.checks)
    trace.add(
        "dry_run.rendered",
        summary=preparation.dry_run_summary,
        **preparation.dry_run_fields,
    )

    approval_decision = approval_for(
        scope,
        intent,
        preparation.effect_kind,
        approval=approval,
        approval_granted=approval_granted,
    )
    approval_record = approval_decision.to_record()
    if approval_decision.status == ApprovalStatus.REQUESTED:
        trace.add(
            "approval.requested",
            effect_kind=preparation.effect_kind,
            **approval_record,
        )
        return pause(
            trace,
            scope,
            intent.intent_id,
            "approval_decision",
            approval=approval_record,
            reason="approval_required_before_commit",
        ), trace

    approval_rejection = approval_rejection_reason(scope, intent, approval_decision)
    if approval_rejection is not None:
        trace.add(
            "approval.rejected",
            effect_kind=preparation.effect_kind,
            **approval_record,
        )
        return reject(
            trace,
            scope,
            intent.intent_id,
            approval_rejection,
            approval=approval_record,
        ), trace

    trace.add(
        "approval.granted",
        effect_kind=preparation.effect_kind,
        **approval_record,
    )

    if _stop_at_approval:
        return approved_result(trace, scope, intent, approval_decision), trace

    # Per-scope rolling-window rate budget: count committed effects in the
    # trailing window and refuse once the scope is at its cap. Checked after
    # approval (only an otherwise-committable effect consumes budget) and
    # before commit (a refusal performs no external effect). Idempotent replays
    # returned earlier never reach here, so they never consume budget.
    effect_now: float | None = None
    if scope.max_effects_per_window > 0:
        effect_now = _rate_now()
        try:
            recent = rate_count_recent(
                scope, now=effect_now, window_seconds=scope.rate_window_seconds
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.ADAPTER_COMMIT_FAILED,
                error_type=exc.__class__.__name__,
            ), trace
        if recent >= scope.max_effects_per_window:
            trace.add(
                "effect.rate_limited",
                max_effects_per_window=scope.max_effects_per_window,
                rate_window_seconds=scope.rate_window_seconds,
                recent=recent,
            )
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.SCOPE_RATE_LIMIT_EXCEEDED,
                max_effects_per_window=scope.max_effects_per_window,
            ), trace

    trace.add(
        "adapter.commit.started",
        adapter=adapter.adapter,
        target=preparation.commit_target,
    )
    commit_evidence = adapter.commit(scope, proposal, intent, trace, preparation)
    if isinstance(commit_evidence, EffectResult):
        return commit_evidence, trace

    trace.add(
        "effect.committed",
        acknowledgement=commit_evidence.acknowledgement,
        verification=commit_evidence.verification,
        committed_at=commit_evidence.committed_at,
    )
    committed = EffectResult(
        state=EffectState.COMMITTED,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=intent.intent_id,
        scope_id=scope.scope_id,
        acknowledgement=commit_evidence.acknowledgement,
        verification=commit_evidence.verification,
        approval=approval_record,
        committed_at=commit_evidence.committed_at,
    )

    # Record the key so a later retry replays this result instead of committing
    # again. The effect has already happened; a recording failure must not fail
    # the commit (it only means a future retry would not dedupe), so it is traced
    # rather than raised.
    if intent.idempotency_key:
        try:
            idempotency_record(
                scope,
                {
                    "idempotency_key": intent.idempotency_key,
                    "scope_id": scope.scope_id,
                    "intent_sha256": intent_sha256(intent),
                    "effect": committed.to_record(),
                },
            )
        except (OSError, ValueError) as exc:
            trace.add(
                "effect.idempotency_record_failed",
                error_type=exc.__class__.__name__,
            )

    # Record this committed effect against the scope's rate budget. As with the
    # idempotency record, the effect has already happened, so a recording
    # failure is traced rather than raised — it can only under-count the window.
    if scope.max_effects_per_window > 0 and effect_now is not None:
        try:
            rate_record(
                scope,
                {
                    "ts": effect_now,
                    "scope_id": scope.scope_id,
                    "effect_id": committed.effect_id,
                    "committed_at": committed.committed_at,
                },
            )
        except (OSError, ValueError) as exc:
            trace.add(
                "effect.rate_record_failed",
                error_type=exc.__class__.__name__,
            )

    return committed, trace
