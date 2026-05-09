# Governed Effect Katas v0

**Created:** May 05, 2026
**Last Updated:** May 06, 2026
**Status:** Draft

---

## Rule

These are slow-practice exercises, not an infinite conservatory. Stop at 5–10 katas, then implement the boring file-write adapter end-to-end.

A kata passes only if it lowers to the shared IR and produces either an admissible next state or a traceable rejection/pause.

## Authority Policy / Scope Katas

### Kata H1 — Minimal sandbox scope

Authority surface:

```text
scope charter_note_sandbox {
  resource file "./sandbox/charter-note.txt"
  capability file.read on "./sandbox/**"
  capability file.write on "./sandbox/**"
  audit retain trace, actor, scope
}
```

Expected IR pressure:

- `Scope.resources[0].kind == "file"`
- `Scope.capabilities` contains `file.read` and `file.write`
- no approval required yet

Pass condition:

- agent `file.write` intent to `./sandbox/charter-note.txt` can reach `AdmissibleEffect`.

### Kata H2 — Path escape denial

Authority surface:

```text
scope charter_note_sandbox {
  resource file "./sandbox/charter-note.txt"
  capability file.write on "./sandbox/**"
  policy deny if target.outside_scope
}
```

Agent counterexample:

```text
intend file.write target:"../outside-scope.txt"
because "save a shortcut note"
```

Expected trace:

```text
proposal.accepted
intent.created
policy.checked result:denied reason:path_outside_scope
effect.rejected
```

Pass condition:

- adapter commit is never called.

### Kata H3 — Approval gate before commit

Authority surface:

```text
scope charter_note_sandbox {
  resource file "./sandbox/charter-note.txt"
  capability file.write on "./sandbox/**"
  approval require performer if effect.kind == "file.write"
  audit retain trace, dry_run, approval
}
```

Expected trace before approval:

```text
proposal.accepted
intent.created
policy.checked result:allowed
dry_run.rendered
approval.requested
effect.paused
```

Pass condition:

- the effect cannot become `CommittedEffect` until an approval record exists.

### Kata H4 — Audit requires commit evidence

Authority surface:

```text
scope charter_note_sandbox {
  resource file "./sandbox/charter-note.txt"
  capability file.write on "./sandbox/**"
  audit retain trace, input_hash, output_hash, adapter_ack, verification
}
```

Expected committed record fields:

```text
acknowledgement.sha256
acknowledgement.bytes
verification.status == "verified"
verification.method == "read_back_sha256"
```

Pass condition:

- runtime refuses to report `CommittedEffect` without adapter acknowledgement and verification status.

## Agent Speech / Intent Katas

### Kata A1 — Need before action

Agent surface:

```text
need file.read target:"docs/charter.md"
because "verify before editing"
confidence 0.93
evidence [skill:ai-language-design, rule:read_first]
```

Expected normalized proposal:

```json
{
  "speech_act": "need",
  "payload": {
    "need": {
      "kind": "tool",
      "capability": "file.read",
      "target": "docs/charter.md"
    }
  }
}
```

Pass condition:

- no external effect is committed; runtime may schedule/allow a read request if scope grants it.

### Kata A2 — Claim with evidence and doubt

Agent surface:

```text
claim "effect creation is not effect execution"
confidence 0.88
evidence [state_machine]

doubt approved_means_committed
because "adapter acknowledgement is missing"
```

Expected normalized proposals:

- one `claim` record;
- one `doubt` record;
- both preserve public evidence references;
- neither leaks hidden chain-of-thought.

Pass condition:

- renderer can produce a warm Discord-readable version without changing semantics.

### Kata A3 — File write intent

Agent JSON surface:

```json
{
  "schema_version": "0.1",
  "record_type": "proposal",
  "proposal_id": "prop_file_write_001",
  "actor": "agent:hermes",
  "speech_act": "intend",
  "reason": "record the charter chorus for the next kata",
  "confidence": 0.82,
  "evidence": ["user:proceed", "scope:charter_note_sandbox"],
  "payload": {
    "utterance": "intend file.write target:\"./sandbox/charter-note.txt\""
  },
  "intent": {
    "intent_id": "intent_file_write_001",
    "proposal_id": "prop_file_write_001",
    "adapter": "file",
    "operation": "write",
    "target": "./sandbox/charter-note.txt",
    "input": {
      "content": "Agents may propose; only governed effects may commit.\n"
    },
    "required_capability": "file.write"
  }
}
```

Pass condition:

- JSON validates;
- runtime lowers to `Proposal` and `Intent`;
- policy decides the next state.

### Kata A4 — Boundary when approval is missing

Agent/runtime surface:

```text
boundary cannot commit effect:file.write
reason approval_missing
offer dry_run_patch instead
```

Expected normalized proposal:

```json
{
  "speech_act": "boundary",
  "payload": {
    "boundary": "cannot commit file.write without required approval",
    "offer": "render dry-run and request approval"
  }
}
```

Pass condition:

- the language makes pause/refusal productive rather than vague.

## Lifecycle Katas

These six katas exercise the *full state-machine lifecycle* end-to-end, one
case per outcome class. Each kata is grounded in a specific golden fixture
in `references/tongue-golden-tests-v0.json` so the kata is executable, not
just illustrative. The pattern for each kata:

- **Scope** — the authority-policy setup that bounds the agent's authority.
- **Proposal** — the agent utterance that triggers the lifecycle.
- **Expected state** — `committed` / `paused` / `rejected`.
- **Expected trace shape** — the ordered event types the trace must contain.
- **What a Discord reader sees** — the warm, one-paragraph summary an
  observer would read. This is the "user-visible result"
  required by issue #5.
- **Golden fixture** — the name of the corresponding entry in
  `references/tongue-golden-tests-v0.json` and `run_self_tests`.

The lifecycle katas are reusable: the same scope can be paired with each
proposal to show the full surface in slow practice.

### Kata L1 — Allowed commit (the boring proof)

**Scope.** A sandbox that grants `file.write` on `./sandbox/**` and
requires no approval.

**Proposal.** Agent emits `intend file.write target:"./sandbox/charter-note.txt"`
with content "Agents may propose; only governed effects may commit.\n".

**Expected state.** `committed`.

**Expected trace shape (in order).**

```text
proposal.received
intent.created
policy.checked        result:allowed
dry_run.rendered
approval.granted      authority:runtime
adapter.commit.started
effect.committed      acknowledgement:{adapter:"file", sha256:..., bytes:54}
```

**What a Discord reader sees.**

> Agent `hermes` proposed a file write to `./sandbox/charter-note.txt`.
> The runtime admitted the proposal under scope
> `charter_note_sandbox`, granted runtime approval (no performer gate),
> and committed 54 bytes via the file adapter. Read-back verification
> matched the proposed SHA-256.

**Golden fixture.** `allowed_write_commits` (file_write_adapter section).

### Kata L2 — Missing capability

**Scope.** A sandbox that grants `file.read` only — no `file.write`.

**Proposal.** Same file-write intent as L1.

**Expected state.** `rejected` with reason `missing_capability`.

**Expected trace shape.**

```text
proposal.received
intent.created
effect.rejected       reason:missing_capability
```

The trace stops before any policy check, dry-run, or adapter touch.
`adapter.commit.started` never appears.

**What a Discord reader sees.**

> Agent `hermes` proposed a file write, but the active scope only
> grants `file.read`. The runtime rejected the intent before the
> file adapter was even consulted. No bytes were written.

**Golden fixture.** `missing_capability_rejected` (file_write_adapter section).

### Kata L3 — Outside scope

**Scope.** Sandbox grants `file.write` on `./sandbox/**`.

**Proposal.** Agent emits `intend file.write target:"../outside-scope.txt"` —
a path that resolves outside the sandbox root.

**Expected state.** `rejected` with reason `path_outside_scope`.

**Expected trace shape.**

```text
proposal.received
intent.created
effect.rejected       reason:path_outside_scope
```

The trace records the rejection with the resolved target and the sandbox
root, so an auditor can see *what* was attempted and *which boundary*
caught it. No adapter call. No temp file.

**What a Discord reader sees.**

> Agent `hermes` proposed a file write to `../outside-scope.txt`.
> After path resolution, the target sat outside the
> `charter_note_sandbox` root. The runtime rejected the intent
> before any adapter work; nothing was written, and the rejection
> trace records both the proposed path and the sandbox boundary.

**Golden fixture.** `path_escape_rejected` (file_write_adapter section).

### Kata L4 — Approval pause

**Scope.** Sandbox grants `file.write` *and* requires performer approval for
`file.write` effects.

**Proposal.** Same file-write intent as L1, but the runtime is called
without `approval_granted=True`.

**Expected state.** `paused` with `required_input: approval_decision`.

**Expected trace shape.**

```text
proposal.received
intent.created
policy.checked        result:allowed
dry_run.rendered      summary:"Write 54 bytes to ./sandbox/needs-approval.txt"
approval.requested    authority:performer
effect.paused         required_input:approval_decision
```

The dry-run is rendered so the approving performer can decide whether the
effect should proceed. The performer is not asked to verify hashes, path math,
or adapter mechanics. No temp file is created. `adapter.commit.started` never
appears.

**What a Discord reader sees.**

> Agent `hermes` proposed a file write that policy admits, but the
> scope requires performer approval. The runtime rendered the dry-run
> (54 bytes to `./sandbox/needs-approval.txt`) and paused, waiting
> for an explicit authorization decision. Nothing has been written yet;
> the next runtime call with approval will commit only if runtime checks
> still pass.

**Golden fixture.** `approval_required_pauses` (file_write_adapter section).

### Kata L5 — Malformed proposal

**Scope.** Any sandbox; this kata fails before policy.

**Proposal.** Agent emits a `claim` speech act (not `intend`), or an
`intend` with missing/non-string `content`. Either form fails the
shape gate.

**Expected state.** `rejected` with reason `proposal_is_not_an_intent`
(for the wrong-speech-act variant) or `content_missing_or_not_string`
(for the malformed-intent variant).

**Expected trace shape (claim variant).**

```text
proposal.received
effect.rejected       reason:proposal_is_not_an_intent
```

**Expected trace shape (malformed-intent variant).**

```text
proposal.received
intent.created
effect.rejected       reason:content_missing_or_not_string
```

In both cases, no policy check, no dry-run, no adapter.

**What a Discord reader sees (claim variant).**

> Agent `hermes` made a `claim` ("effect creation is not effect
> execution"), not an effect intent. The runtime accepted the claim
> as a public utterance but did not lower it to a proposed effect;
> nothing was scheduled or committed. Claims are not commits.

**Golden fixtures.** `non_intent_rejected` and `content_missing_rejected`
(file_write_adapter section).

### Kata L6 — Adapter verification failure

**Scope.** Sandbox grants `file.write` on `./sandbox/**`.

**Proposal.** File-write intent to a path whose parent is a regular file
(not a directory) — e.g., `./sandbox/blocked-parent/file.txt` where
`./sandbox/blocked-parent` already exists as a file.

This is the "adapter started, then failed" case. Policy admits the
proposal; the runtime begins the commit; the filesystem operation
fails because the parent is not a directory.

**Expected state.** `rejected` with reason `adapter_commit_failed`.

**Expected trace shape.**

```text
proposal.received
intent.created
policy.checked        result:allowed
dry_run.rendered
approval.granted      authority:runtime
adapter.commit.started
adapter.commit.failed error_type:NotADirectoryError
effect.rejected       reason:adapter_commit_failed
```

This trace shape is the *whole point* of distinguishing policy
rejection (no `adapter.commit.started`) from adapter error
(`adapter.commit.started` plus `adapter.commit.failed`) — see issue #1
for the parallel distinction with `verification.failed` for
post-rename hash mismatch.

**What a Discord reader sees.**

> Agent `hermes` proposed a file write to
> `./sandbox/blocked-parent/file.txt`. Policy admitted the
> proposal, and the file adapter began the commit, but the
> filesystem rejected the temp-file creation because
> `./sandbox/blocked-parent` is itself a file, not a directory.
> The runtime cleaned up any partial temp state and reported the
> failure. The commit boundary was *not* crossed: nothing was
> written under the intended target.

**Golden fixture.** `adapter_error_rejected` (file_write_adapter section).

## Exit Gate

The original v0 gate said:

> Do not add kata A5/H5 until the first adapter work begins.

That gate is now open: the file-write adapter (PR #1 race hardening)
and the memory-write adapter (PR #2) are both shipped, and an explicit
interpreter (issue #4) exposes the state-machine spine. The lifecycle
katas above use those adapters and that interpreter as their substrate.

The next discipline is *not* to grow the kata list to A5/A6/A7 etc. for
its own sake. The lifecycle katas (L1–L6) are intended as *slow practice
before performance*: a fixed set, repeatedly walked, that exercises every
outcome class the runtime can produce. New katas should be added only
when:

1. a new adapter ships with a behavior the lifecycle katas do not yet
   demonstrate (e.g., a deployment adapter with a verification-after-poll
   shape distinct from `read-back-sha256`);
2. a new failure mode is identified that none of L1–L6 covers (e.g., the
   `verification.failed` post-rename mismatch from PR #1 hardening, which
   is currently exercised in code but not yet promoted to its own kata
   because triggering it deterministically requires fault injection);
3. or the authority-policy DSL gains a construct that changes the shape of
   admission traces (issue #3).

Resist adding katas that only restate L1–L6 with a different adapter.
The discipline is in the lifecycle, not the variation.
