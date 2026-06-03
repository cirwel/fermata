# Ugly Trace v0

**Created:** May 09, 2026
**Status:** Draft

---

This document shows the boring path Fermata is trying to make auditable:

```text
agent proposal
-> typed intent
-> scope and capability checks
-> dry-run evidence
-> typed approval decision
-> adapter commit
-> read-back verification
-> optional durable trace ledger append
```

The point is not pretty syntax. The point is that every boundary is visible and
the agent never gets to self-declare an external-world effect committed.

## Scope

The v0 Python scope is intentionally narrow:

```python
Scope(
    scope_id="charter_note_sandbox",
    sandbox_root=Path("/tmp/fermata/sandbox").resolve(),
    capabilities=frozenset({"file.read", "file.write"}),
    approval_required_for=frozenset({"file.write"}),
    max_bytes=4096,
)
```

This says the runtime may consider `file.write` proposals inside one sandbox, but
the effect still needs approval before commit.

## Proposal and Intent

The agent proposal is public and typed:

```python
Proposal(
    proposal_id="prop_file_write_001",
    actor="agent:hermes",
    speech_act="intend",
    reason="record the charter chorus for the next kata",
    confidence=0.82,
    evidence=["user:proceed", "scope:charter_note_sandbox"],
    intent=Intent(
        intent_id="intent_file_write_001",
        proposal_id="prop_file_write_001",
        adapter="file",
        operation="write",
        target="charter-note.txt",
        input={
            "content": "Agents may propose; only governed effects may commit.\n"
        },
        required_capability="file.write",
    ),
)
```

This is still only a proposal. It has not touched the filesystem.

## Approval Decision

Approval is a record bound to the scope and intent, not an ambient boolean:

```python
ApprovalDecision(
    status=ApprovalStatus.APPROVED,
    authority=ApprovalAuthority.PERFORMER,
    approval_id="approval_1234abcd",
    approver="performer:steward",
    decided_at="2026-05-09T18:00:00Z",
    scope_id="charter_note_sandbox",
    intent_id="intent_file_write_001",
    intent_sha256="<sha256 of canonical intent>",
)
```

A human is not the loop here. If a person is present, they appear as a
performer or authority recorded in the approval evidence. That person does not
need to be a coder; the record should show the plain role that held or released
the boundary. The runtime still owns commit.

Approval is not technical verification. A calculator should not ask a person to
prove its arithmetic, and Fermata should not ask a steward to verify path
resolution, hashes, byte counts, schema validity, or read-back evidence. The
runtime owns those checks. The approval decision answers whether the already
rendered effect is wanted, authorized, and in scope.

New approval paths should pass this typed record to the evaluator. The older
`approval_granted=True` shortcut is legacy compatibility only; it cannot carry
the same explicit approver, reason, expiry, and intent-binding evidence.

Compatibility note: earlier draft traces may contain `authority: "human"`.
Treat that as legacy authoring language and migrate it to
`authority: "performer"` with the concrete actor preserved in `approver`, for
example `performer:steward`. New v0 records should not emit
`authority: "human"`.

If the approval is denied, expired, bound to another scope, bound to another
intent, or carries a mismatched intent hash, the runtime rejects before adapter
commit.

## Trace Shape

A successful governed file write emits trace events like:

```json
[
  {"type": "proposal.received"},
  {"type": "intent.created"},
  {"type": "policy.checked"},
  {"type": "dry_run.rendered"},
  {"type": "approval.granted"},
  {"type": "adapter.commit.started"},
  {"type": "effect.committed"}
]
```

Rejected and paused traces are equally important. For example, a missing approval
produces `approval.requested` and `effect.paused`, and never produces
`adapter.commit.started`.

## Adapter Boundary

The shared evaluator owns the state-machine spine:

```text
proposal shape
-> intent shape
-> capability check
-> adapter.prepare
-> approval gate
-> adapter.commit
-> committed effect record
```

Each adapter owns only the effect-specific parts:

```text
prepare(scope, proposal, intent, trace) -> AdapterPreparation | RejectedEffect
commit(scope, proposal, intent, trace, preparation) -> CommitEvidence | RejectedEffect
```

`prepare` must not touch the external world. It validates adapter-specific input
and renders dry-run evidence. `commit` is the only place an adapter may cross the
external-world boundary, and it must return acknowledgement plus verification.

## Committed Effect

For `file.write`, committed means:

```text
target parent opened by walking from the sandbox without following symlinks
+ late symlink or no-overwrite races rejected before final target change
+ bytes written to a temp file relative to the opened parent directory
+ temp bytes fsynced
+ temp bytes read back and hashed without following symlinks
+ temp file linked into place without overwrite, or renamed when overwrite is explicit
+ parent directory fsynced when available
+ final target read back without following symlinks and SHA-256 verified
+ effect record carries adapter acknowledgement and verification evidence
```

The resulting effect record includes the approval record, acknowledgement,
verification, commit timestamp, scope, intent, and trace ID.

## Trace Ledger

Trace ledger writes are explicit. They are not part of pure interpretation.

```python
evidence = append_trace_ledger(scope, trace)
```

The local ledger appends a JSONL trace record under:

```text
<sandbox>/.fermata-traces/traces.jsonl
```

The ledger write fsyncs the record and verifies it by reading the appended trace
back by `trace_id` and line hash. This makes audit persistence a separate,
inspectable effect instead of hidden logging.

## Denial Evidence

The v0 golden checks cover denial and pause paths including:

- non-intent proposals;
- malformed target, input, or content;
- path escapes;
- missing capability;
- spoofed capability;
- missing approval;
- denied approval;
- mismatched approval intent hash;
- symlink target and symlink path components;
- adapter commit errors.

A safe rejection is a valid runtime outcome. It proves the boundary is working.
