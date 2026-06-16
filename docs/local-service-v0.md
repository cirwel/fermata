# Local Service v0

**Created:** June 16, 2026
**Last Updated:** June 16, 2026
**Status:** Draft

---

> **Agents may propose; only governed effects may commit.**

This document describes the local alpha HTTP service exposed by:

```bash
fermata service run --host 127.0.0.1 --port 8765 --service-root /tmp/fermata-service
```

The service is a loopback-only transport wrapper around the same runtime API used
by the CLI. It is not a hosted production service, approval UI, scheduler,
multi-user authorization layer, or remote adapter boundary.

## Supported Endpoints

```text
GET  /health
POST /v0/interpret
POST /v0/run
```

`/health` returns service metadata, including `loopback_only: true`,
`production: false`, and the configured `service_root`.

`/v0/interpret` evaluates a proposal without committing an external-world
effect.

`/v0/run` may commit only through a governed adapter and only when the runtime
state machine permits it.

## Request Envelope

Requests use an outer service envelope:

```json
{
  "schema_version": "0.1",
  "record_type": "service_request",
  "request_id": "svc_req_example_001",
  "operation": "interpret",
  "caller": {
    "subject": "orchestrator:local"
  },
  "sandbox_root": "sandbox",
  "scope": {},
  "proposal": {}
}
```

For `run`, callers may include `approval` as a canonical approval record.

`sandbox_root` is optional and defaults to `sandbox`. It may be absolute or
relative, but it must resolve inside `--service-root`. Requests that try to run
outside the service root fail before runtime evaluation.

## Response Envelope

Successful responses preserve public effect and trace records:

```json
{
  "schema_version": "0.1",
  "record_type": "service_response",
  "request_id": "svc_req_example_001",
  "operation": "interpret",
  "status": "ok",
  "effect": {},
  "trace": {}
}
```

Malformed service envelopes return service errors instead of effect states:

```json
{
  "schema_version": "0.1",
  "record_type": "service_error",
  "status": "error",
  "error": {
    "code": "invalid_service_envelope",
    "message": "request.record_type must be 'service_request'"
  }
}
```

Service errors are transport and envelope failures. Runtime denials still return
normal `service_response` records whose `effect.state` is `rejected`.

## Persistence

The service appends JSONL records under:

```text
--service-root/records/
  requests.jsonl
  responses.jsonl
  traces.jsonl
  errors.jsonl
```

Each stored item includes:

- `schema_version`;
- `record_type`;
- `stored_at`;
- `request_id`;
- `operation`;
- `payload_sha256`;
- `payload`.

The service writes with append mode, fsyncs the file, and verifies the appended
line hash before returning.

Read-only record export is available through the CLI:

```bash
fermata service records --service-root /tmp/fermata-service
fermata service records \
  --service-root /tmp/fermata-service \
  --request-id svc_req_example_001 \
  --include-payload
```

The export groups service records by `request_id`, verifies wrapper
`payload_sha256` values, includes line hashes, and classifies each request group
as `committed`, `paused`, `rejected`, `service_error`, `incomplete`, or
`needs_review`. Payloads are omitted unless `--include-payload` is passed.

## Local Boundaries

The local service enforces:

- bind host must resolve only to loopback addresses;
- request sandbox roots must resolve under `--service-root`;
- only `interpret` and `run` are exposed;
- malformed service envelopes are recorded as service errors;
- committed effects still require adapter acknowledgement and runtime
  verification.

It does not provide:

- authentication;
- multi-user authorization;
- approval queues;
- hosted persistence guarantees;
- process isolation for adapters;
- remote adapter safety;
- cryptographic trace sealing;
- exactly-once execution.

## Validation

Run:

```bash
python3 scripts/check_local_service.py
```

The checker starts the installed `fermata service run` command on
`127.0.0.1` with port `0`, then verifies:

- `/health`;
- interpret pauses without adapter commit;
- path escape rejects before adapter commit;
- approved run commits with acknowledgement and verification;
- outside-service-root requests return a service error;
- request, response, trace, and error records are appended;
- `fermata service records` exports grouped record summaries and can filter by
  `request_id`;
- `--host 0.0.0.0` is rejected.

This check is part of `python3 scripts/validate_local_alpha.py`.

## Recovery Evidence

When reviewing service incidents or incomplete local runs, use the recovery
evidence templates in:

```text
references/recovery-evidence-templates-v0/
```

The packet is documented in [recovery-evidence-v0.md](recovery-evidence-v0.md)
and checked by:

```bash
python3 scripts/check_recovery_evidence.py
```

The templates are evidence records only. They do not add automatic retry,
rollback, approval, hosted trace APIs, or production incident response.
