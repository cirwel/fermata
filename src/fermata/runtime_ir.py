"""Canonical v0 IR records and shared contract helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol


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


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    REQUESTED = "requested"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ApprovalAuthority(str, Enum):
    PERFORMER = "performer"
    COUNCIL = "council"
    RUNTIME = "runtime"
    NONE = "none"


class RejectionReason(str, Enum):
    PROPOSAL_IS_NOT_AN_INTENT = "proposal_is_not_an_intent"
    UNSUPPORTED_ADAPTER_OPERATION = "unsupported_adapter_operation"
    UNSUPPORTED_CAPABILITY_FOR_OPERATION = "unsupported_capability_for_operation"
    MISSING_CAPABILITY = "missing_capability"
    TARGET_MISSING_OR_NOT_STRING = "target_missing_or_not_string"
    INPUT_MISSING_OR_NOT_OBJECT = "input_missing_or_not_object"
    PATH_OUTSIDE_SCOPE = "path_outside_scope"
    TARGET_IS_SYMLINK = "target_is_symlink"
    PATH_COMPONENT_IS_SYMLINK = "path_component_is_symlink"
    CONTENT_MISSING_OR_NOT_STRING = "content_missing_or_not_string"
    INPUT_TOO_LARGE = "input_too_large"
    TARGET_IS_DIRECTORY = "target_is_directory"
    TARGET_EXISTS_NO_OVERWRITE = "target_exists_no_overwrite"
    ADAPTER_COMMIT_FAILED = "adapter_commit_failed"
    VERIFICATION_READ_FAILED = "verification_read_failed"
    VERIFICATION_FAILED_POST_COMMIT = "verification_failed_post_commit"
    MEMORY_TARGET_OUTSIDE_SCOPE = "memory_target_outside_scope"
    MEMORY_TARGET_RESERVED_SUFFIX = "memory_target_reserved_suffix"
    MEMORY_CONTENT_MISSING_OR_NOT_STRING = "memory_content_missing_or_not_string"
    MEMORY_PROVENANCE_INVALID = "memory_provenance_invalid"
    MEMORY_LIFESPAN_INVALID = "memory_lifespan_invalid"
    MEMORY_STORE_UNREADABLE = "memory_store_unreadable"
    MEMORY_RECORD_INVALID = "memory_record_invalid"
    UNSUPPORTED_ADAPTER_FOR_INTERPRET = "unsupported_adapter_for_interpret"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_SCOPE_MISMATCH = "approval_scope_mismatch"
    APPROVAL_INTENT_MISMATCH = "approval_intent_mismatch"
    APPROVAL_INTENT_HASH_MISMATCH = "approval_intent_hash_mismatch"
    APPROVAL_NOT_DECIDED = "approval_not_decided"
    APPROVAL_UNBOUND = "approval_unbound"
    NETWORK_URL_INVALID = "network_url_invalid"
    NETWORK_SCHEME_UNSUPPORTED = "network_scheme_unsupported"
    NETWORK_URL_NOT_IN_ALLOWLIST = "network_url_not_in_allowlist"
    NETWORK_HOST_IS_PRIVATE = "network_host_is_private"
    NETWORK_METHOD_NOT_ALLOWED = "network_method_not_allowed"
    NETWORK_REDIRECT_NOT_ALLOWED = "network_redirect_not_allowed"
    NETWORK_RESPONSE_TOO_LARGE = "network_response_too_large"
    NETWORK_REQUEST_FAILED = "network_request_failed"
    IDEMPOTENCY_KEY_CONFLICT = "idempotency_key_conflict"


SpeechAct = Literal["need", "claim", "doubt", "intend", "remember", "boundary"]


@dataclass(frozen=True)
class Scope:
    """Runtime boundary supplied by a governing performer or operator."""

    scope_id: str
    sandbox_root: Path
    capabilities: frozenset[str]
    approval_required_for: frozenset[str] = field(default_factory=frozenset)
    max_bytes: int = 4096
    # URL prefixes the network.fetch adapter may reach. Empty means no network
    # effect is authorized. A tuple (not list) so Scope stays hashable/frozen.
    network_allow: tuple[str, ...] = ()
    # Whether network.fetch may reach private / loopback / link-local
    # addresses. Default deny (SSRF guard); operators opt in for governing
    # fetches to local services.
    allow_private_network: bool = False


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
    # Optional retry-safety key. When set, the runtime commits the effect at
    # most once per (scope, key): a later proposal with the same key returns the
    # prior committed result instead of re-running the adapter. Excluded from
    # intent_sha256 when None so existing intent hashes are unchanged.
    #
    # At-most-once holds for SERIAL callers. The lookup and the record are not
    # held under one lock, so two concurrent commits with the same (scope, key)
    # can both miss and both commit (a double effect). That is acceptable for
    # the local-alpha single-writer model; multi-writer use would need a lock or
    # transactional store.
    idempotency_key: str | None = None


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


@dataclass(frozen=True)
class ApprovalDecision:
    """Typed approval record bound to a scope and intent."""

    status: ApprovalStatus
    authority: ApprovalAuthority
    approval_id: str | None = None
    approver: str | None = None
    decided_at: str | None = None
    expires_at: str | None = None
    scope_id: str | None = None
    intent_id: str | None = None
    intent_sha256: str | None = None
    reason: str | None = None

    def to_record(self) -> dict[str, Any]:
        """Return the canonical approval record shape."""

        record: dict[str, Any] = {
            "status": self.status.value,
            "authority": self.authority.value,
        }
        optional_fields = {
            "approval_id": self.approval_id,
            "approver": self.approver,
            "decided_at": self.decided_at,
            "expires_at": self.expires_at,
            "scope_id": self.scope_id,
            "intent_id": self.intent_id,
            "intent_sha256": self.intent_sha256,
            "reason": self.reason,
        }
        for key, value in optional_fields.items():
            if value is not None:
                record[key] = value
        return record


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
    approval: dict[str, Any] | None = None
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
            "approval": self.approval,
            "rejection_reason": self.rejection_reason,
            "required_input": self.required_input,
            "committed_at": self.committed_at,
        }
        for key, value in optional_fields.items():
            if value is not None:
                record[key] = to_jsonable(value)
        return record


@dataclass(frozen=True)
class AdapterPreparation:
    """Adapter-owned precommit evidence after shape and policy checks."""

    effect_kind: str
    commit_target: str
    checks: list[str]
    dry_run_summary: str
    dry_run_fields: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommitEvidence:
    """Adapter acknowledgement and verification for a committed effect."""

    acknowledgement: dict[str, Any]
    verification: dict[str, Any]
    committed_at: str


class GovernedAdapter(Protocol):
    """Small v0 adapter protocol used by the shared evaluator."""

    adapter: str
    operation: str
    capability: str

    def prepare(
        self,
        scope: Scope,
        proposal: Proposal,
        intent: Intent,
        trace: Trace,
    ) -> AdapterPreparation | EffectResult:
        """Validate adapter-specific input and render dry-run evidence."""

    def commit(
        self,
        scope: Scope,
        proposal: Proposal,
        intent: Intent,
        trace: Trace,
        preparation: AdapterPreparation,
    ) -> CommitEvidence | EffectResult:
        """Perform the adapter side effect and return verification evidence."""

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


def enum_value(value: str | Enum) -> str:
    """Return the public string value for enum-backed contract codes."""

    if isinstance(value, Enum):
        return str(value.value)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return a stable JSON encoding for hashing contract records."""

    return json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def intent_sha256(intent: Intent) -> str:
    """Return the stable hash for an intent record.

    A ``None`` ``idempotency_key`` is dropped before hashing so intents without
    a key hash exactly as they did before the field existed — preserving every
    previously issued approval binding. A set key participates in the hash, so
    the same operation with and without a key are distinct intents.
    """

    data = to_jsonable(intent)
    if isinstance(data, dict) and data.get("idempotency_key") is None:
        data.pop("idempotency_key", None)
    return sha256_bytes(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def parse_iso_timestamp(value: str) -> datetime:
    """Parse a JSON Schema date-time timestamp with optional Z suffix."""

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def approval_for(
    scope: Scope,
    intent: Intent,
    effect_kind: str,
    *,
    approval: ApprovalDecision | None = None,
    approval_granted: bool = False,
) -> ApprovalDecision:
    """Return an approval decision for the current transition.

    ``approval_granted`` is retained for legacy callers. Runtime paths that
    require performer or council authorization should pass an explicit
    ``ApprovalDecision`` so approval remains bound to the exact scope, intent,
    and intent hash.
    """

    if approval is not None:
        return approval

    required = effect_kind in scope.approval_required_for
    if required and not approval_granted:
        return ApprovalDecision(
            status=ApprovalStatus.REQUESTED,
            authority=ApprovalAuthority.PERFORMER,
            scope_id=scope.scope_id,
            intent_id=intent.intent_id,
            intent_sha256=intent_sha256(intent),
            reason="approval_required_before_commit",
        )
    if required:
        return ApprovalDecision(
            status=ApprovalStatus.APPROVED,
            authority=ApprovalAuthority.PERFORMER,
            approval_id=f"approval_{uuid.uuid4().hex[:8]}",
            approver="legacy:approval_granted",
            decided_at=now_timestamp(),
            scope_id=scope.scope_id,
            intent_id=intent.intent_id,
            intent_sha256=intent_sha256(intent),
            reason="legacy_boolean_approval_granted",
        )
    return ApprovalDecision(
        status=ApprovalStatus.NOT_REQUIRED,
        authority=ApprovalAuthority.RUNTIME,
        decided_at=now_timestamp(),
        scope_id=scope.scope_id,
        intent_id=intent.intent_id,
        intent_sha256=intent_sha256(intent),
    )


def make_approval_decision(
    scope: Scope,
    intent: Intent,
    *,
    approver: str,
    status: ApprovalStatus = ApprovalStatus.APPROVED,
    authority: ApprovalAuthority = ApprovalAuthority.PERFORMER,
    reason: str | None = None,
    approval_id: str | None = None,
    decided_at: str | None = None,
    expires_at: str | None = None,
) -> ApprovalDecision:
    """Build a canonical approval record bound to one scope and intent.

    Approval is an authorization decision, not technical verification. This
    helper records who held or released the boundary while binding that decision
    to the intent hash the runtime itself can verify.
    """

    return ApprovalDecision(
        status=status,
        authority=authority,
        approval_id=approval_id or f"approval_{uuid.uuid4().hex[:8]}",
        approver=approver,
        decided_at=decided_at or now_timestamp(),
        expires_at=expires_at,
        scope_id=scope.scope_id,
        intent_id=intent.intent_id,
        intent_sha256=intent_sha256(intent),
        reason=reason,
    )


def approval_rejection_reason(
    scope: Scope,
    intent: Intent,
    approval: ApprovalDecision,
) -> RejectionReason | None:
    """Validate an approval decision before adapter commit."""

    if approval.scope_id is not None and approval.scope_id != scope.scope_id:
        return RejectionReason.APPROVAL_SCOPE_MISMATCH
    if approval.intent_id is not None and approval.intent_id != intent.intent_id:
        return RejectionReason.APPROVAL_INTENT_MISMATCH
    if approval.intent_sha256 is not None and approval.intent_sha256 != intent_sha256(
        intent
    ):
        return RejectionReason.APPROVAL_INTENT_HASH_MISMATCH
    if approval.status == ApprovalStatus.DENIED:
        return RejectionReason.APPROVAL_DENIED
    if approval.status == ApprovalStatus.EXPIRED:
        return RejectionReason.APPROVAL_EXPIRED
    # A not-yet-decided approval must never authorize a commit. The runtime
    # pauses on REQUESTED upstream; this guards any direct caller of the
    # validator (e.g. a future adapter) from treating "requested" as "granted".
    if approval.status == ApprovalStatus.REQUESTED:
        return RejectionReason.APPROVAL_NOT_DECIDED
    # An approval that authorizes a commit must be bound to a specific intent
    # (by intent_id, intent_sha256, or both — each is checked for a match
    # above). A bare "approved" record bound to neither would authorize any
    # intent, even across scopes (replay/forgery). Scope_id alone is not enough:
    # it would still authorize any intent within that scope. Every legitimate
    # approval (make_approval_decision / approval_for) carries an intent
    # binding, so this rejects only unbound forgeries.
    if (
        approval.status == ApprovalStatus.APPROVED
        and approval.intent_id is None
        and approval.intent_sha256 is None
    ):
        return RejectionReason.APPROVAL_UNBOUND
    if approval.expires_at is not None:
        try:
            expires_at = parse_iso_timestamp(approval.expires_at)
        except ValueError:
            return RejectionReason.APPROVAL_EXPIRED
        if expires_at <= datetime.now(UTC):
            return RejectionReason.APPROVAL_EXPIRED
    return None


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
