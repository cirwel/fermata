"""Shared governed-effect evaluator and local audit helpers."""

from __future__ import annotations

import json
import os
import uuid
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
    """Return the scoped local trace ledger path."""

    return (scope.sandbox_root / ".fermata-traces" / "traces.jsonl").resolve()


def append_trace_ledger(scope: Scope, trace: Trace) -> dict[str, Any]:
    """Append a trace record to a scoped durable JSONL audit ledger.

    This is explicit rather than automatic so pure interpretation remains free of
    external side effects. The ledger write is local, fsynced, and verified by
    reading back the appended trace by ID and line hash.
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
    fd = os.open(ledger_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as ledger_file:
        os.fchmod(ledger_file.fileno(), 0o600)
        ledger_file.write(record_bytes)
        ledger_file.flush()
        os.fsync(ledger_file.fileno())

    try:
        dir_fd = os.open(ledger_path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass

    matched_record: dict[str, Any] | None = None
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
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
    return EffectResult(
        state=EffectState.COMMITTED,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=intent.intent_id,
        scope_id=scope.scope_id,
        acknowledgement=commit_evidence.acknowledgement,
        verification=commit_evidence.verification,
        approval=approval_record,
        committed_at=commit_evidence.committed_at,
    ), trace
