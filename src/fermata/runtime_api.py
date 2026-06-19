"""Stable local runtime API for governed-effect records."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fermata.file_adapter import evaluate_file_write
from fermata.interpreter import interpret as interpret_effect
from fermata.memory_adapter import evaluate_memory_write
from fermata.network_adapter import evaluate_network_fetch
from fermata.runtime_ir import (
    ApprovalAuthority,
    ApprovalDecision,
    ApprovalStatus,
    EffectResult,
    Intent,
    Proposal,
    Scope,
    Trace,
)


class RuntimeApiError(ValueError):
    """Raised when public runtime API input records are malformed."""


# The only recognized approval-condition grammar is an explicit effect-kind
# equality, e.g. ``effect.kind == "file.write"``. Matching the capability name
# structurally (rather than by substring) keeps approval enrollment exact: a
# condition can only enroll a capability it names verbatim, and a condition
# that names no declared capability is rejected rather than silently enrolling
# every capability in scope.
_APPROVAL_CONDITION_RE = re.compile(r'effect\.kind\s*==\s*"([^"]+)"')


JsonObject = Mapping[str, Any]
RuntimeMode = Literal["interpret", "run"]


@dataclass(frozen=True)
class RuntimeOutput:
    """Public runtime output containing only effect and trace records."""

    effect: dict[str, Any]
    trace: dict[str, Any]

    @property
    def state(self) -> str:
        """Return the final effect state."""

        return str(self.effect["state"])

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-safe wrapper for callers that need one object."""

        return {"effect": self.effect, "trace": self.trace}


def positive_int(value: Any, *, label: str) -> int:
    """Return a positive integer field value."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeApiError(f"{label} must be a positive integer")
    return value


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from path."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeApiError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeApiError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeApiError(f"{path} must contain a JSON object")
    return data


def require_string(record: JsonObject, field: str, *, label: str) -> str:
    """Return a required non-empty string field."""

    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeApiError(f"{label}.{field} must be a non-empty string")
    return value


def require_object(record: JsonObject, field: str, *, label: str) -> dict[str, Any]:
    """Return a required object field."""

    value = record.get(field)
    if not isinstance(value, dict):
        raise RuntimeApiError(f"{label}.{field} must be an object")
    return value


def optional_string_list(record: JsonObject, field: str, *, label: str) -> list[str]:
    """Return an optional string array field."""

    value = record.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeApiError(f"{label}.{field} must be an array of strings")
    return value


def _optional_idempotency_key(record: JsonObject) -> str | None:
    """Read an optional idempotency_key, rejecting a malformed (non-string) value.

    Absent or null is fine (keyless). A present-but-non-string value is a
    malformed intent and is rejected rather than silently treated as keyless.
    """

    value = record.get("idempotency_key")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeApiError(
            "intent.idempotency_key must be a non-empty string when present"
        )
    return value


def intent_from_record(record: JsonObject) -> Intent:
    """Lower a canonical intent record into the runtime dataclass."""

    input_record = require_object(record, "input", label="intent")
    return Intent(
        intent_id=require_string(record, "intent_id", label="intent"),
        proposal_id=require_string(record, "proposal_id", label="intent"),
        adapter=require_string(record, "adapter", label="intent"),
        operation=require_string(record, "operation", label="intent"),
        target=require_string(record, "target", label="intent"),
        input=input_record,
        required_capability=require_string(
            record,
            "required_capability",
            label="intent",
        ),
        idempotency_key=_optional_idempotency_key(record),
    )


def proposal_from_record(record: JsonObject) -> Proposal:
    """Lower a canonical proposal record into the runtime dataclass."""

    if record.get("schema_version") != "0.1":
        raise RuntimeApiError("proposal.schema_version must be 0.1")
    if record.get("record_type") != "proposal":
        raise RuntimeApiError("proposal.record_type must be proposal")
    speech_act = require_string(record, "speech_act", label="proposal")
    if speech_act not in {"need", "claim", "doubt", "intend", "remember", "boundary"}:
        raise RuntimeApiError("proposal.speech_act must be a v0 speech act")
    intent = None
    if speech_act == "intend":
        intent = intent_from_record(require_object(record, "intent", label="proposal"))
    confidence_value = record.get("confidence")
    confidence = (
        float(confidence_value)
        if isinstance(confidence_value, (int, float))
        and not isinstance(confidence_value, bool)
        else None
    )
    return Proposal(
        proposal_id=require_string(record, "proposal_id", label="proposal"),
        actor=require_string(record, "actor", label="proposal"),
        speech_act=speech_act,  # type: ignore[arg-type]
        reason=record.get("reason") if isinstance(record.get("reason"), str) else None,
        confidence=confidence,
        evidence=optional_string_list(record, "evidence", label="proposal"),
        intent=intent,
    )


def scope_from_record(
    record: JsonObject,
    *,
    sandbox_root: Path,
    max_bytes: int = 4096,
) -> Scope:
    """Lower a canonical or local-alpha scope record into a runtime dataclass."""

    if "schema_version" in record and record.get("schema_version") != "0.1":
        raise RuntimeApiError("scope.schema_version must be 0.1")
    if record.get("record_type") not in {None, "scope"}:
        raise RuntimeApiError("scope.record_type must be scope when present")
    raw_capabilities = record.get("capabilities")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise RuntimeApiError("scope.capabilities must be a non-empty array")
    capabilities: set[str] = set()
    for index, capability in enumerate(raw_capabilities):
        if isinstance(capability, str) and capability:
            capabilities.add(capability)
            continue
        if not isinstance(capability, dict):
            raise RuntimeApiError(f"scope.capabilities[{index}] must be an object")
        capabilities.add(
            require_string(capability, "name", label=f"capabilities[{index}]")
        )

    approval_required_for: set[str] = set()
    raw_required_approvals = record.get("approval_required_for", [])
    if raw_required_approvals:
        if not isinstance(raw_required_approvals, list) or not all(
            isinstance(item, str) for item in raw_required_approvals
        ):
            raise RuntimeApiError(
                "scope.approval_required_for must be an array of strings"
            )
        approval_required_for.update(raw_required_approvals)

    raw_approvals = record.get("approvals", [])
    if raw_approvals:
        if not isinstance(raw_approvals, list):
            raise RuntimeApiError("scope.approvals must be an array")
        for index, approval in enumerate(raw_approvals):
            if not isinstance(approval, dict):
                raise RuntimeApiError(f"scope.approvals[{index}] must be an object")
            condition = approval.get("condition")
            if not isinstance(condition, str):
                raise RuntimeApiError(
                    f"scope.approvals[{index}].condition must be a string"
                )
            named = _APPROVAL_CONDITION_RE.findall(condition)
            if not named:
                raise RuntimeApiError(
                    f"scope.approvals[{index}].condition is not a recognized "
                    'approval condition; expected effect.kind == "<capability>", '
                    f"got: {condition!r}"
                )
            for capability in named:
                if capability not in capabilities:
                    raise RuntimeApiError(
                        f"scope.approvals[{index}].condition requires approval "
                        f"for capability {capability!r}, which is not declared "
                        "in scope.capabilities"
                    )
            approval_required_for.update(named)

    raw_network_allow = record.get("network_allow", [])
    if raw_network_allow:
        if not isinstance(raw_network_allow, list) or not all(
            isinstance(item, str) and item for item in raw_network_allow
        ):
            raise RuntimeApiError(
                "scope.network_allow must be an array of non-empty strings"
            )
    network_allow = tuple(raw_network_allow)

    raw_allow_private = record.get("allow_private_network", False)
    if not isinstance(raw_allow_private, bool):
        raise RuntimeApiError("scope.allow_private_network must be a boolean")

    raw_content_types = record.get("network_allowed_content_types", [])
    if raw_content_types:
        if not isinstance(raw_content_types, list) or not all(
            isinstance(item, str) and item for item in raw_content_types
        ):
            raise RuntimeApiError(
                "scope.network_allowed_content_types must be an array of "
                "non-empty strings"
            )
    network_allowed_content_types = tuple(raw_content_types)

    raw_max_effects = record.get("max_effects_per_window", 0)
    if not isinstance(raw_max_effects, int) or isinstance(raw_max_effects, bool) or (
        raw_max_effects < 0
    ):
        raise RuntimeApiError(
            "scope.max_effects_per_window must be a non-negative integer"
        )
    raw_rate_window = record.get("rate_window_seconds", 0)
    if isinstance(raw_rate_window, bool) or not isinstance(
        raw_rate_window, (int, float)
    ):
        raise RuntimeApiError("scope.rate_window_seconds must be a number")
    if raw_max_effects > 0 and raw_rate_window <= 0:
        raise RuntimeApiError(
            "scope.rate_window_seconds must be > 0 when "
            "max_effects_per_window is set"
        )

    return Scope(
        scope_id=require_string(record, "scope_id", label="scope"),
        sandbox_root=sandbox_root.resolve(),
        capabilities=frozenset(capabilities),
        approval_required_for=frozenset(approval_required_for),
        max_bytes=positive_int(
            record.get("max_bytes", max_bytes),
            label="scope.max_bytes",
        ),
        network_allow=network_allow,
        allow_private_network=raw_allow_private,
        network_allowed_content_types=network_allowed_content_types,
        max_effects_per_window=raw_max_effects,
        rate_window_seconds=float(raw_rate_window),
    )


def approval_from_record(record: JsonObject) -> ApprovalDecision:
    """Lower a canonical approval record into the runtime dataclass."""

    try:
        status = ApprovalStatus(require_string(record, "status", label="approval"))
        authority = ApprovalAuthority(
            require_string(record, "authority", label="approval")
        )
    except ValueError as exc:
        raise RuntimeApiError(str(exc)) from exc
    return ApprovalDecision(
        status=status,
        authority=authority,
        approval_id=(
            record.get("approval_id")
            if isinstance(record.get("approval_id"), str)
            else None
        ),
        approver=(
            record.get("approver") if isinstance(record.get("approver"), str) else None
        ),
        decided_at=(
            record.get("decided_at")
            if isinstance(record.get("decided_at"), str)
            else None
        ),
        expires_at=(
            record.get("expires_at")
            if isinstance(record.get("expires_at"), str)
            else None
        ),
        scope_id=(
            record.get("scope_id") if isinstance(record.get("scope_id"), str) else None
        ),
        intent_id=(
            record.get("intent_id") if isinstance(record.get("intent_id"), str) else None
        ),
        intent_sha256=(
            record.get("intent_sha256")
            if isinstance(record.get("intent_sha256"), str)
            else None
        ),
        reason=record.get("reason") if isinstance(record.get("reason"), str) else None,
    )


def approval_from_bundle_record(record: JsonObject) -> ApprovalDecision:
    """Lower either a bare approval record or bundle wrapper."""

    if "approval" in record:
        return approval_from_record(require_object(record, "approval", label="bundle"))
    return approval_from_record(record)


def coerce_scope(
    scope: Scope | JsonObject,
    *,
    sandbox_root: Path | str | None = None,
    max_bytes: int = 4096,
) -> Scope:
    """Return a runtime scope from either a Scope object or public record."""

    if isinstance(scope, Scope):
        return scope
    if not isinstance(scope, Mapping):
        raise RuntimeApiError("scope must be a Scope object or JSON object")
    if sandbox_root is None:
        raise RuntimeApiError("sandbox_root is required when scope is a record")
    return scope_from_record(
        scope,
        sandbox_root=Path(sandbox_root),
        max_bytes=max_bytes,
    )


def coerce_proposal(proposal: Proposal | JsonObject) -> Proposal:
    """Return a runtime proposal from either a Proposal object or public record."""

    if isinstance(proposal, Proposal):
        return proposal
    if not isinstance(proposal, Mapping):
        raise RuntimeApiError("proposal must be a Proposal object or JSON object")
    return proposal_from_record(proposal)


def coerce_approval(
    approval: ApprovalDecision | JsonObject | None,
) -> ApprovalDecision | None:
    """Return a runtime approval decision from an object, record, or None."""

    if approval is None or isinstance(approval, ApprovalDecision):
        return approval
    if not isinstance(approval, Mapping):
        raise RuntimeApiError(
            "approval must be an ApprovalDecision object or JSON object"
        )
    return approval_from_bundle_record(approval)


def output_from_effect(effect: EffectResult, trace: Trace) -> RuntimeOutput:
    """Return the public API output for internal runtime objects."""

    return RuntimeOutput(effect=effect.to_record(), trace=trace.to_record())


def evaluate(
    mode: RuntimeMode,
    scope: Scope | JsonObject,
    proposal: Proposal | JsonObject,
    *,
    approval: ApprovalDecision | JsonObject | None = None,
    sandbox_root: Path | str | None = None,
    max_bytes: int = 4096,
) -> RuntimeOutput:
    """Evaluate one proposal and return public effect and trace records."""

    runtime_scope = coerce_scope(
        scope,
        sandbox_root=sandbox_root,
        max_bytes=max_bytes,
    )
    runtime_proposal = coerce_proposal(proposal)
    runtime_approval = coerce_approval(approval)
    if mode == "interpret":
        effect, trace = interpret_effect(
            runtime_scope,
            runtime_proposal,
            approval=runtime_approval,
        )
    elif mode == "run":
        intent = runtime_proposal.intent
        if (
            intent is not None
            and intent.adapter == "file"
            and intent.operation == "write"
        ):
            effect, trace = evaluate_file_write(
                runtime_scope,
                runtime_proposal,
                approval=runtime_approval,
            )
        elif (
            intent is not None
            and intent.adapter == "memory"
            and intent.operation == "write"
        ):
            effect, trace = evaluate_memory_write(
                runtime_scope,
                runtime_proposal,
                approval=runtime_approval,
            )
        elif (
            intent is not None
            and intent.adapter == "network"
            and intent.operation == "fetch"
        ):
            effect, trace = evaluate_network_fetch(
                runtime_scope,
                runtime_proposal,
                approval=runtime_approval,
            )
        else:
            effect, trace = interpret_effect(
                runtime_scope,
                runtime_proposal,
                approval=runtime_approval,
            )
    else:
        raise RuntimeApiError(f"unknown runtime mode {mode}")
    return output_from_effect(effect, trace)


def interpret(
    scope: Scope | JsonObject,
    proposal: Proposal | JsonObject,
    *,
    approval: ApprovalDecision | JsonObject | None = None,
    sandbox_root: Path | str | None = None,
    max_bytes: int = 4096,
) -> RuntimeOutput:
    """Interpret a proposal without committing an external-world effect."""

    return evaluate(
        "interpret",
        scope,
        proposal,
        approval=approval,
        sandbox_root=sandbox_root,
        max_bytes=max_bytes,
    )


def run(
    scope: Scope | JsonObject,
    proposal: Proposal | JsonObject,
    *,
    approval: ApprovalDecision | JsonObject | None = None,
    sandbox_root: Path | str | None = None,
    max_bytes: int = 4096,
) -> RuntimeOutput:
    """Run a proposal through a governed adapter when policy allows it."""

    return evaluate(
        "run",
        scope,
        proposal,
        approval=approval,
        sandbox_root=sandbox_root,
        max_bytes=max_bytes,
    )


__all__ = [
    "RuntimeApiError",
    "RuntimeMode",
    "RuntimeOutput",
    "approval_from_bundle_record",
    "approval_from_record",
    "coerce_approval",
    "coerce_proposal",
    "coerce_scope",
    "evaluate",
    "intent_from_record",
    "interpret",
    "output_from_effect",
    "positive_int",
    "proposal_from_record",
    "read_json_object",
    "require_object",
    "require_string",
    "run",
    "scope_from_record",
]
