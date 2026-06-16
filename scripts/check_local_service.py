"""Check the loopback-only Fermata local service prototype."""

from __future__ import annotations

import json
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, TextIO
from urllib.error import HTTPError
from urllib.request import Request, urlopen


STARTUP_TIMEOUT_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 5
SHUTDOWN_TIMEOUT_SECONDS = 5


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from a checked-in fixture."""

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def fermata_command() -> str:
    """Return the installed fermata command path."""

    command = shutil.which("fermata")
    if command is None:
        raise AssertionError("fermata command is not installed")
    return command


def read_line_with_timeout(stream: TextIO, timeout: int) -> str:
    """Read one line without blocking forever."""

    lines: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_line() -> None:
        lines.put(stream.readline())

    thread = threading.Thread(target=read_line, daemon=True)
    thread.start()
    try:
        line = lines.get(timeout=timeout)
    except queue.Empty as exc:
        raise AssertionError("service did not emit startup JSON") from exc
    if not line:
        raise AssertionError("service exited before startup JSON")
    return line


def post_json(url: str, record: dict[str, Any]) -> dict[str, Any]:
    """POST a JSON object and return a JSON object."""

    request = Request(
        url,
        data=json.dumps(record).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read().decode("utf-8"))
    assert isinstance(data, dict)
    return data


def get_json(url: str) -> dict[str, Any]:
    """GET a JSON object response."""

    with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read().decode("utf-8"))
    assert isinstance(data, dict)
    return data


def read_http_error(exc: HTTPError) -> dict[str, Any]:
    """Read a JSON object HTTP error response."""

    data = json.loads(exc.read().decode("utf-8"))
    assert isinstance(data, dict)
    return data


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL stream into JSON objects."""

    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            assert isinstance(record, dict)
            records.append(record)
    return records


def run_cli_json(command: str, args: list[str]) -> dict[str, Any]:
    """Run the fermata CLI and return a JSON object."""

    result = subprocess.run(
        [command, *args],
        capture_output=True,
        text=True,
        timeout=REQUEST_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result
    data = json.loads(result.stdout)
    assert isinstance(data, dict)
    return data


def request_envelope(
    *,
    request_id: str,
    operation: str,
    scope: dict[str, Any],
    proposal: dict[str, Any],
    approval: dict[str, Any] | None = None,
    sandbox_root: str = "sandbox",
) -> dict[str, Any]:
    """Build a service request envelope."""

    envelope: dict[str, Any] = {
        "schema_version": "0.1",
        "record_type": "service_request",
        "request_id": request_id,
        "operation": operation,
        "caller": {"subject": "orchestrator:local-service-check"},
        "sandbox_root": sandbox_root,
        "scope": scope,
        "proposal": proposal,
    }
    if approval is not None:
        envelope["approval"] = approval
    return envelope


def escaped_proposal(source: dict[str, Any]) -> dict[str, Any]:
    """Return a proposal that should reject before adapter commit."""

    proposal = json.loads(json.dumps(source))
    proposal["proposal_id"] = "prop_service_escape_001"
    proposal["intent"]["proposal_id"] = "prop_service_escape_001"
    proposal["intent"]["intent_id"] = "intent_service_escape_001"
    proposal["intent"]["target"] = "../escape.txt"
    return proposal


def outside_root_request(source: dict[str, Any]) -> dict[str, Any]:
    """Return a request whose sandbox root escapes the service root."""

    request = json.loads(json.dumps(source))
    request["request_id"] = "svc_req_service_outside_root_001"
    request["sandbox_root"] = "../outside"
    return request


def parse_startup(line: str, *, expected_root: Path) -> dict[str, Any]:
    """Parse and validate the startup JSON record."""

    record = json.loads(line)
    assert isinstance(record, dict)
    assert record["record_type"] == "service_started"
    assert record["host"] == "127.0.0.1"
    assert isinstance(record["port"], int) and record["port"] > 0
    assert record["service_root"] == str(expected_root.resolve())
    assert record["loopback_only"] is True
    assert record["production"] is False
    return record


def stop_service(process: subprocess.Popen[str]) -> int:
    """Stop a running service process."""

    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        return process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        raise AssertionError("service did not stop after SIGINT") from exc


def check_non_loopback_guard(command: str, service_root: Path) -> str:
    """Verify the CLI refuses non-loopback bind hosts."""

    result = subprocess.run(
        [
            command,
            "service",
            "run",
            "--host",
            "0.0.0.0",
            "--port",
            "0",
            "--service-root",
            str(service_root),
        ],
        capture_output=True,
        text=True,
        timeout=STARTUP_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 2, result
    assert "non_loopback_bind_rejected" in result.stderr
    return "non_loopback_bind_rejected"


def run_service_check(command: str, root: Path) -> dict[str, Any]:
    """Run the service subprocess and exercise local endpoints."""

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
        health = get_json(f"{base}/health")
        assert health["status"] == "ok"
        assert health["loopback_only"] is True
        assert health["production"] is False

        scope = load_json(repo / "examples/local-alpha/file-scope.json")
        proposal = load_json(repo / "examples/local-alpha/file-write-proposal.json")
        approval = load_json(repo / "examples/local-alpha/file-write-approval.json")

        paused = post_json(
            f"{base}/v0/interpret",
            request_envelope(
                request_id="svc_req_service_interpret_001",
                operation="interpret",
                scope=scope,
                proposal=proposal,
            ),
        )
        assert paused["effect"]["state"] == "paused"
        paused_events = [event["type"] for event in paused["trace"]["events"]]
        assert "adapter.commit.started" not in paused_events
        assert not (service_root / "sandbox" / "cli-note.txt").exists()

        rejected = post_json(
            f"{base}/v0/run",
            request_envelope(
                request_id="svc_req_service_escape_001",
                operation="run",
                scope=scope,
                proposal=escaped_proposal(proposal),
            ),
        )
        assert rejected["effect"]["state"] == "rejected"
        assert rejected["effect"]["rejection_reason"] == "path_outside_scope"
        rejected_events = [event["type"] for event in rejected["trace"]["events"]]
        assert "adapter.commit.started" not in rejected_events
        assert not (service_root / "escape.txt").exists()

        committed = post_json(
            f"{base}/v0/run",
            request_envelope(
                request_id="svc_req_service_run_001",
                operation="run",
                scope=scope,
                proposal=proposal,
                approval=approval,
            ),
        )
        assert committed["effect"]["state"] == "committed"
        assert committed["effect"]["acknowledgement"]["adapter"] == "file"
        assert committed["effect"]["verification"]["status"] == "verified"
        assert (service_root / "sandbox" / "cli-note.txt").read_text(
            encoding="utf-8"
        ) == "Fermata CLI writes only through governed adapters.\n"

        try:
            post_json(
                f"{base}/v0/run",
                outside_root_request(committed_request(scope, proposal)),
            )
        except HTTPError as exc:
            outside_error = read_http_error(exc)
        else:
            raise AssertionError("outside service root request unexpectedly succeeded")
        assert outside_error["error"]["code"] == "scope_outside_service_root"

        records_dir = service_root / "records"
        requests = read_jsonl(records_dir / "requests.jsonl")
        responses = read_jsonl(records_dir / "responses.jsonl")
        traces = read_jsonl(records_dir / "traces.jsonl")
        errors = read_jsonl(records_dir / "errors.jsonl")
        assert len(requests) == 4
        assert len(responses) == 3
        assert len(traces) == 3
        assert len(errors) == 1
        for record in requests + responses + traces + errors:
            assert "payload_sha256" in record
            assert "stored_at" in record

        records_export = run_cli_json(
            command,
            ["service", "records", "--service-root", str(service_root)],
        )
        assert records_export["record_type"] == "service_records_export"
        assert records_export["status"] == "ok"
        assert records_export["request_count"] == 4
        assert records_export["streams"]["requests"]["records"] == 4
        assert records_export["streams"]["responses"]["records"] == 3
        assert records_export["streams"]["traces"]["records"] == 3
        assert records_export["streams"]["errors"]["records"] == 1
        classes = {
            row["request_id"]: row["classification"]
            for row in records_export["requests"]
        }
        assert classes == {
            "svc_req_service_escape_001": "rejected",
            "svc_req_service_interpret_001": "paused",
            "svc_req_service_outside_root_001": "service_error",
            "svc_req_service_run_001": "committed",
        }
        default_committed_row = next(
            row
            for row in records_export["requests"]
            if row["request_id"] == "svc_req_service_run_001"
        )
        assert "payload" not in default_committed_row["records"]["request"][0]
        committed_export = run_cli_json(
            command,
            [
                "service",
                "records",
                "--service-root",
                str(service_root),
                "--request-id",
                "svc_req_service_run_001",
                "--include-payload",
            ],
        )
        assert committed_export["request_count"] == 1
        committed_row = committed_export["requests"][0]
        assert committed_row["classification"] == "committed"
        assert committed_row["verification_status"] == "verified"
        assert committed_row["trace"]["adapter_commit_started"] is True
        request_ref = committed_row["records"]["request"][0]
        assert request_ref["payload"]["record_type"] == "service_request"

        return {
            "health_status": health["status"],
            "states": {
                "committed": committed["effect"]["state"],
                "paused": paused["effect"]["state"],
                "rejected": rejected["effect"]["state"],
            },
            "records": {
                "errors": len(errors),
                "requests": len(requests),
                "responses": len(responses),
                "traces": len(traces),
            },
            "records_export": {
                "classifications": classes,
                "committed_payload_included": "payload" in request_ref,
                "request_count": records_export["request_count"],
            },
        }
    finally:
        exit_code = stop_service(process)
        assert exit_code in {0, -signal.SIGINT}, exit_code


def committed_request(scope: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    """Return a basic run request envelope for mutation by negative tests."""

    return request_envelope(
        request_id="svc_req_service_run_outside_001",
        operation="run",
        scope=scope,
        proposal=proposal,
    )


def main() -> int:
    """Run local service checks and print machine-readable evidence."""

    command = fermata_command()
    with tempfile.TemporaryDirectory(prefix="fermata_service_check_") as tmp:
        root = Path(tmp)
        service_result = run_service_check(command, root)
        non_loopback = check_non_loopback_guard(command, root / "non-loopback-root")
    print(
        json.dumps(
            {
                "checks": {
                    "loopback_service": service_result,
                    "non_loopback_guard": non_loopback,
                },
                "command": command,
                "service": "local-service-v0",
                "status": "passed",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
