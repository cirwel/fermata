# Recovery Evidence v0

**Created:** June 16, 2026
**Last Updated:** June 16, 2026
**Status:** Draft

---

> **Agents may propose; only governed effects may commit.**

This document defines the local-alpha recovery evidence packet for the Fermata
loopback service. It is an operator evidence format, not an automatic retry,
rollback, approval queue, or production incident system.

Use it when the local service has records under:

```text
--service-root/records/
  requests.jsonl
  responses.jsonl
  traces.jsonl
  errors.jsonl
```

The templates live in:

```text
references/recovery-evidence-templates-v0/
  service-incident-report-template.json
  service-reconciliation-report-template.json
```

## Recovery Packet

A recovery packet has two parts:

1. **Incident report** - names what was observed, which request IDs are in
   scope, which service records were inspected, and what decision is being
   proposed for local use.
2. **Reconciliation report** - groups append-only service records by
   `request_id`, verifies record wrappers, classifies the runtime outcome, and
   identifies unmatched or incomplete records.

The packet does not create a committed effect. It records public evidence for a
person or higher-level governance process to review.

## Evidence Rules

For each referenced service record, capture:

- stream name: `requests`, `responses`, `traces`, or `errors`;
- relative JSONL path, such as `records/responses.jsonl`;
- line number in the archived JSONL stream;
- service wrapper `record_type`;
- `request_id` and `operation`;
- wrapper `payload_sha256`;
- computed `line_sha256` for the full JSONL line when available;
- a small public payload excerpt when useful.

The wrapper `payload_sha256` is the SHA-256 hash of Fermata canonical JSON bytes
for the wrapper payload. The service writes this field for every append-only
record.

## Reconciliation Procedure

1. Quiesce the local service when possible. If it cannot be quiesced, record the
   time window and treat the packet as a point-in-time observation.
2. Copy or otherwise preserve `--service-root/records/` before editing anything.
3. Parse every non-empty JSONL line in the four service streams.
4. Recompute each wrapper `payload_sha256`.
5. Group records by `request_id`.
6. Classify each request group:
   - `service_error` when an error record exists and no runtime effect was
     produced;
   - `paused` when a response effect is paused;
   - `rejected` when a response effect is rejected;
   - `committed` only when a response effect is committed and carries adapter
     acknowledgement plus verification evidence;
   - `incomplete` when a request is missing the response, trace, or error
     needed to classify it.
7. Compare trace events with the effect state. Treat mismatches as
   `needs_review`.
8. Record the operator decision as a proposal or next safe step, not as an
   automatic authority grant.

Do not infer that a rejected effect made no external change unless the trace and
adapter evidence support that narrower claim. Some rejections can happen before
adapter work; others can represent adapter-level failure. The report should say
which evidence it used.

## Validation

Run:

```bash
fermata service records --service-root /tmp/fermata-service
python3 scripts/check_recovery_evidence.py
```

The `service records` command exports grouped read-only summaries from the local
service JSONL streams. The checker validates the template files and exercises
the same service record wrapper helpers used by the local service. It is also
part of:

```bash
python3 scripts/validate_local_alpha.py
```

Passing this check means the recovery evidence templates are internally
consistent with local service record streams. It does not mean Fermata has
automatic recovery, hosted persistence, hosted trace lookup APIs, or production
incident response.
