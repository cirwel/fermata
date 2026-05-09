# Runtime Contract and Authoring Model

**Created:** May 05, 2026  
**Last Updated:** May 05, 2026  
**Status:** Active

---

## Core Position

Do not let the project become **YAML for workflows**. Workflow notation is crowded and weakly differentiated. The differentiated product is the runtime contract around effect admission:

> **Agents may propose; only governed effects may commit.**

The language is not primarily a nicer way to draw workflows. It is the surface area for a type/state model that controls how proposals become real-world effects.

## Charter Contents for the First Serious Doc

The first serious charter should be short enough to finish — roughly 5–10 pages — and should resist feature expansion. A useful target is:

1. **Purpose and non-goals** — substrate for governed effects, not another agent framework.
2. **Minimal grammar** — keep the authority surface and agent surface intentionally tiny; resist growth beyond the first 6 authority constructs and 6 agent speech acts until concrete examples demand it.
3. **Drawn state machine** — proposal → intent → admissible → verified → approved/rejected → committed.
4. **One example per surface** — authority policy/scope DSL, agent JSON/utterance proposal, canonical IR.
5. **Shared IR definition** — the typed records all surfaces lower into.
6. **Definition of `committed`** — the load-bearing runtime definition of when the external world has actually changed.
7. **One ugly concrete case** — a file write end-to-end through the contract.

If the charter cannot define `committed`, the rest is probably aesthetic rather than operational.

## Positioning

The strongest pitch is:

> This sits under Hermes/UNITARES as the governed-effect substrate that other orchestration systems could target.

Do not position it as a LangGraph/AutoGen/CrewAI competitor. Those systems can remain planners, graph builders, agent routers, or workflow authors. This layer answers a lower-level question:

```text
Given an agent-produced proposal,
under which identity, scope, policy, evidence, approval, and risk state
may it become a committed effect?
```

In compiler terms, this is closer to a **thin-waist effect IR + evaluator** than an application framework.

Substrate position is the durable position: orchestrators above, governed runtime in the middle, committed effects below.

## Authoring Model: Who Writes It?

This question must be answered before syntax design. The recommended first answer is a two-strata model.

### 1. Performers and operators write policy, scope, and reviewable boundaries

Optimize this layer for operational readability and trust.

Performers and operators write or review:

- scopes and capabilities
- policy gates
- approval rules
- risk budgets
- memory retention rules
- audit/export requirements
- high-level contracts for tools and effects

Approval rules are about authorization, intent, and risk ownership. They are
not a mechanism for asking the approver to verify technical facts the runtime
can calculate itself.

Example:

```text
scope docs_only_review {
  resources: files("docs/**")
  capabilities: file.read, file.patch, tests.markdown
  memory: session.write, project.read
  risk_budget: low
  require approval if effect.destructive
}
```

Design pressure: clear, boring, diffable, reviewable. Operators need to trust it.

### 2. Agents emit intents, claims, evidence, needs, and proposed effects

Optimize this layer for reliable LLM emission and machine parsing.

Agents emit:

- intent records
- need/request records
- claims and confidence
- evidence references
- boundary/refusal statements
- proposed tool/effect calls
- memory candidates
- questions for performer or council review

Example:

```text
intent file.patch target:"docs/charter.md"
because "update the project purpose after reviewer feedback"
confidence 0.78
evidence [user_feedback, prior_trace]
```

Design pressure: simple grammar, low punctuation brittleness, schema-valid, easy for models to produce consistently.

## Worked Example: Concrete Lowering

The two surfaces are not theoretical. As of issue #3, both lower into the
same canonical IR records and both are exercised in the golden test suite.

### Authority policy → canonical Scope record

A governing performer writes (parsed by ``src/fermata/policy_parser.py``):

```text
scope charter_note_sandbox {
  resource file "./sandbox/charter-note.txt"
  capability file.read on "./sandbox/**"
  capability file.write on "./sandbox/**"
  policy deny if path.outside_scope
  approval require performer if effect.kind == "file.write"
  audit retain trace, input_hash, output_hash, actor, approval
}
```

The parser produces a JSON-Schema-valid Scope record:

```json
{
  "schema_version": "0.1",
  "record_type": "scope",
  "scope_id": "charter_note_sandbox",
  "resources": [{"kind": "file", "target": "./sandbox/charter-note.txt"}],
  "capabilities": [
    {"name": "file.read",  "resource_kind": "file", "mode": "read",  "allow": ["./sandbox/**"]},
    {"name": "file.write", "resource_kind": "file", "mode": "write", "allow": ["./sandbox/**"]}
  ],
  "policies":  [{"id": "policy_001", "effect": "deny", "condition": "path.outside_scope"}],
  "approvals": [{"authority": "performer", "condition": "effect.kind == \"file.write\""}],
  "audit":     {"retain": ["trace", "input_hash", "output_hash", "actor", "approval"]}
}
```

This is the authority surface. It owns: `scope_id`, `resources`, `capabilities`,
`policies`, `approvals`, `audit`. It does *not* own commit state, adapter
acknowledgement, verification status, or trace events — those belong to the
runtime.

### Agent JSON proposal → canonical Proposal record

An agent emits (validated by the IR JSON Schema):

```json
{
  "schema_version": "0.1",
  "record_type": "proposal",
  "proposal_id": "prop_surface_test_001",
  "actor": "agent:hermes",
  "speech_act": "intend",
  "reason": "split-surfaces kata",
  "confidence": 0.81,
  "evidence": ["scope:charter_note_sandbox"],
  "payload": {"utterance": "intend file.write target:\"./sandbox/note.txt\""},
  "intent": {
    "intent_id": "intent_surface_test_001",
    "proposal_id": "prop_surface_test_001",
    "adapter": "file",
    "operation": "write",
    "target": "./sandbox/note.txt",
    "input": {"content": "boring proof\n"},
    "required_capability": "file.write"
  }
}
```

This is the agent surface. It owns: `proposal_id`, `actor`, `speech_act`,
`reason`, `confidence`, `evidence`, `payload`, and (for `intend` speech
acts) the embedded `intent`. It does *not* own commit state — see below.

### Neither surface can self-declare a committed effect

Two structural defenses against either surface trying to bypass the runtime:

**Agent injection.** If an agent emits a Proposal-shape record but tries to
include `state: "committed"` and a forged `acknowledgement`, schema
validation rejects it because the `Proposal` record uses
`additionalProperties: false`. A `CommittedEffect` requires
adapter-supplied `acknowledgement` + `verification` + `committed_at`,
which only the runtime can produce. Tested in
`run_self_tests` as `agent_cannot_inject_committed_state` and validated by
`check_surfaces` in `src/fermata/golden_checks.py`.

**Authority inline grant.** The authority-policy parser has no `approval grant
...` construct — the authority surface declares *requirements*
(`approval require performer if ...`), not granted approvals. A grant only
exists at runtime, when the runtime receives an explicit approval record or
approval flag. Tested in `run_self_tests` as
`authority_policy_cannot_inline_grant`.

The cut-line: the runtime is the only authority that can produce a
`CommittedEffect`. Both surfaces describe what *should be allowed* or
*what is being proposed*; neither surface can describe what *has
happened*.

## Consequence for Syntax

There may not be one syntax. There may be three surfaces over one semantic core:

1. **Canonical IR** — typed records used by runtimes and tests.
2. **Authority policy surface** — readable contracts for scope/policy/review gates.
3. **Agent utterance surface** — compact speech acts optimized for LLM emission.

All three compile/normalize to the same runtime contract.

A practical v0 architecture is:

```text
authority policy DSL ───┐
                         ├─> canonical IR dataclasses ─> evaluator/state machine
agent JSON Schema records ┘
```

For the first implementation, prefer **Python dataclasses or Pydantic models as the IR**. Let the authority DSL be a thin layer over those records, and let the agent surface be JSON-Schema-validated records that lower into the same classes. This avoids debating syntax before the runtime contract has executable semantics.

## Minimal Type/State Model

The core entities:

- `Proposal` — agent says something may be worth doing.
- `Intent` — proposal has a typed target/effect shape.
- `AdmissibleEffect` — policy/capability/scope checks have passed.
- `VerifiedEffect` — required evidence has passed.
- `ApprovedEffect` — performer/council/model authority gate has passed when needed.
- `CommittedEffect` — the external world changed.
- `RejectedEffect` — denied with reason and possible alternatives.
- `Trace` — durable record of transitions and evidence.

State transition sketch:

```text
Proposal
  -> Intent
  -> AdmissibleEffect     # scope + capability + policy
  -> VerifiedEffect       # tests/evidence/checks
  -> ApprovedEffect       # if required
  -> CommittedEffect      # only here external reality changes
```

Invalid transitions are the product. A system that can reject or pause safely is more important than one that can run workflows prettily.

## Definition of Committed

`Committed` must have a precise runtime meaning. Proposed definition for v0:

> An effect is **committed** only after the governed runtime invokes the concrete effect adapter and obtains an adapter-specific durable acknowledgement that the external target state has changed or accepted the change.

Examples:

- **File write:** bytes were written, flushed/closed, and the runtime can read back or stat the expected file revision/hash.
- **Database write:** transaction committed and the runtime received the database commit acknowledgement or can read the written row/version.
- **Message send:** platform API accepted the message and returned a durable message ID.
- **Memory write:** memory backend acknowledged persistence with an ID/version and trace linkage.
- **Tool call with side effect:** the tool returned a success handle sufficient for audit or verification.

A tool call is not automatically a commit. A model output is not a commit. A dry-run is not a commit. An approval is not a commit. `CommittedEffect` is the state after the runtime crosses the external-world boundary and records evidence that the crossing happened.

Every committed effect should carry at least:

```text
committed_at
adapter
target
input_hash or normalized_input
acknowledgement/handle
verification_status
trace_id
actor_identity
scope_id
```

If the runtime cannot define acknowledgement and verification for an effect adapter, that adapter should remain experimental or dry-run-only.

## Katas Then One Boring Concrete Case

Katas are useful slow practice, but the failure mode is over-katas-ing: a beautiful library nobody programs in. After 5–10 katas, force contact with one ugly concrete case.

Recommended first concrete case:

> Implement one file write end-to-end through the runtime contract.

Required path:

```text
authority scope grants file.write for one sandbox path
agent proposes a file.write intent as JSON
runtime validates schema
runtime checks scope/capability/policy
runtime renders dry-run
runtime obtains required approval, if any
runtime commits through a file adapter
runtime reads back hash/stat evidence
runtime emits CommittedEffect or RejectedEffect trace
```

If the language survives this case, it can earn a second adapter. If it cannot, cut syntax or semantics until it can.

## Integration Thesis

- Hermes supplies execution surfaces, tool schemas, skills, gateway UX, sessions, and platform delivery.
- UNITARES supplies identity, governance state, dialectic, calibration, outcome events, and durable semantic memory.
- LangGraph/AutoGen/etc. could supply plans or graphs that emit proposals into this substrate.
- The native tongue gives agents a public expressive layer for proposing, doubting, asking, remembering, and stating boundaries.

## Design Rule

When choosing between syntax elegance and effect-admission clarity, choose effect-admission clarity.

When choosing between operator authorability and LLM emission reliability, split the surface but keep one semantic core.

When choosing between more katas and one real effect adapter, ship the boring adapter.
