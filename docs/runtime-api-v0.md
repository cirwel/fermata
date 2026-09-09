# Runtime API v0

**Created:** June 16, 2026
**Last Updated:** June 16, 2026
**Status:** Draft

---

> **Agents may propose; only governed effects may commit.**

This document names the local alpha Python import surface for host applications
that should not shell out to `fermata`.

The API accepts public scope, proposal, and approval records or the runtime
dataclasses. It returns public effect and trace records. It does not expose
hidden reasoning or let callers self-declare committed effects.

## Import Surface

```python
from fermata import interpret, run
```

Stable for local alpha callers:

```python
interpret(scope, proposal, *, approval=None, sandbox_root=None, max_bytes=4096)
run(scope, proposal, *, approval=None, sandbox_root=None, max_bytes=4096)
```

Both functions return `RuntimeOutput`:

```python
output.effect  # canonical effect record
output.trace   # canonical trace record
output.state   # effect["state"]
```

`scope`, `proposal`, and `approval` may be runtime dataclasses or JSON-like
records. When `scope` is a record, `sandbox_root` is required because canonical
scope records name authority and capability; they do not own a host filesystem
root by themselves.

Malformed public records raise `RuntimeApiError`.

## Interpret

`interpret` runs the governed state machine without committing an external-world
effect.

Expected outcomes:

- `approved` when the proposal clears admission and approval checks and would be
  ready for a real adapter commit;
- `paused` when approval or narrower input is required;
- `rejected` when shape, scope, capability, policy, or approval checks fail.

For `interpret`, committed adapter evidence is absent:

- no `adapter.commit.started` event;
- no `effect.committed` event;
- no `acknowledgement`;
- no `committed_at`.

## Run

`run` may commit only through a governed adapter.

For local alpha, the public dispatcher supports:

- `file.write`;
- `memory.write`.

Expected outcomes:

- `committed` only after adapter acknowledgement and runtime verification;
- `approved` when the intent declared `record_only` custody and cleared every
  check without committing;
- `paused` when approval is required and absent;
- `rejected` when a denial path is reached.

### Declared custody

`intent.custody_mode` names who performs the effect, before the run terminates.

- `execute`, or the field unset, is the committing path above.
- `record_only` runs the whole governed pipeline and stops before the adapter
  commit. An external actor performs the effect.

`record_only` reaches `approved` rather than `committed`, and every terminal
result carries `effect.custody_mode` so an auditor reading the record can tell
which custody produced it. Under `run`, an `approved` outcome therefore means
one of two different things, distinguished by that field: a `record_only` effect
that cleared every check, or a dry run that was never going to commit.

Record-only custody skips the commit and nothing else. The idempotency conflict
check and the scope rate budget both apply, because the effect still reaches the
world. What it does **not** get is an idempotency record: fermata records no
completed effect for a commit it did not perform, so retry-replay is the
external actor's responsibility, not the runtime's.

Committed outputs include:

```text
effect.state == "committed"
effect.acknowledgement
effect.verification
effect.committed_at
trace.events includes effect.committed
```

## Example

```python
import json
import tempfile
from pathlib import Path

from fermata import interpret, run

scope = json.loads(Path("examples/local-alpha/file-scope.json").read_text())
proposal = json.loads(Path("examples/local-alpha/file-write-proposal.json").read_text())
approval = json.loads(Path("examples/local-alpha/file-write-approval.json").read_text())

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    paused = interpret(scope, proposal, sandbox_root=root)
    assert paused.state == "paused"
    assert "acknowledgement" not in paused.effect

    committed = run(scope, proposal, approval=approval, sandbox_root=root)
    assert committed.state == "committed"
    assert committed.effect["verification"]["status"] == "verified"
```

## Validation

Run:

```bash
python3 scripts/check_runtime_api.py
```

The checker calls the package-level API, not CLI subprocesses. It verifies:

- `file.write` interpret pauses without touching the target;
- `file.write` path escape rejects before adapter commit;
- `file.write` run commits with acknowledgement and verification;
- `memory.write` interpret pauses without appending a ledger record;
- `memory.write` run commits with acknowledgement and verification;
- malformed public records raise `RuntimeApiError`.

This check is part of `python3 scripts/validate_local_alpha.py`.

## Non-Claims

This API is a local alpha import surface. It does not claim:

- hosted service readiness;
- multi-user authentication or authorization;
- process isolation for adapters;
- remote adapter safety;
- cryptographic trace sealing;
- exactly-once execution.

It is the stable local boundary for host code that wants public effect and trace
records without importing Fermata internals.
