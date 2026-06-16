"""Command line interface for local Fermata runtime records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fermata.runtime_api import (
    RuntimeApiError as CliError,
    approval_from_bundle_record,
    approval_from_record,
    interpret as interpret_runtime,
    proposal_from_record,
    read_json_object,
    run as run_runtime,
    scope_from_record,
)
from fermata.runtime_ir import (
    ApprovalDecision,
    ApprovalStatus,
    Proposal,
    Scope,
    make_approval_decision,
)
from fermata.service_records import ServiceRecordsError, export_service_records


def run_effect(
    mode: str,
    scope: Scope,
    proposal: Proposal,
    *,
    approval: ApprovalDecision | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one proposal and return public effect and trace records."""

    if mode == "interpret":
        output = interpret_runtime(scope, proposal, approval=approval)
    elif mode == "run":
        output = run_runtime(scope, proposal, approval=approval)
    else:  # pragma: no cover - protected by argparse choices.
        raise CliError(f"unknown mode {mode}")
    return output.effect, output.trace


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


def read_pending_approval(bundle_dir: Path) -> tuple[dict[str, Any], Scope, Proposal]:
    """Load a bundle that is paused awaiting an approval decision.

    Raises ``CliError`` if the bundle has not been run, is not paused for
    approval, or carries no intent to approve.
    """

    effect_path = bundle_dir / "effect.json"
    if not effect_path.exists():
        raise CliError(
            f"{effect_path} not found; run `fermata bundle run` first so there "
            "is a pending effect to approve"
        )
    effect = read_json_object(effect_path)
    if effect.get("state") != "paused" or effect.get("required_input") != "approval_decision":
        raise CliError(
            "bundle is not awaiting an approval decision "
            f"(state={effect.get('state')!r}, required_input="
            f"{effect.get('required_input')!r})"
        )

    scope_path = bundle_dir / "scope.json"
    proposal_path = bundle_dir / "proposal.json"
    scope_record = read_json_object(scope_path)
    scope = scope_from_record(
        scope_record,
        sandbox_root=bundle_sandbox_root(scope_record, bundle_dir),
    )
    proposal = proposal_from_record(read_json_object(proposal_path))
    if proposal.intent is None:
        raise CliError("proposal has no intent to approve")
    return effect, scope, proposal


def render_pending_approval(proposal: Proposal, scope: Scope) -> str:
    """Render a plain-English summary of the effect awaiting approval."""

    intent = proposal.intent
    assert intent is not None  # guaranteed by read_pending_approval
    content = intent.input.get("content") if isinstance(intent.input, dict) else None
    size = f"{len(content)} bytes" if isinstance(content, str) else "no content"
    return (
        f"{proposal.actor} wants to {intent.operation} "
        f"{intent.adapter}:{intent.target} ({size}) "
        f"under scope {scope.scope_id!r}, which requires your approval. "
        f"Capability: {intent.required_capability}."
    )


def approve_bundle(
    bundle_dir: Path,
    *,
    decision: str,
    approver: str,
) -> dict[str, Any]:
    """Record an approval decision for a paused bundle and re-run it.

    ``decision`` is ``"approve"`` or ``"deny"``. The decision is written as a
    canonical approval record bound to the bundle's scope and intent hash, then
    the bundle is re-run so ``effect.json``/``trace.json`` reflect the outcome.
    """

    bundle_dir = bundle_dir.resolve()
    if not bundle_dir.is_dir():
        raise CliError(f"{bundle_dir} must be a bundle directory")
    if decision not in {"approve", "deny"}:
        raise CliError(f"unknown decision {decision!r}; expected approve or deny")

    _, scope, proposal = read_pending_approval(bundle_dir)
    status = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.DENIED
    approval = make_approval_decision(
        scope,
        proposal.intent,
        approver=approver,
        status=status,
        reason=f"operator_{decision}",
    )
    approval_path = bundle_dir / "approval.json"
    write_json_object(approval_path, approval.to_record(), overwrite=True)
    result = run_bundle(bundle_dir, overwrite=True)
    return {
        "status": "ok",
        "decision": decision,
        "approver": approver,
        "approval": str(approval_path),
        "effect": result["effect"],
        "trace": result["trace"],
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

    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("bundle_dir", type=Path)
    approve_parser.add_argument(
        "--approver",
        default="operator:cli",
        help="who is recording the decision; stored in the approval record",
    )
    approve_parser.add_argument(
        "--render-only",
        action="store_true",
        help="print the pending approval summary and exit without deciding",
    )
    decision_group = approve_parser.add_mutually_exclusive_group()
    decision_group.add_argument(
        "--yes",
        action="store_true",
        help="approve without prompting (required for non-interactive use)",
    )
    decision_group.add_argument(
        "--deny",
        action="store_true",
        help="deny without prompting",
    )

    service_parser = subparsers.add_parser("service")
    service_subparsers = service_parser.add_subparsers(
        dest="service_command",
        required=True,
    )
    service_run_parser = service_subparsers.add_parser("run")
    service_run_parser.add_argument("--host", default="127.0.0.1")
    service_run_parser.add_argument("--port", type=int, default=8765)
    service_run_parser.add_argument("--service-root", required=True, type=Path)
    service_records_parser = service_subparsers.add_parser("records")
    service_records_parser.add_argument("--service-root", required=True, type=Path)
    service_records_parser.add_argument("--request-id")
    service_records_parser.add_argument("--include-payload", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "service":
            if args.service_command == "run":
                from fermata.service import run_service

                return run_service(
                    host=args.host,
                    port=args.port,
                    service_root=args.service_root,
                )
            output = export_service_records(
                service_root=args.service_root,
                request_id=args.request_id,
                include_payload=args.include_payload,
            )
        elif args.command == "bundle":
            output = run_bundle(args.bundle_dir, overwrite=args.overwrite)
        elif args.command == "approve":
            bundle_dir = args.bundle_dir.resolve()
            effect, scope, proposal = read_pending_approval(bundle_dir)
            summary = render_pending_approval(proposal, scope)
            if args.render_only:
                output = {"status": "ok", "pending": summary, "effect": effect}
            else:
                if args.deny:
                    decision = "deny"
                elif args.yes:
                    decision = "approve"
                elif sys.stdin.isatty():
                    print(summary, file=sys.stderr)
                    answer = input("Approve this effect? [y/N] ").strip().lower()
                    decision = "approve" if answer in {"y", "yes"} else "deny"
                else:
                    raise CliError(
                        "no approval decision provided; pass --yes or --deny for "
                        "non-interactive use"
                    )
                output = approve_bundle(
                    bundle_dir, decision=decision, approver=args.approver
                )
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
    except (CliError, ServiceRecordsError) as exc:
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
