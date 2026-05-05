# Governed Effect Katas v0

**Created:** May 05, 2026  
**Last Updated:** May 05, 2026  
**Status:** Draft

---

## Rule

These are slow-practice exercises, not an infinite conservatory. Stop at 5–10 katas, then implement the boring file-write adapter end-to-end.

A kata passes only if it lowers to the shared IR and produces either an admissible next state or a traceable rejection/pause.

## Human Policy / Scope Katas

### Kata H1 — Minimal sandbox scope

Human surface:

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

Human surface:

```text
scope charter_note_sandbox {
  resource file "./sandbox/charter-note.txt"
  capability file.write on "./sandbox/**"
  policy deny if target.outside_scope
}
```

Agent counterexample:

```text
intend file.write target:"../secrets.txt"
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

Human surface:

```text
scope charter_note_sandbox {
  resource file "./sandbox/charter-note.txt"
  capability file.write on "./sandbox/**"
  approval require human if effect.kind == "file.write"
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

Human surface:

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

## Exit Gate

Do not add kata A5/H5 until the first adapter work begins.

The next real artifact after these katas is:

```text
file.write adapter spike
  scope -> proposal -> intent -> admissible -> verified -> approved -> committed/rejected
```

Acceptance for the adapter spike:

- allowed write commits with matching read-back hash;
- path escape is rejected before adapter call;
- missing capability is rejected before adapter call;
- approval-required write pauses before commit;
- trace records every transition.
