"""Pure governed-effect interpreter dispatch."""

from __future__ import annotations

import uuid

from fermata.file_adapter import evaluate_file_write
from fermata.memory_adapter import evaluate_memory_write
from fermata.runtime_core import reject
from fermata.runtime_ir import (
    ApprovalDecision,
    EffectResult,
    Proposal,
    RejectionReason,
    Scope,
    Trace,
)


def interpret(
    scope: Scope,
    proposal: Proposal,
    *,
    approval_granted: bool = False,
    approval: ApprovalDecision | None = None,
) -> tuple[EffectResult, Trace]:
    """Run a proposal through the governed-effect state machine without committing.

    Returns an ``EffectResult`` in one of three terminal-for-pure-eval states:

    - ``REJECTED`` — the proposal failed admission, verification, or shape checks;
    - ``PAUSED`` — the proposal reached approval but approval was required and not
      granted; the runtime needs an approval decision before proceeding;
    - ``APPROVED`` — the proposal cleared all pure-eval phases and would commit on
      the next call to a real adapter; no external effect has occurred.

    No adapter commit is performed. No file is written, no memory ledger is
    appended, no network is called. The trace stops at ``approval.granted`` (or
    earlier on rejection / pause). To actually commit, call the public
    adapter-specific entry point (``evaluate_file_write``, ``evaluate_memory_write``)
    with an explicit ``ApprovalDecision`` when approval is required.

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
        return (
            reject(trace, scope, None, RejectionReason.PROPOSAL_IS_NOT_AN_INTENT),
            trace,
        )

    intent = proposal.intent
    if intent.adapter == "file" and intent.operation == "write":
        return evaluate_file_write(
            scope,
            proposal,
            approval_granted=approval_granted,
            approval=approval,
            _stop_at_approval=True,
        )
    if intent.adapter == "memory" and intent.operation == "write":
        return evaluate_memory_write(
            scope,
            proposal,
            approval_granted=approval_granted,
            approval=approval,
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
        RejectionReason.UNSUPPORTED_ADAPTER_FOR_INTERPRET,
        adapter=intent.adapter,
        operation=intent.operation,
    ), trace
