#!/usr/bin/env python3
"""Validate recovery evidence templates for local service records."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from fermata.runtime_api import run
from fermata.runtime_ir import canonical_json_bytes, sha256_bytes
from fermata.service import (
    ServiceError,
    error_envelope,
    response_envelope,
    service_record,
)


STREAM_RECORD_TYPES = {
    "requests": "service_request_item",
    "responses": "service_response_item",
    "traces": "service_trace_item",
    "errors": "service_error_item",
}
CHECK_NAMES = {
    "jsonl_parse",
    "payload_sha256",
    "group_by_request_id",
    "trace_commit_events",
    "outcome_classification",
    "operator_decision",
}
CLASSIFICATIONS = {
    "committed",
    "paused",
    "rejected",
    "service_error",
    "incomplete",
    "needs_review",
}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def require(condition: bool, message: str) -> None:
    """Raise when a template invariant is not met."""

    if not condition:
        raise AssertionError(message)


def validate_hash(value: Any, *, label: str) -> None:
    """Validate one lowercase SHA-256 hex string."""

    require(isinstance(value, str) and HASH_RE.fullmatch(value) is not None, label)


def validate_record_ref(ref: dict[str, Any], *, label: str) -> None:
    """Validate one reference to a persisted service JSONL record."""

    stream = ref.get("stream")
    require(stream in STREAM_RECORD_TYPES, f"{label}.stream")
    require(ref.get("path") == f"records/{stream}.jsonl", f"{label}.path")
    require(
        ref.get("record_type") == STREAM_RECORD_TYPES[stream],
        f"{label}.record_type",
    )
    require(isinstance(ref.get("line"), int) and ref["line"] >= 1, f"{label}.line")
    require(
        isinstance(ref.get("request_id"), str)
        and ref["request_id"].startswith("svc_req_"),
        f"{label}.request_id",
    )
    require(ref.get("operation") in {"interpret", "run"}, f"{label}.operation")
    validate_hash(ref.get("payload_sha256"), label=f"{label}.payload_sha256")
    validate_hash(ref.get("line_sha256"), label=f"{label}.line_sha256")


def validate_incident_template(template: dict[str, Any]) -> None:
    """Validate the service incident report template."""

    require(template.get("schema_version") == "0.1", "incident.schema_version")
    require(
        template.get("record_type") == "service_incident_report_template",
        "incident.record_type",
    )
    require(template.get("template_version") == "0.1", "incident.template_version")
    require(template.get("status") == "draft", "incident.status")
    service = template.get("service")
    require(isinstance(service, dict), "incident.service")
    require(service.get("loopback_only") is True, "incident.service.loopback_only")
    require(service.get("production") is False, "incident.service.production")
    observed = template.get("observed_records")
    require(isinstance(observed, list) and observed, "incident.observed_records")
    for index, ref in enumerate(observed):
        require(isinstance(ref, dict), f"incident.observed_records.{index}")
        validate_record_ref(ref, label=f"incident.observed_records.{index}")
    require(
        "approval_granted" in template.get("non_claims", []),
        "incident.non_claims.approval_granted",
    )


def validate_reconciliation_template(template: dict[str, Any]) -> None:
    """Validate the service reconciliation report template."""

    require(template.get("schema_version") == "0.1", "reconciliation.schema_version")
    require(
        template.get("record_type") == "service_reconciliation_report_template",
        "reconciliation.record_type",
    )
    require(
        template.get("template_version") == "0.1",
        "reconciliation.template_version",
    )
    streams = template.get("streams")
    require(isinstance(streams, dict), "reconciliation.streams")
    require(set(streams) == set(STREAM_RECORD_TYPES), "reconciliation.streams.keys")
    for stream, record_type in STREAM_RECORD_TYPES.items():
        stream_spec = streams[stream]
        require(
            stream_spec.get("path") == f"records/{stream}.jsonl",
            f"streams.{stream}.path",
        )
        require(
            stream_spec.get("record_type") == record_type,
            f"streams.{stream}.record_type",
        )

    checks = template.get("checks")
    require(isinstance(checks, list), "reconciliation.checks")
    require(
        {check.get("name") for check in checks} == CHECK_NAMES,
        "reconciliation.checks",
    )
    require(
        set(template.get("allowed_classifications", [])) == CLASSIFICATIONS,
        "reconciliation.allowed_classifications",
    )
    rows = template.get("request_reconciliations")
    require(isinstance(rows, list) and rows, "reconciliation.request_reconciliations")
    for row_index, row in enumerate(rows):
        require(isinstance(row, dict), f"reconciliation.rows.{row_index}")
        require(
            row.get("classification") in CLASSIFICATIONS,
            f"reconciliation.rows.{row_index}.classification",
        )
        records = row.get("records")
        require(isinstance(records, dict), f"reconciliation.rows.{row_index}.records")
        for key in ("request", "response", "trace"):
            ref = records.get(key)
            require(isinstance(ref, dict), f"reconciliation.rows.{row_index}.{key}")
            validate_record_ref(ref, label=f"reconciliation.rows.{row_index}.{key}")
        require(
            records.get("error") is None or isinstance(records.get("error"), dict),
            "reconciliation.error",
        )


def validate_service_wrapper(stream: str, record: dict[str, Any]) -> None:
    """Validate a persisted service wrapper record."""

    require(record.get("schema_version") == "0.1", f"{stream}.schema_version")
    require(
        record.get("record_type") == STREAM_RECORD_TYPES[stream],
        f"{stream}.record_type",
    )
    require(record.get("operation") in {"interpret", "run"}, f"{stream}.operation")
    require(isinstance(record.get("stored_at"), str), f"{stream}.stored_at")
    payload = record.get("payload")
    require(isinstance(payload, dict), f"{stream}.payload")
    expected_hash = sha256_bytes(canonical_json_bytes(payload))
    require(record.get("payload_sha256") == expected_hash, f"{stream}.payload_sha256")


def classify_group(records: dict[str, dict[str, Any] | None]) -> str:
    """Classify one request group from service wrapper records."""

    error = records.get("errors")
    if error is not None:
        return "service_error"
    response = records.get("responses")
    if response is None:
        return "incomplete"
    payload = response["payload"]
    effect = payload.get("effect")
    if not isinstance(effect, dict):
        return "needs_review"
    state = effect.get("state")
    if state == "committed":
        trace = records.get("traces")
        events = []
        if trace is not None:
            events = [event.get("type") for event in trace["payload"].get("events", [])]
        if (
            "adapter.commit.started" in events
            and "effect.committed" in events
            and isinstance(effect.get("acknowledgement"), dict)
            and isinstance(effect.get("verification"), dict)
        ):
            return "committed"
        return "needs_review"
    if state in {"paused", "rejected"}:
        return state
    return "needs_review"


def build_sample_records(root: Path) -> dict[str, dict[str, Any] | None]:
    """Build sample service wrapper records from local-alpha fixtures."""

    scope = load_json(root / "examples/local-alpha/file-scope.json")
    proposal = load_json(root / "examples/local-alpha/file-write-proposal.json")
    approval = load_json(root / "examples/local-alpha/file-write-approval.json")
    request = {
        "schema_version": "0.1",
        "record_type": "service_request",
        "request_id": "svc_req_recovery_check_001",
        "operation": "run",
        "caller": {"subject": "operator:recovery-evidence-check"},
        "sandbox_root": "sandbox",
        "scope": scope,
        "proposal": proposal,
        "approval": approval,
    }
    with tempfile.TemporaryDirectory(prefix="fermata_recovery_evidence_") as tmp:
        output = run(
            scope,
            proposal,
            approval=approval,
            sandbox_root=Path(tmp) / "service-root" / "sandbox",
        )
    response = response_envelope(
        request_id=request["request_id"],
        operation="run",
        effect=output.effect,
        trace=output.trace,
    )
    error = error_envelope(
        ServiceError(
            "scope_outside_service_root",
            "request sandbox_root must resolve inside the service root",
        )
    )
    error["request_id"] = "svc_req_recovery_error_001"
    error["operation"] = "run"
    return {
        "requests": service_record(
            record_type="service_request_item",
            request_id=request["request_id"],
            operation="run",
            payload=request,
        ),
        "responses": service_record(
            record_type="service_response_item",
            request_id=request["request_id"],
            operation="run",
            payload=response,
        ),
        "traces": service_record(
            record_type="service_trace_item",
            request_id=request["request_id"],
            operation="run",
            payload=output.trace,
        ),
        "errors": service_record(
            record_type="service_error_item",
            request_id="svc_req_recovery_error_001",
            operation="run",
            payload=error,
        ),
    }


def main() -> int:
    """Run recovery evidence checks and print machine-readable evidence."""

    root = repo_root()
    templates_dir = root / "references/recovery-evidence-templates-v0"
    incident = load_json(templates_dir / "service-incident-report-template.json")
    reconciliation = load_json(
        templates_dir / "service-reconciliation-report-template.json"
    )
    validate_incident_template(incident)
    validate_reconciliation_template(reconciliation)

    wrappers = build_sample_records(root)
    for stream, record in wrappers.items():
        assert record is not None
        validate_service_wrapper(stream, record)
    committed = classify_group(
        {
            "requests": wrappers["requests"],
            "responses": wrappers["responses"],
            "traces": wrappers["traces"],
            "errors": None,
        }
    )
    service_error = classify_group(
        {
            "requests": None,
            "responses": None,
            "traces": None,
            "errors": wrappers["errors"],
        }
    )
    require(committed == "committed", "sample.committed_classification")
    require(service_error == "service_error", "sample.service_error_classification")

    print(
        json.dumps(
            {
                "checks": {
                    "templates": [
                        "service-incident-report-template.json",
                        "service-reconciliation-report-template.json",
                    ],
                    "streams": sorted(STREAM_RECORD_TYPES),
                    "classifications": sorted(CLASSIFICATIONS),
                    "sample_classifications": {
                        "committed": committed,
                        "service_error": service_error,
                    },
                },
                "recovery_evidence": "recovery-evidence-v0",
                "status": "passed",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
