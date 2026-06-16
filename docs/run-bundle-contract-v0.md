# Run Bundle Contract v0

**Created:** June 16, 2026
**Last Updated:** June 16, 2026
**Status:** Draft

---

> **Agents may propose; only governed effects may commit.**

This contract describes the local alpha run-bundle directory consumed by
`fermata bundle run`.

The bundle exists so a person, CI job, or orchestrator can inspect the same
scope, proposal, approval, effect, and trace records without importing Fermata
internals or relying on chat transcripts.

## Directory Shape

A bundle directory contains input records and runtime output records:

```text
fermata-run/
  scope.json          # required input
  proposal.json       # required input
  approval.json       # optional input
  effect.json         # produced by bundle run
  trace.json          # produced by bundle run
```

Generated adapter side effects may also appear under paths named by `scope.json`,
usually a local `sandbox/` directory.

## Inputs

`scope.json` may use canonical Scope capabilities or the local alpha shorthand:

```json
{
  "scope_id": "example_bundle",
  "sandbox_root": "sandbox",
  "capabilities": ["file.read", "file.write"],
  "approval_required_for": ["file.write"],
  "max_bytes": 4096
}
```

If `sandbox_root` is relative, it is resolved relative to the bundle directory.
If it is omitted, the runtime uses `<bundle>/sandbox`.

`proposal.json` must be a canonical Proposal record with
`schema_version: "0.1"` and `record_type: "proposal"`.

`approval.json`, when present, may be either a bare approval record or a wrapper
with an `approval` object. It is an authorization record, not commit evidence.

## Run Command

Run:

```bash
fermata bundle run path/to/bundle
```

The command writes `effect.json` and `trace.json`, and prints:

```json
{
  "status": "ok",
  "bundle": {
    "path": "...",
    "scope": ".../scope.json",
    "proposal": ".../proposal.json",
    "approval": ".../approval.json",
    "effect": ".../effect.json",
    "trace": ".../trace.json"
  },
  "effect": {},
  "trace": {}
}
```

`fermata bundle run` refuses to overwrite existing `effect.json` or `trace.json`
unless `--overwrite` is passed.

## State Expectations

With required approval and no `approval.json`:

- `effect.state` is `paused`;
- `effect.required_input` is `approval_decision`;
- `adapter.commit.started` is absent from the trace;
- external side effects are not committed.

With no required approval, or with valid `approval.json`:

- an admissible effect may become `committed`;
- committed effects include adapter `acknowledgement`, `verification`, and
  `committed_at`.

With malformed or out-of-scope input:

- `effect.state` is `rejected`;
- `effect.rejection_reason` explains the governed denial;
- adapter commit is not started for precommit denials.

## Stability Boundary

Stable for local alpha consumers:

- file names: `scope.json`, `proposal.json`, `approval.json`, `effect.json`,
  `trace.json`;
- top-level output keys: `status`, `bundle`, `effect`, `trace`;
- state names: `paused`, `rejected`, `committed`;
- committed-effect requirement for `acknowledgement`, `verification`, and
  `committed_at`;
- trace event `type` fields.

Draft/unstable:

- generated IDs and timestamps;
- trace event payload details beyond `type` and `at`;
- adapter-specific acknowledgement fields beyond `adapter`, `target`, and
  `handle`.

## Checked Example

The checked-in skeleton is:

```text
examples/local-alpha/run-bundle/
  scope.json
  proposal.json
```

The compatibility fixtures live under:

```text
references/run-bundle-contract-fixtures-v0/
```

Run:

```bash
python3 scripts/check_run_bundle_contract.py
```

The checker copies each fixture bundle to a temporary directory, invokes only the
installed `fermata` command, and asserts stable contract fields for paused,
rejected, and committed outputs.
