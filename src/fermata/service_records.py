"""Read-only export for Fermata local service records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fermata.runtime_ir import canonical_json_bytes, sha256_bytes


STREAM_RECORD_TYPES = {
    "requests": "service_request_item",
    "responses": "service_response_item",
    "traces": "service_trace_item",
    "errors": "service_error_item",
}


class ServiceRecordsError(ValueError):
    """Raised when local service records cannot be exported."""


def relative_record_path(path: Path, service_root: Path) -> str:
    """Return a stable path relative to the service root when possible."""

    try:
        return str(path.relative_to(service_root))
    except ValueError:
        return str(path)


def payload_hash_valid(record: dict[str, Any]) -> bool:
    """Return true when a service wrapper payload hash verifies."""

    payload = record.get("payload")
    payload_hash = record.get("payload_sha256")
    if not isinstance(payload, dict) or not isinstance(payload_hash, str):
        return False
    return payload_hash == sha256_bytes(canonical_json_bytes(payload))


def record_ref(
    *,
    record: dict[str, Any],
    stream: str,
    path: Path,
    service_root: Path,
    line: int,
    raw_line: str,
    include_payload: bool,
) -> dict[str, Any]:
    """Return a public reference to one persisted service wrapper record."""

    payload = record.get("payload")
    ref: dict[str, Any] = {
        "stream": stream,
        "path": relative_record_path(path, service_root),
        "line": line,
        "line_sha256": sha256_bytes((raw_line + "\n").encode("utf-8")),
        "record_type": record.get("record_type"),
        "request_id": record.get("request_id"),
        "operation": record.get("operation"),
        "stored_at": record.get("stored_at"),
        "payload_sha256": record.get("payload_sha256"),
        "payload_sha256_valid": payload_hash_valid(record),
    }
    if isinstance(payload, dict):
        ref["_payload"] = payload
        ref["payload_record_type"] = payload.get("record_type")
    if include_payload:
        ref["payload"] = payload
    return ref


def read_stream(
    *,
    stream: str,
    path: Path,
    service_root: Path,
    include_payload: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read one service JSONL stream."""

    refs: list[dict[str, Any]] = []
    if not path.exists():
        return refs, {
            "path": relative_record_path(path, service_root),
            "records": 0,
            "missing": True,
            "invalid_payload_hashes": 0,
        }

    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, raw_line in enumerate(lines, 1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ServiceRecordsError(
                f"{path}:{line_number} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(record, dict):
            raise ServiceRecordsError(f"{path}:{line_number} is not a JSON object")
        refs.append(
            record_ref(
                record=record,
                stream=stream,
                path=path,
                service_root=service_root,
                line=line_number,
                raw_line=raw_line,
                include_payload=include_payload,
            )
        )

    invalid_hashes = sum(1 for ref in refs if not ref["payload_sha256_valid"])
    return refs, {
        "path": relative_record_path(path, service_root),
        "records": len(refs),
        "missing": False,
        "invalid_payload_hashes": invalid_hashes,
    }


def ref_payload(ref: dict[str, Any]) -> dict[str, Any]:
    """Return an included payload or an empty object."""

    payload = ref.get("_payload")
    if isinstance(payload, dict):
        return payload
    payload = ref.get("payload")
    return payload if isinstance(payload, dict) else {}


def trace_event_types(trace_refs: list[dict[str, Any]]) -> list[str]:
    """Return ordered trace event types from included trace payloads."""

    event_types: list[str] = []
    for ref in trace_refs:
        payload = ref_payload(ref)
        events = payload.get("events", [])
        if not isinstance(events, list):
            continue
        for event in events:
            if isinstance(event, dict) and isinstance(event.get("type"), str):
                event_types.append(event["type"])
    return event_types


def classify_request(group: dict[str, list[dict[str, Any]]]) -> str:
    """Classify one group of service records."""

    if any(not ref["payload_sha256_valid"] for refs in group.values() for ref in refs):
        return "needs_review"
    if group["errors"]:
        return "service_error"
    if not group["responses"]:
        return "incomplete"
    if len(group["responses"]) != 1:
        return "needs_review"

    effect = ref_payload(group["responses"][0]).get("effect")
    if not isinstance(effect, dict):
        return "needs_review"
    state = effect.get("state")
    if state == "committed":
        events = trace_event_types(group["traces"])
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


def request_summary(
    request_id: str,
    group: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Return one request-group summary."""

    response_payload = ref_payload(group["responses"][0]) if group["responses"] else {}
    effect = response_payload.get("effect")
    effect = effect if isinstance(effect, dict) else {}
    event_types = trace_event_types(group["traces"])
    operations = sorted(
        {
            ref["operation"]
            for refs in group.values()
            for ref in refs
            if isinstance(ref.get("operation"), str)
        }
    )
    return {
        "request_id": request_id,
        "operation": operations[0] if len(operations) == 1 else None,
        "operations": operations,
        "classification": classify_request(group),
        "effect_state": effect.get("state"),
        "verification_status": (
            effect.get("verification", {}).get("status")
            if isinstance(effect.get("verification"), dict)
            else None
        ),
        "trace": {
            "event_types": event_types,
            "adapter_commit_started": "adapter.commit.started" in event_types,
            "effect_committed_event": "effect.committed" in event_types,
        },
        "records": {
            "request": [public_ref(ref) for ref in group["requests"]],
            "response": [public_ref(ref) for ref in group["responses"]],
            "trace": [public_ref(ref) for ref in group["traces"]],
            "error": [public_ref(ref) for ref in group["errors"]],
        },
    }


def public_ref(ref: dict[str, Any]) -> dict[str, Any]:
    """Return a record reference without internal-only fields."""

    return {key: value for key, value in ref.items() if key != "_payload"}


def export_service_records(
    *,
    service_root: Path,
    request_id: str | None = None,
    include_payload: bool = False,
) -> dict[str, Any]:
    """Export and summarize local service JSONL records without modifying them."""

    service_root = service_root.resolve()
    records_dir = service_root / "records"
    if not records_dir.is_dir():
        raise ServiceRecordsError(f"{records_dir} does not exist")

    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    streams: dict[str, Any] = {}
    for stream in STREAM_RECORD_TYPES:
        refs, stream_summary = read_stream(
            stream=stream,
            path=records_dir / f"{stream}.jsonl",
            service_root=service_root,
            include_payload=include_payload,
        )
        streams[stream] = stream_summary
        for ref in refs:
            ref_request_id = ref.get("request_id")
            if not isinstance(ref_request_id, str):
                ref_request_id = "unknown"
            if request_id is not None and ref_request_id != request_id:
                continue
            group = groups.setdefault(
                ref_request_id,
                {name: [] for name in STREAM_RECORD_TYPES},
            )
            group[stream].append(ref)

    summaries = [
        request_summary(group_request_id, group)
        for group_request_id, group in sorted(groups.items())
    ]
    return {
        "schema_version": "0.1",
        "record_type": "service_records_export",
        "status": "ok",
        "service_root": str(service_root),
        "records_dir": str(records_dir),
        "filters": {"request_id": request_id},
        "streams": streams,
        "request_count": len(summaries),
        "requests": summaries,
    }
