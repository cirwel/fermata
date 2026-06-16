#!/usr/bin/env python3
"""Check local alpha run-bundle contract fixtures."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


CONTRACT_ROOT = "references/run-bundle-contract-fixtures-v0"
EFFECT_STATES = frozenset({"paused", "rejected", "committed"})


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def read_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from path."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError(f"{path} did not contain a JSON object")
    return data


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


def run_expect_error(command: list[str], expected: str) -> None:
    """Run a command that should fail with a stable stderr fragment."""

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        raise AssertionError(f"command unexpectedly succeeded: {' '.join(command)}")
    if expected not in result.stderr:
        raise AssertionError(
            f"expected {expected!r} in stderr for {' '.join(command)}\n"
            f"stderr:\n{result.stderr}"
        )


def require_keys(record: dict[str, Any], keys: set[str], *, label: str) -> None:
    """Require stable keys in a JSON object."""

    missing = sorted(keys - set(record))
    if missing:
        raise AssertionError(f"{label} missing key(s): {', '.join(missing)}")


def event_types(trace: dict[str, Any]) -> set[str]:
    """Return trace event type strings."""

    return {
        event["type"]
        for event in trace["events"]
        if isinstance(event, dict) and isinstance(event.get("type"), str)
    }


def assert_bundle_contract(output: dict[str, Any], bundle: Path) -> None:
    """Assert stable local-alpha run-bundle output fields."""

    require_keys(output, {"status", "bundle", "effect", "trace"}, label="output")
    if output["status"] != "ok":
        raise AssertionError("bundle output status must be ok")
    bundle_record = output["bundle"]
    effect = output["effect"]
    trace = output["trace"]
    if not isinstance(bundle_record, dict):
        raise AssertionError("output.bundle must be an object")
    if not isinstance(effect, dict):
        raise AssertionError("output.effect must be an object")
    if not isinstance(trace, dict):
        raise AssertionError("output.trace must be an object")

    require_keys(
        bundle_record,
        {"path", "scope", "proposal", "approval", "effect", "trace"},
        label="bundle",
    )
    require_keys(
        effect,
        {"schema_version", "record_type", "effect_id", "state", "scope_id", "trace_id"},
        label="effect",
    )
    require_keys(
        trace,
        {"schema_version", "record_type", "trace_id", "events"},
        label="trace",
    )

    if effect["schema_version"] != "0.1" or effect["record_type"] != "effect":
        raise AssertionError("effect must be a v0.1 effect record")
    if trace["schema_version"] != "0.1" or trace["record_type"] != "trace":
        raise AssertionError("trace must be a v0.1 trace record")
    if effect["state"] not in EFFECT_STATES:
        raise AssertionError(f"unexpected effect state: {effect['state']!r}")
    if effect["trace_id"] != trace["trace_id"]:
        raise AssertionError("effect.trace_id must match trace.trace_id")
    if not isinstance(trace["events"], list) or not trace["events"]:
        raise AssertionError("trace.events must be a non-empty array")
    for index, event in enumerate(trace["events"]):
        if not isinstance(event, dict):
            raise AssertionError(f"trace event {index} must be an object")
        if not isinstance(event.get("type"), str) or not event["type"]:
            raise AssertionError(f"trace event {index} missing stable type")

    if read_object(bundle / "effect.json") != effect:
        raise AssertionError("effect.json does not match command output")
    if read_object(bundle / "trace.json") != trace:
        raise AssertionError("trace.json does not match command output")


def assert_state_contract(case: dict[str, Any], output: dict[str, Any]) -> None:
    """Assert state-specific contract fields for one fixture."""

    effect = output["effect"]
    expected_state = case["expected_state"]
    if effect["state"] != expected_state:
        raise AssertionError(
            f"{case['name']}: state {effect['state']!r} != {expected_state!r}"
        )

    if expected_state == "paused":
        required_input = case.get("expected_required_input")
        if effect.get("required_input") != required_input:
            raise AssertionError(f"{case['name']}: required_input mismatch")
        if "acknowledgement" in effect or "committed_at" in effect:
            raise AssertionError(f"{case['name']}: paused effect committed evidence")

    if expected_state == "rejected":
        expected_reason = case.get("expected_reason")
        if effect.get("rejection_reason") != expected_reason:
            raise AssertionError(f"{case['name']}: rejection_reason mismatch")
        if "acknowledgement" in effect or "committed_at" in effect:
            raise AssertionError(f"{case['name']}: rejected effect committed evidence")

    if expected_state == "committed":
        require_keys(
            effect,
            {"intent_id", "acknowledgement", "verification", "committed_at"},
            label=f"{case['name']} committed effect",
        )
        acknowledgement = effect["acknowledgement"]
        verification = effect["verification"]
        if not isinstance(acknowledgement, dict):
            raise AssertionError(f"{case['name']}: acknowledgement must be object")
        if not isinstance(verification, dict):
            raise AssertionError(f"{case['name']}: verification must be object")
        require_keys(
            acknowledgement,
            {"adapter", "target", "handle"},
            label=f"{case['name']} acknowledgement",
        )
        if verification.get("status") != "verified":
            raise AssertionError(f"{case['name']}: verification not verified")
        if acknowledgement["adapter"] != case.get("expected_ack_adapter"):
            raise AssertionError(f"{case['name']}: acknowledgement adapter mismatch")

    excluded = set(case.get("expected_trace_excludes", []))
    present = event_types(output["trace"])
    unexpected = sorted(excluded & present)
    if unexpected:
        raise AssertionError(
            f"{case['name']}: trace unexpectedly contained {', '.join(unexpected)}"
        )


def assert_file_expectations(case: dict[str, Any], bundle: Path) -> None:
    """Assert file side-effect expectations declared by a fixture."""

    target = case.get("expected_target_content")
    if isinstance(target, dict):
        target_path = (bundle / target["path"]).resolve()
        actual = target_path.read_text(encoding="utf-8")
        if actual != target["content"]:
            raise AssertionError(
                f"{case['name']}: target content mismatch at {target_path}"
            )

    for relative_path in case.get("forbidden_paths", []):
        forbidden = (bundle / relative_path).resolve()
        if forbidden.exists():
            raise AssertionError(f"{case['name']}: forbidden path exists: {forbidden}")


def assert_memory_expectations(case: dict[str, Any], output: dict[str, Any]) -> None:
    """Assert memory side-effect expectations declared by a fixture."""

    expected_content = case.get("expected_memory_content")
    if expected_content is None:
        return

    acknowledgement = output["effect"]["acknowledgement"]
    store = Path(acknowledgement["store"])
    record_id = acknowledgement["record_id"]
    matched: dict[str, Any] | None = None
    for line in store.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if isinstance(record, dict) and record.get("record_id") == record_id:
            matched = record
            break
    if matched is None:
        raise AssertionError(f"{case['name']}: memory record not found")
    if matched.get("content") != expected_content:
        raise AssertionError(f"{case['name']}: memory record content mismatch")


def check_case(
    fermata: str,
    fixtures_root: Path,
    case: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    """Copy and check one run-bundle contract fixture."""

    source = fixtures_root / case["bundle"]
    if not source.exists():
        raise AssertionError(f"{case['name']}: missing bundle fixture {source}")
    bundle = work_root / case["bundle"]
    shutil.copytree(source, bundle)

    output = run_json([fermata, "bundle", "run", str(bundle)])
    assert_bundle_contract(output, bundle)
    assert_state_contract(case, output)
    assert_file_expectations(case, bundle)
    assert_memory_expectations(case, output)
    run_expect_error(
        [fermata, "bundle", "run", str(bundle)],
        "effect.json already exists",
    )
    return {
        "name": case["name"],
        "state": output["effect"]["state"],
        "trace_id": output["trace"]["trace_id"],
    }


def main() -> int:
    """Run all run-bundle contract fixtures."""

    fermata = shutil.which("fermata")
    if fermata is None:
        print(
            "fermata console script not found on PATH; run: "
            "python3 -m pip install -e '.[dev]'",
            file=sys.stderr,
        )
        return 2

    fixtures_root = repo_root() / CONTRACT_ROOT
    manifest = read_object(fixtures_root / "manifest.json")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise AssertionError("manifest.cases must be a non-empty array")

    with tempfile.TemporaryDirectory(prefix="fermata_bundle_contract_") as tmp:
        work_root = Path(tmp)
        checked = [
            check_case(fermata, fixtures_root, case, work_root)
            for case in cases
            if isinstance(case, dict)
        ]

    states = Counter(item["state"] for item in checked)
    evidence = {
        "status": "passed",
        "command": fermata,
        "contract": manifest.get("contract"),
        "fixtures": [item["name"] for item in checked],
        "states": dict(sorted(states.items())),
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
