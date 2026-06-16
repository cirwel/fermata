#!/usr/bin/env python3
"""Generate and validate a filled recovery evidence example."""

from __future__ import annotations

import json
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from check_local_service import (
    STARTUP_TIMEOUT_SECONDS,
    fermata_command,
    load_json,
    parse_startup,
    post_json,
    read_line_with_timeout,
    request_envelope,
    stop_service,
)
from check_recovery_evidence import CLASSIFICATIONS, require, validate_record_ref


EXAMPLE_REQUEST_ID = "svc_req_recovery_example_run_001"


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def load_example(path: Path) -> dict[str, Any]:
    """Load a checked-in recovery evidence example packet."""

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def run_cli_json(command: str, args: list[str]) -> dict[str, Any]:
    """Run the fermata CLI and return a JSON object."""

    result = subprocess.run(
        [command, *args],
        capture_output=True,
        text=True,
        timeout=STARTUP_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result
    data = json.loads(result.stdout)
    assert isinstance(data, dict)
    return data


def public_ref(ref: dict[str, Any]) -> dict[str, Any]:
    """Return a persisted record reference without full payload."""

    return {
        key: ref[key]
        for key in (
            "stream",
            "path",
            "line",
            "line_sha256",
            "record_type",
            "request_id",
            "operation",
            "stored_at",
            "payload_sha256",
            "payload_sha256_valid",
            "payload_record_type",
        )
        if key in ref
    }


def flatten_record_refs(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every record reference in a service-records export row."""

    records = row.get("records")
    require(isinstance(records, dict), "records_export.row.records")
    refs: list[dict[str, Any]] = []
    for key in ("request", "response", "trace", "error"):
        value = records.get(key)
        require(isinstance(value, list), f"records_export.row.records.{key}")
        for ref in value:
            require(isinstance(ref, dict), f"records_export.row.records.{key}.ref")
            refs.append(public_ref(ref))
    return refs


def build_packet(
    records_export: dict[str, Any],
    *,
    service_root: Path,
) -> dict[str, Any]:
    """Build a filled recovery evidence packet from service record export."""

    require(
        records_export.get("record_type") == "service_records_export",
        "export.type",
    )
    require(records_export.get("status") == "ok", "export.status")
    require(records_export.get("request_count") == 1, "export.request_count")
    rows = records_export.get("requests")
    require(isinstance(rows, list) and len(rows) == 1, "export.requests")
    row = rows[0]
    require(isinstance(row, dict), "export.requests.0")
    refs = flatten_record_refs(row)
    request_refs = row["records"]["request"]
    response_refs = row["records"]["response"]
    trace_refs = row["records"]["trace"]
    error_refs = row["records"]["error"]

    return {
        "schema_version": "0.1",
        "record_type": "recovery_evidence_packet",
        "packet_version": "0.1",
        "source": {
            "kind": "actual_local_service_run",
            "service_root": str(service_root.resolve()),
            "generated_by": (
                "fermata service records --service-root "
                f"{service_root.resolve()} --request-id {EXAMPLE_REQUEST_ID} "
                "--include-payload"
            ),
            "request_id": EXAMPLE_REQUEST_ID,
        },
        "service_records_export": {
            "record_type": records_export["record_type"],
            "status": records_export["status"],
            "request_count": records_export["request_count"],
            "stream_counts": {
                stream: summary["records"]
                for stream, summary in records_export["streams"].items()
            },
            "request": {
                "request_id": row["request_id"],
                "operation": row["operation"],
                "classification": row["classification"],
                "effect_state": row["effect_state"],
                "verification_status": row["verification_status"],
                "trace": row["trace"],
                "records": {
                    "request": [public_ref(ref) for ref in request_refs],
                    "response": [public_ref(ref) for ref in response_refs],
                    "trace": [public_ref(ref) for ref in trace_refs],
                    "error": [public_ref(ref) for ref in error_refs],
                },
            },
        },
        "incident_report": {
            "record_type": "service_incident_report",
            "incident_id": "svc_inc_recovery_example_001",
            "status": "complete",
            "scope": {
                "request_ids": [row["request_id"]],
                "operations": [row["operation"]],
            },
            "observed_records": refs,
            "operator_decision": {
                "decision": "no_recovery_action_required",
                "reason": (
                    "The request reconciles to a committed effect with adapter "
                    "acknowledgement and verified read-back evidence."
                ),
                "next_safe_steps": [
                    "retain service record snapshot",
                    "attach packet to local-alpha evidence",
                ],
            },
        },
        "reconciliation_report": {
            "record_type": "service_reconciliation_report",
            "reconciliation_id": "svc_rec_recovery_example_001",
            "status": "complete",
            "request_reconciliations": [
                {
                    "request_id": row["request_id"],
                    "operation": row["operation"],
                    "classification": row["classification"],
                    "effect_state": row["effect_state"],
                    "adapter_commit_started": row["trace"][
                        "adapter_commit_started"
                    ],
                    "effect_committed_event": row["trace"]["effect_committed_event"],
                    "verification_status": row["verification_status"],
                    "records": {
                        "request": [public_ref(ref) for ref in request_refs],
                        "response": [public_ref(ref) for ref in response_refs],
                        "trace": [public_ref(ref) for ref in trace_refs],
                        "error": [public_ref(ref) for ref in error_refs],
                    },
                }
            ],
            "summary": {
                "committed": 1 if row["classification"] == "committed" else 0,
                "needs_review": 1 if row["classification"] == "needs_review" else 0,
            },
        },
        "non_claims": [
            "automatic_retry",
            "rollback_completed",
            "approval_granted_by_report",
            "hosted_production_incident_response",
        ],
    }


def validate_packet(packet: dict[str, Any]) -> None:
    """Validate a recovery evidence packet example."""

    require(packet.get("schema_version") == "0.1", "packet.schema_version")
    require(packet.get("record_type") == "recovery_evidence_packet", "packet.type")
    require(packet.get("packet_version") == "0.1", "packet.version")
    source = packet.get("source")
    require(isinstance(source, dict), "packet.source")
    require(isinstance(source.get("request_id"), str), "packet.source.request_id")

    export = packet.get("service_records_export")
    require(isinstance(export, dict), "packet.service_records_export")
    require(export.get("record_type") == "service_records_export", "export.type")
    require(export.get("status") == "ok", "export.status")
    require(export.get("request_count") == 1, "export.request_count")
    request = export.get("request")
    require(isinstance(request, dict), "export.request")
    require(request.get("request_id") == source["request_id"], "request.id")
    require(request.get("operation") == "run", "request.operation")
    require(
        request.get("classification") in CLASSIFICATIONS,
        "request.classification",
    )
    require(request.get("classification") == "committed", "request.committed")
    require(request.get("effect_state") == "committed", "request.effect_state")
    require(request.get("verification_status") == "verified", "request.verified")
    trace = request.get("trace")
    require(isinstance(trace, dict), "request.trace")
    require(trace.get("adapter_commit_started") is True, "trace.adapter_commit")
    require(trace.get("effect_committed_event") is True, "trace.effect_commit")

    refs = flatten_record_refs(request)
    require(len(refs) == 3, "request.record_ref_count")
    for index, ref in enumerate(refs):
        validate_record_ref(ref, label=f"packet.records.{index}")
        require(ref.get("payload_sha256_valid") is True, f"packet.records.{index}.hash")

    incident = packet.get("incident_report")
    require(isinstance(incident, dict), "packet.incident_report")
    require(incident.get("status") == "complete", "incident.status")
    observed = incident.get("observed_records")
    require(isinstance(observed, list) and len(observed) == 3, "incident.observed")
    for index, ref in enumerate(observed):
        require(isinstance(ref, dict), f"incident.observed.{index}")
        validate_record_ref(ref, label=f"incident.observed.{index}")

    reconciliation = packet.get("reconciliation_report")
    require(isinstance(reconciliation, dict), "packet.reconciliation_report")
    rows = reconciliation.get("request_reconciliations")
    require(isinstance(rows, list) and len(rows) == 1, "reconciliation.rows")
    row = rows[0]
    require(isinstance(row, dict), "reconciliation.row")
    require(row.get("classification") == "committed", "reconciliation.committed")
    require(row.get("adapter_commit_started") is True, "reconciliation.adapter")
    require(row.get("effect_committed_event") is True, "reconciliation.effect")
    require(row.get("verification_status") == "verified", "reconciliation.verified")

    non_claims = packet.get("non_claims")
    require(isinstance(non_claims, list), "packet.non_claims")
    for non_claim in (
        "automatic_retry",
        "rollback_completed",
        "approval_granted_by_report",
    ):
        require(non_claim in non_claims, f"packet.non_claims.{non_claim}")


def generate_from_local_service(command: str, root: Path) -> dict[str, Any]:
    """Run the local service and build one filled packet from exported records."""

    repo = repo_root()
    service_root = root / "service-root"
    process = subprocess.Popen(
        [
            command,
            "service",
            "run",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--service-root",
            str(service_root),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    try:
        startup = parse_startup(
            read_line_with_timeout(process.stdout, STARTUP_TIMEOUT_SECONDS),
            expected_root=service_root,
        )
        base = f"http://127.0.0.1:{startup['port']}"

        scope = load_json(repo / "examples/local-alpha/file-scope.json")
        proposal = load_json(repo / "examples/local-alpha/file-write-proposal.json")
        approval = load_json(repo / "examples/local-alpha/file-write-approval.json")
        committed = post_json(
            f"{base}/v0/run",
            request_envelope(
                request_id=EXAMPLE_REQUEST_ID,
                operation="run",
                scope=scope,
                proposal=proposal,
                approval=approval,
            ),
        )
        assert committed["effect"]["state"] == "committed"
        assert committed["effect"]["verification"]["status"] == "verified"
        assert (service_root / "sandbox" / "cli-note.txt").exists()

        records_export = run_cli_json(
            command,
            [
                "service",
                "records",
                "--service-root",
                str(service_root),
                "--request-id",
                EXAMPLE_REQUEST_ID,
                "--include-payload",
            ],
        )
        packet = build_packet(records_export, service_root=service_root)
        validate_packet(packet)
        return packet
    finally:
        exit_code = stop_service(process)
        assert exit_code in {0, -signal.SIGINT}, exit_code


def main() -> int:
    """Validate the checked example and a freshly generated example."""

    root = repo_root()
    example_path = (
        root
        / "references/recovery-evidence-examples-v0/local-service-run-packet-v0.json"
    )
    checked_packet = load_example(example_path)
    validate_packet(checked_packet)

    command = fermata_command()
    with tempfile.TemporaryDirectory(prefix="fermata_recovery_example_check_") as tmp:
        generated_packet = generate_from_local_service(command, Path(tmp))
    validate_packet(generated_packet)

    print(
        json.dumps(
            {
                "checks": {
                    "checked_example": example_path.name,
                    "generated_request_id": generated_packet["source"]["request_id"],
                    "generated_classification": generated_packet[
                        "service_records_export"
                    ]["request"]["classification"],
                    "observed_records": len(
                        generated_packet["incident_report"]["observed_records"]
                    ),
                },
                "recovery_evidence_example": "local-service-run-packet-v0",
                "status": "passed",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
