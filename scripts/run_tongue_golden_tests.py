#!/usr/bin/env python3
"""Run v0 golden checks for parser, renderer, and file-write spike."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from governed_effect_file_write_spike import run_self_tests
from parse_tongue_line import parse_line
from render_tongue_record import render_record


DEFAULT_GOLDEN = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "tongue-golden-tests-v0.json"
)


def assert_payload_contains(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    """Assert expected nested payload fields are present."""

    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, dict):
            assert isinstance(actual_value, dict), f"payload.{key} is not an object"
            assert_payload_contains(actual_value, expected_value)
        else:
            assert actual_value == expected_value, f"payload.{key}: {actual_value!r} != {expected_value!r}"


def check_parser(golden: dict[str, Any]) -> list[str]:
    """Run parser golden cases."""

    passed = []
    for case in golden["parser"]:
        parsed = parse_line(case["input"])
        assert parsed["speech_act"] == case["expected_speech_act"]
        assert_payload_contains(parsed["payload"], case.get("expected_payload", {}))
        if "expected_reason" in case:
            assert parsed.get("reason") == case["expected_reason"]
        if "expected_evidence" in case:
            assert parsed.get("evidence") == case["expected_evidence"]
        passed.append(case["input"])
    return passed


def check_renderer(golden: dict[str, Any]) -> list[str]:
    """Run renderer golden cases."""

    passed = []
    for case in golden["renderer"]:
        rendered = render_record(case["record"])
        for expected in case["expected_contains"]:
            assert expected in rendered, f"{expected!r} not in rendered text: {rendered!r}"
        passed.append(case["record"]["proposal_id"])
    return passed


def check_file_write(golden: dict[str, Any]) -> list[str]:
    """Run file-write adapter golden cases."""

    results = run_self_tests()
    passed = []
    for case in golden["file_write_adapter"]:
        name = case["name"]
        if name == "allowed_write_commits":
            actual = results[name]
            assert actual["state"] == case["expected_state"]
            trace = results["allowed_write_trace_events"]
            for event_type in case["expected_trace_contains"]:
                assert event_type in trace
        else:
            actual = results[name]
            assert actual["state"] == case["expected_state"]
            if "expected_reason" in case:
                assert actual.get("rejection_reason") == case["expected_reason"]
            if "expected_required_input" in case:
                assert actual.get("required_input") == case["expected_required_input"]
        passed.append(name)
    return passed


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("golden", nargs="?", default=str(DEFAULT_GOLDEN))
    args = parser.parse_args()

    golden = json.loads(Path(args.golden).read_text())
    result = {
        "parser": check_parser(golden),
        "renderer": check_renderer(golden),
        "file_write_adapter": check_file_write(golden),
    }
    print(json.dumps({"status": "passed", "result": result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
