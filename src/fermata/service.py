"""Loopback-only local HTTP service for Fermata runtime records."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fermata.runtime_api import RuntimeApiError, interpret, run
from fermata.runtime_ir import canonical_json_bytes, now_timestamp, sha256_bytes


MAX_REQUEST_BYTES = 1_000_000


class ServiceError(ValueError):
    """Raised when a service envelope or boundary check fails."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: HTTPStatus = HTTPStatus.BAD_REQUEST,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class AppendOnlyStore:
    """Append-only JSONL records rooted under one local service directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.records_dir = self.root / "records"
        self._lock = threading.Lock()

    def path_for(self, stream: str) -> Path:
        """Return a named JSONL stream path."""

        return self.records_dir / f"{stream}.jsonl"

    def append(self, stream: str, record: dict[str, Any]) -> dict[str, Any]:
        """Append and verify one JSON object record."""

        self.records_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")
        line_hash = sha256_bytes(data)
        path = self.path_for(stream)
        with self._lock:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "ab") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or sha256_bytes((lines[-1] + "\n").encode("utf-8")) != line_hash:
            raise ServiceError(
                "append_verification_failed",
                f"could not verify append to {path}",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return {
            "stream": stream,
            "path": str(path),
            "sha256": line_hash,
            "bytes": len(data),
        }


class FermataServiceServer(ThreadingHTTPServer):
    """HTTP server carrying local Fermata service configuration."""

    service_root: Path
    store: AppendOnlyStore


def is_loopback_host(host: str) -> bool:
    """Return true when a host resolves only to loopback addresses."""

    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not infos:
        return False
    try:
        return all(ipaddress.ip_address(info[4][0]).is_loopback for info in infos)
    except ValueError:
        return False


def require_object(value: Any, *, label: str) -> dict[str, Any]:
    """Return a JSON object or raise a service error."""

    if not isinstance(value, dict):
        raise ServiceError("invalid_service_envelope", f"{label} must be a JSON object")
    return value


def require_string(record: dict[str, Any], field: str, *, label: str) -> str:
    """Return a required non-empty string field."""

    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ServiceError(
            "invalid_service_envelope",
            f"{label}.{field} must be a non-empty string",
        )
    return value


def operation_from_path(path: str) -> str:
    """Return the service operation for an HTTP request path."""

    parsed = urlparse(path).path
    if parsed == "/v0/interpret":
        return "interpret"
    if parsed == "/v0/run":
        return "run"
    raise ServiceError(
        "unknown_endpoint",
        "supported endpoints are GET /health, POST /v0/interpret, POST /v0/run",
        status=HTTPStatus.NOT_FOUND,
    )


def validate_request(record: Any, *, expected_operation: str) -> dict[str, Any]:
    """Validate a local service request envelope."""

    envelope = require_object(record, label="request")
    if envelope.get("schema_version") != "0.1":
        raise ServiceError(
            "invalid_service_envelope",
            "request.schema_version must be '0.1'",
        )
    if envelope.get("record_type") != "service_request":
        raise ServiceError(
            "invalid_service_envelope",
            "request.record_type must be 'service_request'",
        )
    request_id = require_string(envelope, "request_id", label="request")
    if not request_id.startswith("svc_req_"):
        raise ServiceError(
            "invalid_service_envelope",
            "request.request_id must use the svc_req_ prefix",
        )
    operation = require_string(envelope, "operation", label="request")
    if operation != expected_operation:
        raise ServiceError(
            "operation_path_mismatch",
            f"request.operation {operation!r} does not match endpoint "
            f"{expected_operation!r}",
        )
    caller = require_object(envelope.get("caller"), label="request.caller")
    require_string(caller, "subject", label="request.caller")
    require_object(envelope.get("scope"), label="request.scope")
    require_object(envelope.get("proposal"), label="request.proposal")
    if "approval" in envelope:
        require_object(envelope["approval"], label="request.approval")
    return envelope


def service_record(
    *,
    record_type: str,
    request_id: str,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return a service persistence wrapper."""

    return {
        "schema_version": "0.1",
        "record_type": record_type,
        "stored_at": now_timestamp(),
        "request_id": request_id,
        "operation": operation,
        "payload_sha256": sha256_bytes(canonical_json_bytes(payload)),
        "payload": payload,
    }


def resolve_sandbox_root(envelope: dict[str, Any], service_root: Path) -> Path:
    """Resolve a request sandbox root under the service root."""

    scope = require_object(envelope.get("scope"), label="request.scope")
    raw = envelope.get("sandbox_root", scope.get("sandbox_root", "sandbox"))
    if not isinstance(raw, str) or not raw:
        raise ServiceError(
            "invalid_service_envelope",
            "request.sandbox_root must be a non-empty string when present",
    )
    candidate = Path(raw)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (service_root / candidate).resolve()
    )
    try:
        resolved.relative_to(service_root.resolve())
    except ValueError as exc:
        raise ServiceError(
            "scope_outside_service_root",
            "request sandbox_root must resolve inside the service root",
        ) from exc
    return resolved


def response_envelope(
    *,
    request_id: str,
    operation: str,
    effect: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    """Return a service response envelope."""

    return {
        "schema_version": "0.1",
        "record_type": "service_response",
        "request_id": request_id,
        "operation": operation,
        "status": "ok",
        "effect": effect,
        "trace": trace,
    }


def error_envelope(error: ServiceError) -> dict[str, Any]:
    """Return a service error envelope."""

    return {
        "schema_version": "0.1",
        "record_type": "service_error",
        "status": "error",
        "error": {"code": error.code, "message": error.message},
    }


class FermataServiceHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local Fermata service."""

    server: FermataServiceServer

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr request logging."""

    def write_json(self, status: HTTPStatus, record: dict[str, Any]) -> None:
        """Write one JSON response."""

        data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        """Handle service health checks."""

        if urlparse(self.path).path != "/health":
            self.write_json(
                HTTPStatus.NOT_FOUND,
                error_envelope(
                    ServiceError(
                        "unknown_endpoint",
                        "supported endpoint is GET /health",
                        status=HTTPStatus.NOT_FOUND,
                    )
                ),
            )
            return
        host, port = self.server.server_address[:2]
        self.write_json(
            HTTPStatus.OK,
            {
                "schema_version": "0.1",
                "record_type": "service_health",
                "status": "ok",
                "service": "fermata-local-service",
                "production": False,
                "loopback_only": True,
                "append_only_records": True,
                "host": host,
                "port": port,
                "service_root": str(self.server.service_root),
                "supported_operations": ["interpret", "run"],
            },
        )

    def do_POST(self) -> None:
        """Handle interpret and run service requests."""

        try:
            operation = operation_from_path(self.path)
            body = self.read_body()
            envelope = validate_request(body, expected_operation=operation)
            request_id = envelope["request_id"]
            self.server.store.append(
                "requests",
                service_record(
                    record_type="service_request_item",
                    request_id=request_id,
                    operation=operation,
                    payload=envelope,
                ),
            )
            sandbox_root = resolve_sandbox_root(envelope, self.server.service_root)
            approval = envelope.get("approval")
            output = (
                interpret(
                    envelope["scope"],
                    envelope["proposal"],
                    approval=approval,
                    sandbox_root=sandbox_root,
                )
                if operation == "interpret"
                else run(
                    envelope["scope"],
                    envelope["proposal"],
                    approval=approval,
                    sandbox_root=sandbox_root,
                )
            )
            response = response_envelope(
                request_id=request_id,
                operation=operation,
                effect=output.effect,
                trace=output.trace,
            )
            self.server.store.append(
                "responses",
                service_record(
                    record_type="service_response_item",
                    request_id=request_id,
                    operation=operation,
                    payload=response,
                ),
            )
            self.server.store.append(
                "traces",
                service_record(
                    record_type="service_trace_item",
                    request_id=request_id,
                    operation=operation,
                    payload=output.trace,
                ),
            )
            self.write_json(HTTPStatus.OK, response)
        except RuntimeApiError as exc:
            self.handle_service_error(
                ServiceError("runtime_api_error", str(exc)),
                request_id=locals().get("request_id"),
                operation=locals().get("operation", "unknown"),
            )
        except ServiceError as exc:
            self.handle_service_error(
                exc,
                request_id=locals().get("request_id"),
                operation=locals().get("operation", "unknown"),
            )

    def read_body(self) -> dict[str, Any]:
        """Read and parse one JSON request body."""

        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as exc:
            raise ServiceError(
                "invalid_content_length",
                "Content-Length is invalid",
            ) from exc
        if length < 1:
            raise ServiceError("empty_request_body", "request body is required")
        if length > MAX_REQUEST_BYTES:
            raise ServiceError("request_too_large", "request body exceeds local limit")
        data = self.rfile.read(length)
        try:
            record = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServiceError("invalid_json", "request body must be valid JSON") from exc
        return require_object(record, label="request")

    def handle_service_error(
        self,
        error: ServiceError,
        *,
        request_id: str | None,
        operation: str,
    ) -> None:
        """Persist and return a service error."""

        envelope = error_envelope(error)
        if request_id is not None:
            envelope["request_id"] = request_id
        envelope["operation"] = operation
        self.server.store.append(
            "errors",
            service_record(
                record_type="service_error_item",
                request_id=request_id or "unknown",
                operation=operation,
                payload=envelope,
            ),
        )
        self.write_json(error.status, envelope)


def build_server(host: str, port: int, service_root: Path) -> FermataServiceServer:
    """Build a configured local service server."""

    if not is_loopback_host(host):
        raise ServiceError(
            "non_loopback_bind_rejected",
            "the local service prototype only binds to loopback hosts",
        )
    service_root = service_root.resolve()
    service_root.mkdir(parents=True, exist_ok=True)
    server = FermataServiceServer((host, port), FermataServiceHandler)
    server.service_root = service_root
    server.store = AppendOnlyStore(service_root)
    return server


def run_service(*, host: str, port: int, service_root: Path) -> int:
    """Run the loopback-only local service until interrupted."""

    try:
        server = build_server(host, port, service_root)
    except ServiceError as exc:
        print(json.dumps(error_envelope(exc), sort_keys=True), file=sys.stderr)
        return 2
    actual_host, actual_port = server.server_address[:2]
    print(
        json.dumps(
            {
                "schema_version": "0.1",
                "record_type": "service_started",
                "status": "ok",
                "host": actual_host,
                "port": actual_port,
                "service_root": str(server.service_root),
                "loopback_only": True,
                "production": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the service CLI parser."""

    parser = argparse.ArgumentParser(
        prog="fermata service run",
        description="Run the loopback-only Fermata local service prototype.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--service-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Service CLI entry point."""

    args = build_parser().parse_args(argv)
    return run_service(
        host=args.host,
        port=args.port,
        service_root=args.service_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
