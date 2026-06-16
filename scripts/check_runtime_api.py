"""Check the public Fermata runtime API surface."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from typing import Any

from fermata import RuntimeApiError, RuntimeOutput, interpret, run


def load_json(path: Path) -> dict[str, Any]:
    """Load a checked-in JSON object."""

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def event_types(output: RuntimeOutput) -> list[str]:
    """Return trace event type strings."""

    return [event["type"] for event in output.trace["events"]]


def assert_no_commit(output: RuntimeOutput) -> None:
    """Assert a runtime output did not cross the adapter commit boundary."""

    events = event_types(output)
    assert "adapter.commit.started" not in events
    assert "effect.committed" not in events
    assert "acknowledgement" not in output.effect
    assert "committed_at" not in output.effect


def check_file_api(repo: Path, root: Path) -> dict[str, Any]:
    """Exercise file.write through the public API."""

    scope = load_json(repo / "examples/local-alpha/file-scope.json")
    proposal = load_json(repo / "examples/local-alpha/file-write-proposal.json")
    approval = load_json(repo / "examples/local-alpha/file-write-approval.json")
    target = root / "file-api" / "cli-note.txt"

    paused = interpret(scope, proposal, sandbox_root=target.parent)
    assert paused.state == "paused"
    assert paused.effect["required_input"] == "approval_decision"
    assert not target.exists()
    assert_no_commit(paused)

    escaped_proposal = copy.deepcopy(proposal)
    escaped_proposal["proposal_id"] = "prop_runtime_api_escape_001"
    escaped_proposal["intent"]["intent_id"] = "intent_runtime_api_escape_001"
    escaped_proposal["intent"]["proposal_id"] = "prop_runtime_api_escape_001"
    escaped_proposal["intent"]["target"] = "../escape.txt"
    rejected = run(
        scope,
        escaped_proposal,
        approval=approval,
        sandbox_root=target.parent,
    )
    assert rejected.state == "rejected"
    assert rejected.effect["rejection_reason"] == "path_outside_scope"
    assert not (target.parent.parent / "escape.txt").exists()
    assert_no_commit(rejected)

    committed = run(scope, proposal, approval=approval, sandbox_root=target.parent)
    assert committed.state == "committed"
    assert target.read_text(encoding="utf-8") == (
        "Fermata CLI writes only through governed adapters.\n"
    )
    assert committed.effect["acknowledgement"]["adapter"] == "file"
    assert committed.effect["verification"]["status"] == "verified"
    assert "adapter.commit.started" in event_types(committed)
    assert "effect.committed" in event_types(committed)

    return {
        "committed_state": committed.state,
        "paused_state": paused.state,
        "rejected_reason": rejected.effect["rejection_reason"],
        "target_sha256": committed.effect["acknowledgement"]["sha256"],
    }


def check_memory_api(root: Path) -> dict[str, Any]:
    """Exercise memory.write through the public API."""

    scope: dict[str, Any] = {
        "scope_id": "runtime_api_memory_scope",
        "capabilities": ["memory.write"],
        "approval_required_for": ["memory.write"],
    }
    proposal: dict[str, Any] = {
        "schema_version": "0.1",
        "record_type": "proposal",
        "proposal_id": "prop_runtime_api_memory_001",
        "actor": "agent:runtime-api-check",
        "speech_act": "intend",
        "reason": "prove host applications can call memory.write",
        "confidence": 0.83,
        "evidence": ["script:check_runtime_api"],
        "payload": {
            "utterance": 'intend memory.write target:"project/runtime-api"'
        },
        "intent": {
            "intent_id": "intent_runtime_api_memory_001",
            "proposal_id": "prop_runtime_api_memory_001",
            "adapter": "memory",
            "operation": "write",
            "target": "project/runtime-api",
            "input": {
                "content": "Runtime API calls return public records.\n",
                "lifespan": "project",
                "provenance": ["script:check_runtime_api"],
            },
            "required_capability": "memory.write",
        },
    }
    approval: dict[str, Any] = {
        "status": "approved",
        "authority": "performer",
        "approval_id": "approval_runtime_api_memory_001",
        "approver": "performer:runtime-api-check",
        "decided_at": "2026-06-16T12:00:00Z",
        "scope_id": "runtime_api_memory_scope",
        "intent_id": "intent_runtime_api_memory_001",
        "reason": "approve checked local memory-write example",
    }
    paused = interpret(scope, proposal, sandbox_root=root / "memory-api")
    assert paused.state == "paused"
    assert_no_commit(paused)

    committed = run(
        scope,
        proposal,
        approval=approval,
        sandbox_root=root / "memory-api",
    )
    assert committed.state == "committed"
    assert committed.effect["acknowledgement"]["adapter"] == "memory"
    assert committed.effect["verification"]["status"] == "verified"
    assert Path(committed.effect["acknowledgement"]["store"]).exists()

    return {
        "committed_state": committed.state,
        "paused_state": paused.state,
        "record_id": committed.effect["acknowledgement"]["record_id"],
    }


def check_error_boundary() -> dict[str, Any]:
    """Prove malformed public records raise the public API error type."""

    try:
        interpret({"scope_id": "missing_capabilities"}, {"record_type": "proposal"})
    except RuntimeApiError as exc:
        missing_sandbox_error = str(exc)
    else:
        raise AssertionError("malformed records did not raise RuntimeApiError")

    try:
        run(["not", "a", "scope"], {"record_type": "proposal"}, sandbox_root="/tmp")
    except RuntimeApiError as exc:
        return {
            "error_type": type(exc).__name__,
            "missing_sandbox_message": missing_sandbox_error,
            "non_mapping_message": str(exc),
        }
    raise AssertionError("malformed records did not raise RuntimeApiError")


def main() -> int:
    """Run public API checks and print machine-readable evidence."""

    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="fermata_runtime_api_") as tmp:
        root = Path(tmp)
        file_result = check_file_api(repo, root)
        memory_result = check_memory_api(root)
        error_result = check_error_boundary()
    print(
        json.dumps(
            {
                "api": "runtime-api-v0",
                "checks": {
                    "file": file_result,
                    "memory": memory_result,
                    "malformed_records": error_result,
                },
                "status": "passed",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
