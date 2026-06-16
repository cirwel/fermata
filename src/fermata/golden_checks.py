"""Golden checks for parser, renderer, and governed local adapters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fermata.self_tests import run_self_tests
from fermata.tongue_parser import parse_line
from fermata.tongue_renderer import render_record

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - exercised by environment setup.
    raise SystemExit(
        "jsonschema is required for golden checks; install with: "
        "python -m pip install -e '.[dev]'"
    ) from exc


def default_reference_root() -> Path:
    """Return source references when available, otherwise packaged references."""

    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "references").exists():
        return source_root / "references"
    package_root = Path(__file__).resolve().parent / "reference_data"
    if package_root.exists():
        return package_root
    return Path.cwd() / "references"


REFERENCE_ROOT = default_reference_root()
DEFAULT_GOLDEN = REFERENCE_ROOT / "tongue-golden-tests-v0.json"
DEFAULT_SCHEMA = REFERENCE_ROOT / "governed-effect-ir-v0.schema.json"
DEFAULT_CORPUS = REFERENCE_ROOT / "ai-native-tongue-seed-corpus-v0.jsonl"


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


def validate_adapter_records(
    validator: Draft202012Validator,
    label: str,
    results: dict[str, Any],
) -> None:
    """Validate effect and trace records produced by adapter self-tests."""

    for key, value in results.items():
        if isinstance(value, dict) and value.get("record_type") in {"effect", "trace"}:
            validate_record(validator, f"{label}:{key}", value)


def check_file_write(
    golden: dict[str, Any],
    results: dict[str, Any],
) -> list[str]:
    """Run file-write adapter golden cases."""

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


def check_memory_write(
    golden: dict[str, Any],
    results: dict[str, Any],
) -> list[str]:
    """Run memory-write adapter golden cases."""

    passed = []
    for case in golden["memory_write_adapter"]:
        name = case["name"]
        actual = results[name]
        assert actual["state"] == case["expected_state"]
        if "expected_reason" in case:
            assert actual.get("rejection_reason") == case["expected_reason"]
        if "expected_required_input" in case:
            assert actual.get("required_input") == case["expected_required_input"]
        if "expected_trace_contains" in case:
            trace = results[case["trace_events_key"]]
            for event_type in case["expected_trace_contains"]:
                assert event_type in trace
        passed.append(name)
    return passed


def check_interpreter(
    golden: dict[str, Any],
    results: dict[str, Any],
) -> list[str]:
    """Run interpreter golden cases."""

    passed = []
    for case in golden.get("interpreter", []):
        name = case["name"]
        actual = results[name]
        assert actual["state"] == case["expected_state"]
        if "expected_reason" in case:
            assert actual.get("rejection_reason") == case["expected_reason"]
        if "expected_required_input" in case:
            assert actual.get("required_input") == case["expected_required_input"]
        if "expected_trace_contains" in case:
            trace = results[case["trace_events_key"]]
            for event_type in case["expected_trace_contains"]:
                assert event_type in trace
        if "expected_trace_excludes" in case:
            trace = results[case["trace_events_key"]]
            for event_type in case["expected_trace_excludes"]:
                assert event_type not in trace
        passed.append(name)
    return passed


def check_cli(
    golden: dict[str, Any],
    results: dict[str, Any],
) -> list[str]:
    """Run public CLI lowering/evaluation golden cases."""

    passed = []
    for case in golden.get("cli", []):
        name = case["name"]
        actual = results[name]
        assert actual["state"] == case["expected_state"]
        if "expected_reason" in case:
            assert actual.get("rejection_reason") == case["expected_reason"]
        if "expected_required_input" in case:
            assert actual.get("required_input") == case["expected_required_input"]
        if "expected_trace_contains" in case:
            trace = results[case["trace_events_key"]]
            for event_type in case["expected_trace_contains"]:
                assert event_type in trace
        if "expected_trace_excludes" in case:
            trace = results[case["trace_events_key"]]
            for event_type in case["expected_trace_excludes"]:
                assert event_type not in trace
        passed.append(name)
    return passed


def check_trace_ledger(
    golden: dict[str, Any],
    results: dict[str, Any],
) -> list[str]:
    """Run trace ledger golden cases."""

    passed = []
    for case in golden.get("trace_ledger", []):
        name = case["name"]
        actual = results[name]
        assert actual["acknowledgement"]["adapter"] == "trace_ledger"
        assert actual["verification"]["status"] == case["expected_status"]
        passed.append(name)
    return passed


def check_surfaces(
    validator: Draft202012Validator,
    results: dict[str, Any],
) -> list[str]:
    """Validate the authority-policy and agent-utterance surface lowerings.

    Proves the four halves of issue #3's acceptance:

    - the authority policy block lowers into a schema-valid Scope record;
    - the agent JSON utterance lowers into a schema-valid Proposal record;
    - the agent cannot inject ``state: "committed"`` plus
      ``acknowledgement`` into a Proposal-shape record (rejected by schema
      because ``Proposal`` uses ``additionalProperties: false``);
    - the authority policy parser rejects ``approval grant ...`` — the authority
      surface declares requirements, not granted approvals.
    """

    passed = []

    scope_record = results["authority_policy_parses_to_scope_record"]
    scope_errors = list(validator.iter_errors(scope_record))
    assert not scope_errors, (
        "authority policy must lower into schema-valid Scope; got: "
        + "; ".join(e.message[:120] for e in scope_errors)
    )
    passed.append("authority_policy_lowers_to_canonical_scope")

    proposal_record = results["agent_json_parses_to_proposal_record"]
    proposal_errors = list(validator.iter_errors(proposal_record))
    assert not proposal_errors, (
        "agent JSON must lower into schema-valid Proposal; got: "
        + "; ".join(e.message[:120] for e in proposal_errors)
    )
    passed.append("agent_json_lowers_to_canonical_proposal")

    injected = results["agent_cannot_inject_committed_state"][
        "record_with_injection"
    ]
    injected_errors = list(validator.iter_errors(injected))
    assert injected_errors, (
        "agent must not be able to inject committed-state fields; "
        "schema additionalProperties:false should reject"
    )
    passed.append("agent_cannot_self_declare_committed")

    rejection = results["authority_policy_cannot_inline_grant"]
    assert rejection["rejected"] is True, (
        "authority policy parser must reject 'approval grant ...' inline"
    )
    passed.append("authority_policy_cannot_self_grant_approval")

    return passed


def run_golden_checks(
    *,
    golden_path: Path = DEFAULT_GOLDEN,
    schema_path: Path = DEFAULT_SCHEMA,
    corpus_path: Path = DEFAULT_CORPUS,
) -> dict[str, Any]:
    """Run all golden checks and return the machine-readable result."""

    validator = load_schema_validator(schema_path)
    golden = json.loads(golden_path.read_text())
    adapter_results = run_self_tests()
    validate_adapter_records(validator, "adapter", adapter_results)
    return {
        "schema": check_seed_corpus(validator, corpus_path),
        "parser": check_parser(golden, validator),
        "renderer": check_renderer(golden, validator),
        "file_write_adapter": check_file_write(golden, adapter_results),
        "memory_write_adapter": check_memory_write(golden, adapter_results),
        "interpreter": check_interpreter(golden, adapter_results),
        "cli": check_cli(golden, adapter_results),
        "trace_ledger": check_trace_ledger(golden, adapter_results),
        "surfaces": check_surfaces(validator, adapter_results),
    }


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("golden", nargs="?", default=str(DEFAULT_GOLDEN))
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    args = parser.parse_args()

    result = run_golden_checks(
        golden_path=Path(args.golden),
        schema_path=Path(args.schema),
        corpus_path=Path(args.corpus),
    )
    print(json.dumps({"status": "passed", "result": result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
