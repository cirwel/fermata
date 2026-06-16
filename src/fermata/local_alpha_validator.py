"""One-command local alpha readiness validation."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Gate:
    """One local alpha validation gate."""

    name: str
    command: list[str]
    parses_json: bool = False


def repo_root() -> Path:
    """Return the source checkout root when available."""

    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "scripts").exists() and (source_root / "references").exists():
        return source_root
    return Path.cwd()


def gates() -> list[Gate]:
    """Return the current local alpha gates in execution order."""

    python = sys.executable
    return [
        Gate("compileall", [python, "-m", "compileall", "scripts", "src"]),
        Gate(
            "schema_json",
            [
                python,
                "-m",
                "json.tool",
                "references/governed-effect-ir-v0.schema.json",
            ],
        ),
        Gate(
            "golden_json",
            [python, "-m", "json.tool", "references/tongue-golden-tests-v0.json"],
        ),
        Gate(
            "golden_checks",
            [python, "scripts/run_tongue_golden_tests.py"],
            parses_json=True,
        ),
        Gate(
            "cli_smoke",
            [python, "scripts/run_cli_smoke.py"],
            parses_json=True,
        ),
        Gate(
            "run_bundle_contract",
            [python, "scripts/check_run_bundle_contract.py"],
            parses_json=True,
        ),
        Gate(
            "runtime_api",
            [python, "scripts/check_runtime_api.py"],
            parses_json=True,
        ),
        Gate(
            "local_service",
            [python, "scripts/check_local_service.py"],
            parses_json=True,
        ),
        Gate(
            "package_build",
            [python, "scripts/check_package_build.py"],
            parses_json=True,
        ),
        Gate("diff_check", ["git", "diff", "--check"]),
    ]


def parse_stdout_json(gate: Gate, stdout: str) -> dict[str, Any] | None:
    """Parse a gate's stdout JSON when requested."""

    if not gate.parses_json:
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"status": "invalid_json", "error": str(exc)}
    if not isinstance(data, dict):
        return {"status": "invalid_json", "error": "stdout JSON was not an object"}
    return data


def run_gate(gate: Gate, *, cwd: Path) -> dict[str, Any]:
    """Run one validation gate and return machine-readable evidence."""

    started = time.monotonic()
    result = subprocess.run(
        gate.command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed_ms = round((time.monotonic() - started) * 1000)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    parsed = parse_stdout_json(gate, stdout)
    record: dict[str, Any] = {
        "name": gate.name,
        "command": gate.command,
        "returncode": result.returncode,
        "elapsed_ms": elapsed_ms,
        "status": "passed" if result.returncode == 0 else "failed",
    }
    if parsed is not None:
        record["stdout_json"] = parsed
        if parsed.get("status") not in {None, "passed"}:
            record["status"] = "failed"
    if result.returncode != 0 or record["status"] != "passed":
        record["stdout_tail"] = stdout[-4000:]
        record["stderr_tail"] = stderr[-4000:]
    return record


def run_validation(*, cwd: Path | None = None) -> dict[str, Any]:
    """Run local alpha validation and return one JSON-safe summary."""

    root = cwd or repo_root()
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    for gate in gates():
        evidence = run_gate(gate, cwd=root)
        results.append(evidence)
        if evidence["status"] != "passed":
            break

    failed = [gate for gate in results if gate["status"] != "passed"]
    status = "passed" if not failed and len(results) == len(gates()) else "failed"
    return {
        "status": status,
        "checked": [gate["name"] for gate in results],
        "passed": [gate["name"] for gate in results if gate["status"] == "passed"],
        "failed": [gate["name"] for gate in failed],
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "gates": results,
    }


def main() -> int:
    """CLI entry point."""

    summary = run_validation()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
