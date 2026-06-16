"""Bridge tongue utterances into the governed runtime as typed proposals.

The tongue parser (``tongue_parser.parse_line``) turns a spoken public speech
act — need, claim, doubt, remember, boundary — into a proposal record. This
module routes that proposal through the governed runtime's result/trace
machinery, producing a ``PROPOSAL``-state effect result and a durable trace.

It does **not** commit anything: speech acts are not effects. An acknowledged
proposal is a recorded, traceable "the runtime heard this" — nothing crosses
the world boundary.

Effect ``intend`` records are intentionally out of scope here. Per the v0
charter (see ``tongue_parser``), an intent must arrive as a JSON-Schema
validated record and run through ``runtime_api.run`` / ``interpret`` — it is
never lowered from a one-line utterance. ``propose_from_utterance`` makes that
boundary explicit and refuses to fabricate an intent from speech.
"""

from __future__ import annotations

import uuid
from typing import Any

from fermata.runtime_api import RuntimeApiError, proposal_from_record
from fermata.runtime_ir import EffectResult, EffectState, Proposal, Trace
from fermata.tongue_parser import parse_line

# The speech acts the bridge will acknowledge. ``intend`` is deliberately
# excluded: effects are governed through the JSON intent path, not spoken.
ACKNOWLEDGEABLE_SPEECH_ACTS = frozenset(
    {"need", "claim", "doubt", "remember", "boundary"}
)


class TongueBridgeError(ValueError):
    """Raised when an utterance cannot be routed into the governed runtime."""


def acknowledge_proposal(
    proposal: Proposal,
    *,
    scope_id: str = "unscoped",
    detail: dict[str, Any] | None = None,
) -> tuple[EffectResult, Trace]:
    """Acknowledge a non-intent proposal as a traced ``PROPOSAL``-state result.

    The result never carries an adapter acknowledgement or verification: a
    speech act is recorded, not committed. ``detail`` is merged into the
    ``proposal.acknowledged`` trace event for operator legibility (e.g. a
    boundary's offer, a need's capability and target).

    Raises ``TongueBridgeError`` for an ``intend`` proposal — route it through
    the JSON intent path instead — or for any unrecognized speech act.
    """

    if proposal.speech_act == "intend":
        raise TongueBridgeError(
            "effect intents are not acknowledged by the tongue bridge; supply "
            "the intent as a JSON proposal and run it through "
            "runtime_api.run / interpret"
        )
    if proposal.speech_act not in ACKNOWLEDGEABLE_SPEECH_ACTS:
        raise TongueBridgeError(
            f"unsupported speech act for acknowledgement: {proposal.speech_act!r}"
        )

    trace = Trace(trace_id=f"trace_{uuid.uuid4().hex[:8]}")
    trace.add(
        "proposal.received",
        proposal_id=proposal.proposal_id,
        speech_act=proposal.speech_act,
        actor=proposal.actor,
    )
    acknowledged_fields: dict[str, Any] = {
        "proposal_id": proposal.proposal_id,
        "speech_act": proposal.speech_act,
    }
    if detail:
        acknowledged_fields.update(detail)
    trace.add("proposal.acknowledged", **acknowledged_fields)

    result = EffectResult(
        state=EffectState.PROPOSAL,
        trace_id=trace.trace_id,
        effect_id=f"effect_{uuid.uuid4().hex[:8]}",
        intent_id=None,
        scope_id=scope_id,
    )
    return result, trace


def _acknowledgement_detail(record: dict[str, Any], speech_act: str) -> dict[str, Any]:
    """Extract a small legible detail from a parsed record's payload.

    ``proposal_from_record`` drops the payload when it lowers to a typed
    ``Proposal``, so the detail is read from the original record here.
    """

    payload = record.get("payload")
    if not isinstance(payload, dict):
        return {}
    detail: dict[str, Any] = {}
    if speech_act == "boundary" and isinstance(payload.get("offer"), str):
        detail["offer"] = payload["offer"]
    if speech_act == "need" and isinstance(payload.get("need"), dict):
        need = payload["need"]
        if isinstance(need.get("capability"), str):
            detail["capability"] = need["capability"]
        if isinstance(need.get("target"), str):
            detail["target"] = need["target"]
    return detail


def propose_from_utterance(
    line: str,
    *,
    actor: str = "agent:hermes",
    scope_id: str = "unscoped",
) -> tuple[EffectResult, Trace]:
    """Parse a tongue line and acknowledge it as a governed proposal.

    Returns the ``(EffectResult, Trace)`` pair for the acknowledged speech act.
    Raises ``TongueBridgeError`` for an ``intend`` line (which must be supplied
    as JSON) or for any utterance the v0 tongue parser does not recognize.
    """

    try:
        record = parse_line(line, actor)
    except ValueError as exc:
        if line.strip().startswith("intend"):
            raise TongueBridgeError(
                "effect intents must be supplied as a JSON proposal and run "
                "through runtime_api.run / interpret, not spoken as a tongue line"
            ) from exc
        raise TongueBridgeError(str(exc)) from exc

    try:
        proposal = proposal_from_record(record)
    except RuntimeApiError as exc:  # pragma: no cover - parser keeps records valid
        raise TongueBridgeError(str(exc)) from exc

    detail = _acknowledgement_detail(record, proposal.speech_act)
    return acknowledge_proposal(proposal, scope_id=scope_id, detail=detail)
