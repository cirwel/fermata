"""Governed effect runtime primitives for the v0 file-write adapter.

The module is intentionally small: one scope type, one proposal/intent shape,
one file adapter, and enough trace evidence to make "committed" a runtime fact
rather than an agent claim.
"""

from __future__ import annotations

import hashlib
import json
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
) -> tuple[EffectResult, Trace]:
    """Evaluate one governed file-write proposal end to end."""

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

    if intent.required_capability not in scope.capabilities:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "missing_capability",
            required_capability=intent.required_capability,
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
    trace.add("adapter.commit.started", adapter="file", target=str(target_path))

    temp_path: Path | None = None
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_bytes(content_bytes)
        temp_path.replace(target_path)
        readback = target_path.read_bytes()
    except OSError as exc:
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

    output_hash = sha256_bytes(readback)
    if output_hash != input_hash:
        return reject(
            trace,
            scope,
            intent.intent_id,
            "read_back_hash_mismatch",
            input_sha256=input_hash,
            output_sha256=output_hash,
        ), trace

    ack = {
        "adapter": "file",
        "target": str(target_path),
        "handle": str(target_path),
        "sha256": output_hash,
        "bytes": len(readback),
    }
    verification = {
        "status": "verified",
        "method": "read_back_sha256",
        "detail": {"sha256": output_hash, "bytes": len(readback)},
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

        escaped, escaped_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("../secrets.txt"),
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

    return results


def main() -> None:
    """Run the spike self-tests and print JSON evidence."""

    results = run_self_tests()
    print(json.dumps(results, indent=2, sort_keys=True))
