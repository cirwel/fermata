#!/usr/bin/env python3
"""Run v0 golden checks for parser, renderer, and file-write spike."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fermata.governed_effects import run_self_tests
from parse_tongue_line import parse_line
from render_tongue_record import render_record

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - exercised by environment setup.
    raise SystemExit(
        "jsonschema is required for golden checks; install with: "
        "python -m pip install -e '.[dev]'"
    ) from exc


DEFAULT_GOLDEN = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "tongue-golden-tests-v0.json"
)
DEFAULT_SCHEMA = ROOT / "references" / "governed-effect-ir-v0.schema.json"
DEFAULT_CORPUS = ROOT / "references" / "ai-native-tongue-seed-corpus-v0.jsonl"


def load_schema_validator(schema_path: Path) -> Draft202012Validator:
    """Load and validate the canonical JSON Schema."""

    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def validate_record(
    validator: Draft202012Validator,
    label: str,
    record: dict[str, Any],
) -> None:
    """Assert one canonical record validates against the schema."""

    errors = sorted(
        validator.iter_errors(record),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise AssertionError(f"{label} schema invalid at {path}: {error.message}")


def assert_payload_contains(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    """Assert expected nested payload fields are present."""

    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, dict):
            assert isinstance(actual_value, dict), f"payload.{key} is not an object"
            assert_payload_contains(actual_value, expected_value)
        else:
            assert actual_value == expected_value, (
                f"payload.{key}: {actual_value!r} != {expected_value!r}"
            )


def check_parser(
    golden: dict[str, Any],
    validator: Draft202012Validator,
) -> list[str]:
    """Run parser golden cases."""

    passed = []
    for case in golden["parser"]:
        parsed = parse_line(case["input"])
        validate_record(validator, f"parser:{case['input']}", parsed)
        assert parsed["speech_act"] == case["expected_speech_act"]
        assert_payload_contains(parsed["payload"], case.get("expected_payload", {}))
        if "expected_reason" in case:
            assert parsed.get("reason") == case["expected_reason"]
        if "expected_evidence" in case:
            assert parsed.get("evidence") == case["expected_evidence"]
        passed.append(case["input"])
    return passed


def check_renderer(
    golden: dict[str, Any],
    validator: Draft202012Validator,
) -> list[str]:
    """Run renderer golden cases."""

    passed = []
    for case in golden["renderer"]:
        validate_record(
            validator,
            f"renderer:{case['record']['proposal_id']}",
            case["record"],
        )
        rendered = render_record(case["record"])
        for expected in case["expected_contains"]:
            assert expected in rendered, f"{expected!r} not in rendered text: {rendered!r}"
        passed.append(case["record"]["proposal_id"])
    return passed


def check_seed_corpus(
    validator: Draft202012Validator,
    corpus_path: Path,
) -> dict[str, int]:
    """Validate every seed corpus JSONL record against the schema."""

    count = 0
    for line_number, line in enumerate(corpus_path.read_text().splitlines(), start=1):
        if line.strip():
            validate_record(
                validator,
                f"{corpus_path.name}:{line_number}",
                json.loads(line),
            )
            count += 1
    return {"jsonl_records": count}


def check_file_write(
    golden: dict[str, Any],
    validator: Draft202012Validator,
) -> list[str]:
    """Run file-write adapter golden cases."""

    results = run_self_tests()
    for key, value in results.items():
        if isinstance(value, dict) and value.get("record_type") in {"effect", "trace"}:
            validate_record(validator, f"file_write:{key}", value)

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
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    args = parser.parse_args()

    validator = load_schema_validator(Path(args.schema))
    golden = json.loads(Path(args.golden).read_text())
    result = {
        "schema": check_seed_corpus(validator, Path(args.corpus)),
        "parser": check_parser(golden, validator),
        "renderer": check_renderer(golden, validator),
        "file_write_adapter": check_file_write(golden, validator),
    }
    print(json.dumps({"status": "passed", "result": result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
