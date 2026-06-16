# Adding a Governed Adapter v0

**Created:** June 16, 2026
**Last Updated:** June 16, 2026
**Status:** Draft

---

> **Agents may propose; only governed effects may commit.**

An adapter is the only place an external-world effect actually happens. Everything
else — proposals, intents, scope checks, approval — is decision-making; the
adapter is where a decision becomes a committed change. This guide is the
concrete recipe for adding one, grounded in the three that exist.

## Reference adapters

| Effect | Module | What `committed` means |
|---|---|---|
| `file.write` | `file_adapter.py` | bytes written to a sandbox path, read back, SHA-256 matches |
| `memory.write` | `memory_adapter.py` | record appended to a scoped JSONL ledger, read back by id/version/hash |
| `network.fetch` | `network_adapter.py` | allowlisted URL fetched, response persisted to a sandbox file, read back, SHA-256 matches |

Read one before writing a new one. `file_adapter.py` is the canonical example.

## The contract

An adapter is a class satisfying the `GovernedAdapter` protocol (`runtime_ir.py`):

```python
class MyAdapter:
    adapter = "mykind"      # matches intent.adapter and the schema's adapter enum
    operation = "do"        # matches intent.operation
    capability = "mykind.do"  # matches intent.required_capability and a scope capability

    def prepare(self, scope, proposal, intent, trace) -> AdapterPreparation | EffectResult: ...
    def commit(self, scope, proposal, intent, trace, preparation) -> CommitEvidence | EffectResult: ...
```

The shared evaluator (`runtime_core.evaluate_with_adapter`) owns the whole state
machine — capability checks, the approval gate, trace events, pause/reject. **The
adapter never calls it.** The adapter only implements `prepare` and `commit`, and
a thin `evaluate_my_effect(...)` wrapper that hands its instance to
`evaluate_with_adapter`.

The `intent.adapter` value must be one of the schema's allowed kinds
(`file`, `db`, `message`, `memory`, `network`, `tool` in
`governed-effect-ir-v0.schema.json`). Reuse an existing kind (e.g. `network`)
rather than inventing one, or the records fail schema validation.

## `prepare` — validate, no side effects

`prepare` proves the effect is admissible and renders dry-run evidence. It must
not touch the world. On any problem it returns `reject(...)` with a structured
`RejectionReason`; otherwise it returns an `AdapterPreparation` carrying the
checks passed, a human dry-run summary, and a `payload` dict for `commit`.

Validate everything here: the target is in scope, inputs are well-formed and
under `scope.max_bytes`, and any addressing (paths, URLs) is **matched
structurally, never by substring**. (See the approval-condition and URL-allowlist
code: parse first, compare components — a `startswith` on a raw string is a
bypass waiting to happen.)

## `commit` — do the effect, then verify by read-back

`commit` crosses the world boundary and must prove it. The discipline every
adapter follows:

1. Perform the effect through a **symlink-safe, anchored** path. For filesystem
   persistence, write through an `O_NOFOLLOW` walk from the sandbox (temp file
   created with `O_EXCL | O_NOFOLLOW` anchored to a directory fd), never a bare
   `open(path)` — a symlink at any component otherwise redirects the write.
2. **Read the result back** and compare a SHA-256 (or equivalent) against what
   you intended. If it does not match, raise — do not return success.
3. Return `CommitEvidence(acknowledgement, verification, committed_at)` where
   `verification.status == "verified"`. Map any failure to `reject(...)`.

If your effect produces no durable artifact (a pure network read, say), persist
it to a scoped sandbox file so there *is* something to read back — that is what
`network.fetch` does, keeping the verification contract uniform.

## Fail closed, with structured reasons

Every rejection is a named `RejectionReason` enum value (`runtime_ir.py`), not a
bare string — so rejections are auditable and testable. Add new members for your
adapter's distinct failure modes (e.g. `network_url_not_in_allowlist`). When in
doubt, reject: an unrecognized or ambiguous input is a denial, never a pass.

## Scope extensions

If your adapter needs policy data the current `Scope` does not carry, add an
**optional, default-safe field** (e.g. `network_allow: tuple[str, ...] = ()`,
`allow_private_network: bool = False`). Other adapters ignore it; existing scopes
keep working. Parse it in `scope_from_record` (`runtime_api.py`). Prefer this
over a sweeping change to the core IR. Keep `Scope` hashable (use tuples, not
lists).

## Wiring

Three small edits register an adapter:

- `interpreter.py` — add an `intent.adapter == "..."` branch calling your
  evaluator with `_stop_at_approval=True` (so `interpret` never commits).
- `runtime_api.py` — add the same branch in `evaluate`'s `run` mode.
- `governed_effects.py` — re-export the adapter, evaluator, and sample helpers.

## Testing

Add acceptance cases to `self_tests.py` (`run_self_tests`), which the golden
checks run and schema-validate. Cover the full shape: a verified commit, an
approval-required pause, and one rejection per guard. For an external effect, the
test must be **hermetic** — stand up a loopback server (see the `network.fetch`
tests) so CI touches no real network. Run `fermata-golden-checks` and the
local-alpha validator (`scripts/validate_local_alpha.py`) before opening a PR.

## The one rule

If you cannot say precisely what `committed` means for your effect and how the
runtime verifies it, the adapter is not ready. That definition is the product.
