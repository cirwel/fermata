"""Command line interface for local Fermata runtime records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fermata.file_adapter import evaluate_file_write
from fermata.interpreter import interpret as interpret_effect
from fermata.memory_adapter import evaluate_memory_write
from fermata.runtime_ir import (
    ApprovalAuthority,
    ApprovalDecision,
    ApprovalStatus,
    Intent,
    Proposal,
    Scope,
)


class CliError(ValueError):
    """Raised when CLI input records are malformed."""


def positive_int(value: Any, *, label: str) -> int:
    """Return a positive integer field value."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CliError(f"{label} must be a positive integer")
    return value


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from path."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CliError(f"{path} must contain a JSON object")
    return data


def require_string(record: dict[str, Any], field: str, *, label: str) -> str:
    """Return a required non-empty string field."""

    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise CliError(f"{label}.{field} must be a non-empty string")
    return value


def require_object(record: dict[str, Any], field: str, *, label: str) -> dict[str, Any]:
    """Return a required object field."""

    value = record.get(field)
    if not isinstance(value, dict):
        raise CliError(f"{label}.{field} must be an object")
    return value


def optional_string_list(record: dict[str, Any], field: str, *, label: str) -> list[str]:
    """Return an optional string array field."""

    value = record.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CliError(f"{label}.{field} must be an array of strings")
    return value


def intent_from_record(record: dict[str, Any]) -> Intent:
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
    )


def proposal_from_record(record: dict[str, Any]) -> Proposal:
    """Lower a canonical proposal record into the runtime dataclass."""

    if record.get("schema_version") != "0.1":
        raise CliError("proposal.schema_version must be 0.1")
    if record.get("record_type") != "proposal":
        raise CliError("proposal.record_type must be proposal")
    speech_act = require_string(record, "speech_act", label="proposal")
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
    record: dict[str, Any],
    *,
    sandbox_root: Path,
    max_bytes: int = 4096,
) -> Scope:
    """Lower a canonical scope record into the runtime dataclass."""

    if "schema_version" in record and record.get("schema_version") != "0.1":
        raise CliError("scope.schema_version must be 0.1")
    if record.get("record_type") not in {None, "scope"}:
        raise CliError("scope.record_type must be scope when present")
    raw_capabilities = record.get("capabilities")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise CliError("scope.capabilities must be a non-empty array")
    capabilities: set[str] = set()
    for index, capability in enumerate(raw_capabilities):
        if isinstance(capability, str) and capability:
            capabilities.add(capability)
            continue
        if not isinstance(capability, dict):
            raise CliError(f"scope.capabilities[{index}] must be an object")
        capabilities.add(
            require_string(capability, "name", label=f"capabilities[{index}]")
        )

    approval_required_for: set[str] = set()
    raw_required_approvals = record.get("approval_required_for", [])
    if raw_required_approvals:
        if not isinstance(raw_required_approvals, list) or not all(
            isinstance(item, str) for item in raw_required_approvals
        ):
            raise CliError("scope.approval_required_for must be an array of strings")
        approval_required_for.update(raw_required_approvals)

    raw_approvals = record.get("approvals", [])
    if raw_approvals:
        if not isinstance(raw_approvals, list):
            raise CliError("scope.approvals must be an array")
        for index, approval in enumerate(raw_approvals):
            if not isinstance(approval, dict):
                raise CliError(f"scope.approvals[{index}] must be an object")
            condition = approval.get("condition")
            if not isinstance(condition, str):
                raise CliError(f"scope.approvals[{index}].condition must be a string")
            matched = {
                capability for capability in capabilities if capability in condition
            }
            approval_required_for.update(matched or capabilities)

    return Scope(
        scope_id=require_string(record, "scope_id", label="scope"),
        sandbox_root=sandbox_root.resolve(),
        capabilities=frozenset(capabilities),
        approval_required_for=frozenset(approval_required_for),
        max_bytes=positive_int(
            record.get("max_bytes", max_bytes),
            label="scope.max_bytes",
        ),
    )


def approval_from_record(record: dict[str, Any]) -> ApprovalDecision:
    """Lower a canonical approval record into the runtime dataclass."""

    try:
        status = ApprovalStatus(require_string(record, "status", label="approval"))
        authority = ApprovalAuthority(
            require_string(record, "authority", label="approval")
        )
    except ValueError as exc:
        raise CliError(str(exc)) from exc
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


def approval_from_bundle_record(record: dict[str, Any]) -> ApprovalDecision:
    """Lower either a bare approval record or bundle wrapper."""

    if "approval" in record:
        return approval_from_record(require_object(record, "approval", label="bundle"))
    return approval_from_record(record)


def run_effect(
    mode: str,
    scope: Scope,
    proposal: Proposal,
    *,
    approval: ApprovalDecision | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one proposal and return public effect and trace records."""

    if mode == "interpret":
        effect, trace = interpret_effect(scope, proposal, approval=approval)
    elif mode == "run":
        intent = proposal.intent
        if (
            intent is not None
            and intent.adapter == "file"
            and intent.operation == "write"
        ):
            effect, trace = evaluate_file_write(scope, proposal, approval=approval)
        elif (
            intent is not None
            and intent.adapter == "memory"
            and intent.operation == "write"
        ):
            effect, trace = evaluate_memory_write(scope, proposal, approval=approval)
        else:
            effect, trace = interpret_effect(scope, proposal, approval=approval)
    else:  # pragma: no cover - protected by argparse choices.
        raise CliError(f"unknown mode {mode}")
    return effect.to_record(), trace.to_record()


def bundle_sandbox_root(scope_record: dict[str, Any], bundle_dir: Path) -> Path:
    """Return the sandbox root for a run bundle."""

    raw_sandbox_root = scope_record.get("sandbox_root")
    if raw_sandbox_root is None:
        return bundle_dir / "sandbox"
    if not isinstance(raw_sandbox_root, str) or not raw_sandbox_root:
        raise CliError("scope.sandbox_root must be a non-empty string when present")
    sandbox_root = Path(raw_sandbox_root)
    if sandbox_root.is_absolute():
        return sandbox_root
    return bundle_dir / sandbox_root


def write_json_object(path: Path, record: dict[str, Any], *, overwrite: bool) -> None:
    """Write a JSON object, refusing to overwrite prior evidence by default."""

    if path.exists() and not overwrite:
        raise CliError(f"{path} already exists; pass --overwrite to replace it")
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def require_writable_outputs(paths: list[Path], *, overwrite: bool) -> None:
    """Refuse to run a bundle when output evidence would be overwritten."""

    if overwrite:
        return
    for path in paths:
        if path.exists():
            raise CliError(f"{path} already exists; pass --overwrite to replace it")


def run_bundle(bundle_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    """Run one local alpha bundle and persist effect and trace records."""

    bundle_dir = bundle_dir.resolve()
    if not bundle_dir.is_dir():
        raise CliError(f"{bundle_dir} must be a bundle directory")

    scope_path = bundle_dir / "scope.json"
    proposal_path = bundle_dir / "proposal.json"
    approval_path = bundle_dir / "approval.json"
    effect_path = bundle_dir / "effect.json"
    trace_path = bundle_dir / "trace.json"
    require_writable_outputs([effect_path, trace_path], overwrite=overwrite)

    scope_record = read_json_object(scope_path)
    scope = scope_from_record(
        scope_record,
        sandbox_root=bundle_sandbox_root(scope_record, bundle_dir),
    )
    proposal = proposal_from_record(read_json_object(proposal_path))
    approval = (
        approval_from_bundle_record(read_json_object(approval_path))
        if approval_path.exists()
        else None
    )
    effect, trace = run_effect("run", scope, proposal, approval=approval)
    write_json_object(effect_path, effect, overwrite=overwrite)
    write_json_object(trace_path, trace, overwrite=overwrite)
    return {
        "status": "ok",
        "bundle": {
            "path": str(bundle_dir),
            "scope": str(scope_path),
            "proposal": str(proposal_path),
            "approval": str(approval_path),
            "effect": str(effect_path),
            "trace": str(trace_path),
        },
        "effect": effect,
        "trace": trace,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(
        prog="fermata",
        description="Evaluate local governed-effect JSON records.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("interpret", "run"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--scope", required=True, type=Path)
        subparser.add_argument("--proposal", required=True, type=Path)
        subparser.add_argument("--approval", type=Path)
        subparser.add_argument(
            "--sandbox-root",
            type=Path,
            help="sandbox root for relative runtime targets; defaults to scope file sibling sandbox/",
        )
        subparser.add_argument("--max-bytes", type=int, default=4096)

    bundle_parser = subparsers.add_parser("bundle")
    bundle_subparsers = bundle_parser.add_subparsers(
        dest="bundle_command",
        required=True,
    )
    bundle_run_parser = bundle_subparsers.add_parser("run")
    bundle_run_parser.add_argument("bundle_dir", type=Path)
    bundle_run_parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "bundle":
            output = run_bundle(args.bundle_dir, overwrite=args.overwrite)
        else:
            sandbox_root = (
                args.sandbox_root
                if args.sandbox_root is not None
                else args.scope.resolve().parent / "sandbox"
            )
            scope = scope_from_record(
                read_json_object(args.scope),
                sandbox_root=sandbox_root,
                max_bytes=args.max_bytes,
            )
            proposal = proposal_from_record(read_json_object(args.proposal))
            approval = (
                approval_from_record(read_json_object(args.approval))
                if args.approval is not None
                else None
            )
            effect, trace = run_effect(args.command, scope, proposal, approval=approval)
            output = {"status": "ok", "effect": effect, "trace": trace}
    except CliError as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            output,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
