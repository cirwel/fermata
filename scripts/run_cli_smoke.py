#!/usr/bin/env python3
"""Smoke-test the installed ``fermata`` console script."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def run_json(command: list[str]) -> dict[str, Any]:
    """Run a command, require success, and parse JSON stdout."""

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"command did not emit JSON: {' '.join(command)}\n{result.stdout}"
        ) from exc
    if not isinstance(data, dict):
        raise AssertionError(f"command emitted non-object JSON: {' '.join(command)}")
    return data


def event_types(output: dict[str, Any]) -> list[str]:
    """Return trace event type strings from CLI output."""

    events = output.get("trace", {}).get("events", [])
    if not isinstance(events, list):
        raise AssertionError("trace.events must be a list")
    types = []
    for index, event in enumerate(events):
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise AssertionError(f"trace event {index} missing string type")
        types.append(event["type"])
    return types


def main() -> int:
    """Run the CLI smoke and print machine-readable evidence."""

    fermata = shutil.which("fermata")
    if fermata is None:
        print(
            "fermata console script not found on PATH; run: "
            "python3 -m pip install -e '.[dev]'",
            file=sys.stderr,
        )
        return 2

    root = repo_root()
    scope = root / "examples" / "local-alpha" / "file-scope.json"
    proposal = root / "examples" / "local-alpha" / "file-write-proposal.json"
    approval = root / "examples" / "local-alpha" / "file-write-approval.json"
    source_bundle = root / "examples" / "local-alpha" / "run-bundle"
    expected_content = "Fermata CLI writes only through governed adapters.\n"

    with tempfile.TemporaryDirectory(prefix="fermata_cli_smoke_") as tmp:
        sandbox_root = Path(tmp) / "sandbox"
        target = sandbox_root / "cli-note.txt"
        interpreted = run_json(
            [
                fermata,
                "interpret",
                "--scope",
                str(scope),
                "--proposal",
                str(proposal),
                "--sandbox-root",
                str(sandbox_root),
            ]
        )
        assert interpreted["status"] == "ok"
        assert interpreted["effect"]["state"] == "paused"
        assert interpreted["effect"]["required_input"] == "approval_decision"
        interpreted_events = event_types(interpreted)
        assert "approval.requested" in interpreted_events
        assert "adapter.commit.started" not in interpreted_events
        assert "effect.committed" not in interpreted_events
        assert not target.exists()

        committed = run_json(
            [
                fermata,
                "run",
                "--scope",
                str(scope),
                "--proposal",
                str(proposal),
                "--approval",
                str(approval),
                "--sandbox-root",
                str(sandbox_root),
            ]
        )
        assert committed["status"] == "ok"
        assert committed["effect"]["state"] == "committed"
        assert committed["effect"]["acknowledgement"]["adapter"] == "file"
        assert committed["effect"]["verification"]["status"] == "verified"
        committed_events = event_types(committed)
        assert "adapter.commit.started" in committed_events
        assert "effect.committed" in committed_events
        assert target.read_text(encoding="utf-8") == expected_content

        bundle = Path(tmp) / "run-bundle"
        shutil.copytree(source_bundle, bundle)
        bundle_target = bundle / "sandbox" / "bundle-note.txt"
        bundle_output = run_json([fermata, "bundle", "run", str(bundle)])
        assert bundle_output["status"] == "ok"
        assert bundle_output["effect"]["state"] == "paused"
        assert bundle_output["effect"]["required_input"] == "approval_decision"
        bundle_events = event_types(bundle_output)
        assert "approval.requested" in bundle_events
        assert "adapter.commit.started" not in bundle_events
        assert (bundle / "effect.json").exists()
        assert (bundle / "trace.json").exists()
        assert not bundle_target.exists()

        evidence = {
            "status": "passed",
            "command": fermata,
            "checks": {
                "interpret_state": interpreted["effect"]["state"],
                "interpret_target_absent": True,
                "run_state": committed["effect"]["state"],
                "acknowledgement_adapter": committed["effect"]["acknowledgement"][
                    "adapter"
                ],
                "verification_status": committed["effect"]["verification"]["status"],
                "target_content_sha256": committed["effect"]["acknowledgement"][
                    "sha256"
                ],
                "bundle_state": bundle_output["effect"]["state"],
                "bundle_target_absent": True,
            },
        }
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
