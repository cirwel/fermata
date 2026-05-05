# Governed Effect Language Charter v0

**Created:** May 05, 2026  
**Last Updated:** May 05, 2026  
**Status:** Draft

---

## 0. Chorus

> **Agents may propose; only governed effects may commit.**

This language exists to make agent-mediated side effects inspectable, bounded, reviewable, testable, and replayable. It is not another agent framework. It is the thin-waist contract between planners above and external-world effects below.

```text
orchestrators / agents / humans / workflows
              ↓ propose
canonical governed-effect IR + evaluator
              ↓ admit / reject / verify / approve / commit
external world: files, DBs, messages, memory, tools, deployments
```

The language succeeds only if it makes the dangerous boundary clearer: when a model-produced proposal becomes a real change in the world.

## 1. Purpose

The first version should expose a small runtime contract:

1. A human can define the scope, capabilities, policy gates, approval requirements, and audit expectations for a run.
2. An agent can propose needs, claims, doubts, memory candidates, boundaries, and concrete effect intents.
3. The runtime can normalize both surfaces into one typed IR.
4. The runtime can reject invalid transitions safely.
5. The runtime can say exactly when an effect is **committed**.

Primary center of gravity:

- **Governance + tool effects.**

Secondary centers:

- **Agent expression.** Public, typed speech acts for proposals and boundaries.
- **Verification.** Evidence and trace records before and after commit.

## 2. Non-Goals

This is not:

- a general-purpose replacement for Python, Elixir, JavaScript, Rust, or shell;
- a LangGraph/AutoGen/CrewAI competitor;
- YAML for workflows;
- a hidden chain-of-thought transcript;
- a permissionless autonomous action system;
- a full policy language in v0;
- a beautiful syntax exercise without an adapter that actually commits an effect.

If a feature does not help the first file-write adapter cross the proposal/commit boundary safely, defer it.

## 3. Authoring Split

There are three surfaces over one semantic core.

```text
human policy DSL ───────┐
                         ├─> canonical IR dataclasses ─> evaluator/state machine
agent JSON records ──────┘
```

### 3.1 Human surface

Humans write the world-boundaries:

- scopes;
- resources;
- capabilities;
- policy rules;
- approval gates;
- audit/evidence requirements.

Design pressure: boring, readable, diffable, reviewable.

### 3.2 Agent surface

Agents emit proposals:

- needs;
- claims;
- doubts;
- intents;
- memory candidates;
- boundaries/refusals;
- evidence references and confidence fields.

Design pressure: JSON-Schema-valid, low punctuation brittleness, easy for models to emit reliably.

### 3.3 Runtime surface

The runtime owns the canonical IR, state machine, adapters, trace log, and commit definition.

The agent cannot self-declare an effect committed. The human policy cannot make an effect committed by approving it. Only the runtime can move an effect to `CommittedEffect` after an adapter returns durable acknowledgement and verification evidence.

## 4. Minimal Grammar Budget

Resist expansion past the first **6 human constructs** and **6 agent speech acts** until the file-write adapter works end-to-end.

### 4.1 Human policy constructs

1. `scope` — names the bounded execution context.
2. `resource` — declares reachable external targets.
3. `capability` — declares allowed operation classes.
4. `policy` — declares admission rules.
5. `approval` — declares when human/council approval is required.
6. `audit` — declares trace/evidence retention requirements.

Example sketch:

```text
scope docs_sandbox {
  resource file "./sandbox/notes.md"
  capability file.read on "./sandbox/**"
  capability file.write on "./sandbox/**"

  policy deny if path.outside_scope
  approval require human if effect.kind == "file.write"
  audit retain trace, input_hash, output_hash, actor, approval
}
```

### 4.2 Agent speech acts

1. `need` — request a resource, tool, clarification, or permission.
2. `claim` — assert a public, evidence-bearing statement.
3. `doubt` — mark uncertainty or a competing interpretation.
4. `intend` — propose a typed external effect.
5. `remember` — propose a memory candidate, not a durable write.
6. `boundary` — refuse, pause, or narrow scope.

Example speech form:

```text
intend file.write target:"./sandbox/notes.md"
because "record the charter chorus for the next kata"
confidence 0.82
evidence [user_instruction, current_scope]
```

In v0, evidence, confidence, and reason are fields on speech acts, not separate grammar expansions.

## 5. State Machine

```text
Proposal
  ├─ reject: invalid shape / unsafe / irrelevant
  ↓
Intent
  ├─ reject: schema invalid / unknown adapter / malformed target
  ↓
AdmissibleEffect
  ├─ reject: missing capability / outside scope / policy denial
  ↓
VerifiedEffect
  ├─ reject: failed precondition / missing evidence / failed dry-run
  ↓
ApprovedEffect
  ├─ reject: human/council denial / timeout / stale approval
  ↓
CommittedEffect

Any state ──> RejectedEffect(reason, alternatives?, trace_id)
Any state ──> PausedEffect(reason, required_input?, trace_id)
```

### 5.1 State definitions

- `Proposal` — an agent or planner says something may be worth doing.
- `Intent` — the proposal has a typed effect shape and target.
- `AdmissibleEffect` — scope, capability, and policy checks passed.
- `VerifiedEffect` — required preconditions, evidence, dry-run, or tests passed.
- `ApprovedEffect` — required authority gate passed.
- `CommittedEffect` — the external target state changed or accepted the change, with durable acknowledgement.
- `RejectedEffect` — the transition failed safely and traceably.
- `PausedEffect` — the runtime needs human input, missing evidence, or narrower scope.

Invalid transitions are not bugs. They are the product.

## 6. Definition of `Committed`

`Committed` is the load-bearing definition.

> An effect is **committed** only after the governed runtime invokes the concrete effect adapter and obtains an adapter-specific durable acknowledgement that the external target state has changed or accepted the change.

A model output is not committed. An intent is not committed. A dry-run is not committed. A human approval is not committed. A tool call is not automatically committed.

The commit boundary is crossed only inside an effect adapter's commit operation:

```text
commit(adapter, approved_effect) -> CommitAck | CommitError
```

The adapter must return evidence sufficient for audit and, where possible, read-back verification.

### 6.1 Examples

| Effect kind | Committed means |
|---|---|
| File write | bytes written and closed/flushed; runtime can read back/stat/hash expected file revision |
| Database write | transaction committed; runtime receives DB acknowledgement or reads expected row/version |
| Message send | platform API returns accepted durable message ID |
| Memory write | memory backend acknowledges persisted record ID/version and trace linkage |
| Deployment | deployment API returns release ID and runtime can query resulting status |
| Tool side effect | tool returns a durable success handle sufficient for trace and verification |

### 6.2 Required committed record fields

A `CommittedEffect` should carry at least:

```text
state: "committed"
committed_at
adapter
actor_identity
scope_id
target
normalized_input_hash
acknowledgement
verification_status
trace_id
```

If an adapter cannot define acknowledgement and verification, it should remain dry-run-only.

## 7. Shared IR v0

The IR should begin as Python dataclasses or Pydantic models. Syntax should lower into these records; tests should inspect these records directly.

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

class EffectState(str, Enum):
    PROPOSAL = "proposal"
    INTENT = "intent"
    ADMISSIBLE = "admissible"
    VERIFIED = "verified"
    APPROVED = "approved"
    COMMITTED = "committed"
    REJECTED = "rejected"
    PAUSED = "paused"

@dataclass(frozen=True)
class Scope:
    id: str
    resources: list[dict[str, Any]]
    capabilities: list[dict[str, Any]]
    policies: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Proposal:
    id: str
    actor: str
    speech_act: Literal["need", "claim", "doubt", "intend", "remember", "boundary"]
    reason: str | None = None
    confidence: float | None = None
    evidence: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Intent:
    id: str
    proposal_id: str
    adapter: str
    operation: str
    target: str
    input: dict[str, Any]
    required_capability: str

@dataclass(frozen=True)
class EffectRecord:
    id: str
    state: EffectState
    intent_id: str
    scope_id: str
    trace_id: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    approval: dict[str, Any] | None = None
    acknowledgement: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
```

This is not the final type system. It is a pressure tool: if the dataclasses cannot represent the examples, fix the IR before inventing syntax.

## 8. Example: Human Policy Surface

```text
scope charter_note_sandbox {
  resource file "./sandbox/charter-note.txt"

  capability file.read on "./sandbox/**"
  capability file.write on "./sandbox/**"

  policy deny if target.outside_scope
  policy deny if input.bytes > 4096

  approval require human if effect.kind == "file.write"

  audit retain trace, dry_run, approval, input_hash, output_hash
}
```

This says: the agent may propose a write to one sandbox path, but the runtime must check scope, enforce size, request approval, and retain trace evidence.

## 9. Example: Agent JSON Surface

The agent surface should be JSON first, even if a speakable syntax exists later.

```json
{
  "schema_version": "0.1",
  "speech_act": "intend",
  "actor": "agent:hermes",
  "reason": "record the charter chorus for the next kata",
  "confidence": 0.82,
  "evidence": ["user:proceed", "scope:charter_note_sandbox"],
  "intent": {
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

The agent can propose this. It cannot commit it by saying so.

## 10. Example: Canonical IR Event Trace

```json
{
  "trace_id": "trace_001",
  "events": [
    {
      "type": "proposal.accepted",
      "proposal_id": "prop_001",
      "speech_act": "intend"
    },
    {
      "type": "intent.created",
      "intent_id": "intent_001",
      "adapter": "file",
      "operation": "write"
    },
    {
      "type": "policy.checked",
      "result": "allowed",
      "checks": ["inside_scope", "capability:file.write", "bytes_under_limit"]
    },
    {
      "type": "dry_run.rendered",
      "summary": "Write 54 bytes to ./sandbox/charter-note.txt"
    },
    {
      "type": "approval.granted",
      "approver": "human:kenny",
      "approval_id": "approval_001"
    },
    {
      "type": "effect.committed",
      "adapter": "file",
      "acknowledgement": {
        "path": "./sandbox/charter-note.txt",
        "sha256": "...",
        "bytes": 54
      }
    }
  ]
}
```

## 11. First Ugly Concrete Case: Governed File Write

After 5–10 katas, stop practicing and ship one boring adapter.

Required v0 path:

1. Human writes `scope charter_note_sandbox` granting `file.write` only under `./sandbox/**`.
2. Agent emits JSON-Schema-valid `intend file.write` for `./sandbox/charter-note.txt`.
3. Runtime lowers JSON to `Proposal` and `Intent` dataclasses.
4. Runtime validates adapter and operation.
5. Runtime checks resource path against scope.
6. Runtime checks capability `file.write`.
7. Runtime checks policy: target inside scope, content under 4096 bytes.
8. Runtime renders dry-run: path, bytes, hash, diff/new-file status.
9. Runtime requests approval if policy requires it.
10. Human approval produces `ApprovedEffect`.
11. File adapter writes bytes to a temp path or directly, closes/flushed safely, and renames if needed.
12. Runtime reads back stat/hash evidence.
13. Runtime emits `CommittedEffect` with acknowledgement and trace.
14. Failure at any step emits `RejectedEffect` or `PausedEffect`, not an invisible partial action.

Acceptance tests:

- allowed sandbox write commits and produces matching hash;
- path escape is rejected before adapter commit;
- missing capability is rejected;
- approval-required path pauses before commit;
- failed read-back produces commit error or rejected/uncertain verification state;
- trace contains actor, scope, intent, checks, approval, adapter acknowledgement.

## 12. Success Test

The language earns the next step only if the file-write case is clearer, safer, or more auditable than a direct Python call such as:

```python
Path("./sandbox/charter-note.txt").write_text(content)
```

The advantage must be visible in the trace and failure behavior, not in nicer punctuation.

If the governed runtime can say:

```text
This write was proposed by agent:hermes,
inside scope charter_note_sandbox,
admitted by policies A/B/C,
approved by human:kenny,
committed by file adapter at time T,
verified by sha256 H,
and recorded in trace trace_001.
```

then the language has a real reason to exist.

## 13. Cut Line

Before adding another construct, ask:

1. Does it help define, admit, reject, verify, approve, commit, or trace an effect?
2. Does it help an agent express a public need, claim, doubt, intent, memory candidate, or boundary?
3. Does it help a human define scope, capability, policy, approval, or audit?
4. Does it make the first file-write adapter safer or clearer?

If not, cut or defer it.
