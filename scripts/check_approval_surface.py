#!/usr/bin/env python3
"""Check the steward approval surface (``fermata approve``).

Drives the installed ``fermata`` console script through a paused bundle:
approve, deny, render-only, and the error paths. Asserts the stable contract a
non-coder steward depends on — a paused effect becomes committed on approval,
rejected on denial, and nothing commits without an explicit decision.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCOPE_RECORD = {
    "scope_id": "approval_surface_check",
    "sandbox_root": "sandbox",
    "capabilities": ["file.write"],
    "approval_required_for": ["file.write"],
}
PROPOSAL_RECORD = {
    "schema_version": "0.1",
    "record_type": "proposal",
    "proposal_id": "prop_approval_check_001",
    "actor": "agent:check",
    "speech_act": "intend",
    "reason": "exercise the steward approval surface",
    "intent": {
        "intent_id": "intent_approval_check_001",
        "proposal_id": "prop_approval_check_001",
        "adapter": "file",
        "operation": "write",
        "target": "approved-note.txt",
        "input": {"content": "Approved through the steward surface.\n"},
        "required_capability": "file.write",
    },
}


def write_object(path: Path, record: dict[str, Any]) -> None:
    """Write a JSON object."""

    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_paused_bundle(fermata: str, work_root: Path, name: str) -> Path:
    """Create a bundle and run it to the paused (awaiting-approval) state."""

    bundle = work_root / name
    bundle.mkdir()
    write_object(bundle / "scope.json", SCOPE_RECORD)
    write_object(bundle / "proposal.json", PROPOSAL_RECORD)
    output = run_json([fermata, "bundle", "run", str(bundle)])
    if output["effect"]["state"] != "paused":
        raise AssertionError(f"{name}: expected paused, got {output['effect']['state']!r}")
    return bundle


def run_json(command: list[str]) -> dict[str, Any]:
    """Run a command, require success, and parse JSON stdout."""

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return json.loads(result.stdout)


def run_expect_error(command: list[str], expected: str) -> None:
    """Run a command that should fail with a stable stderr fragment."""

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        raise AssertionError(f"command unexpectedly succeeded: {' '.join(command)}")
    if expected not in result.stderr:
        raise AssertionError(
            f"expected {expected!r} in stderr for {' '.join(command)}\n"
            f"stderr:\n{result.stderr}"
        )


def main() -> int:
    """Run the approval-surface checks against the installed CLI."""

    fermata = shutil.which("fermata")
    if fermata is None:
        print(
            "fermata console script not found on PATH; run: "
            "python3 -m pip install -e '.[dev]'",
            file=sys.stderr,
        )
        return 2

    with tempfile.TemporaryDirectory(prefix="fermata_approval_") as tmp:
        work_root = Path(tmp)

        # Approve: a paused effect commits, and the file side effect appears.
        approve_bundle = make_paused_bundle(fermata, work_root, "approve")
        approved = run_json(
            [fermata, "approve", str(approve_bundle), "--yes", "--approver", "operator:check"]
        )
        if approved["decision"] != "approve":
            raise AssertionError("approve: decision not recorded as approve")
        if approved["effect"]["state"] != "committed":
            raise AssertionError(
                f"approve: expected committed, got {approved['effect']['state']!r}"
            )
        target = approve_bundle / "sandbox" / "approved-note.txt"
        if target.read_text(encoding="utf-8") != PROPOSAL_RECORD["intent"]["input"]["content"]:
            raise AssertionError("approve: committed file content mismatch")
        # Re-approving an already-decided bundle is refused.
        run_expect_error(
            [fermata, "approve", str(approve_bundle), "--yes"],
            "not awaiting an approval decision",
        )

        # Deny: a paused effect is rejected and nothing is written.
        deny_bundle = make_paused_bundle(fermata, work_root, "deny")
        denied = run_json([fermata, "approve", str(deny_bundle), "--deny"])
        if denied["effect"]["state"] != "rejected":
            raise AssertionError(
                f"deny: expected rejected, got {denied['effect']['state']!r}"
            )
        if denied["effect"].get("rejection_reason") != "approval_denied":
            raise AssertionError("deny: rejection_reason must be approval_denied")
        if (deny_bundle / "sandbox" / "approved-note.txt").exists():
            raise AssertionError("deny: file was written despite denial")

        # Render-only: shows the pending summary without deciding.
        render_bundle = make_paused_bundle(fermata, work_root, "render")
        rendered = run_json([fermata, "approve", str(render_bundle), "--render-only"])
        if "pending" not in rendered or "agent:check" not in rendered["pending"]:
            raise AssertionError("render-only: pending summary missing")
        if rendered["effect"]["state"] != "paused":
            raise AssertionError("render-only: must not change effect state")

        # No decision, non-interactive: refused rather than silently committing.
        noflag_bundle = make_paused_bundle(fermata, work_root, "noflag")
        run_expect_error(
            [fermata, "approve", str(noflag_bundle)],
            "no approval decision provided",
        )

    print(
        json.dumps(
            {
                "status": "passed",
                "command": fermata,
                "checks": ["approve", "re_approve_refused", "deny", "render_only", "no_decision_refused"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
