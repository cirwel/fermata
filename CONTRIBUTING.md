# Contributing to Fermata

**Created:** May 05, 2026
**Last Updated:** May 06, 2026
**Status:** Active

---

> **Agents may propose; only governed effects may commit.**

Fermata welcomes contributions from humans, agents, and model-assisted workflows,
but every contribution should preserve the core boundary: model output is a
proposal, not a committed external-world effect. Contributions should make the
runtime contract more inspectable, bounded, testable, replayable, and useful.

## Required Reading

Before opening a non-trivial change, read:

1. `README.md` — project identity, state model, and checks.
2. `docs/charter-v0.md` — semantic charter and definition of `committed`.
3. `docs/runtime-contract-authoring-model.md` — human policy surface, agent
   proposal surface, and shared IR.
4. `docs/tongue-eval-rubric-v0.md` — human taste/eval criteria.
5. `AGENTS.md` — short operational rules for coding agents working in this repo.

## Contribution Priorities

Prefer changes in this order:

1. Clarify the governed-effect contract.
2. Add or tighten executable examples and denial-path tests.
3. Improve schemas, traces, and evidence capture.
4. Refactor the boring file-write spike into a small reusable runtime module.
5. Improve docs and diagrams that make proposal/intent/commit boundaries clearer.

Do not prioritize syntax bikeshedding, ecosystem scaffolding, or broad agent
framework features before the runtime contract is sharper.

## Agent and Model Coordination Contract

When humans coordinate multiple agents or models, use explicit roles. One model
should not silently perform every role.

| Role | Responsibility | Boundary |
|---|---|---|
| Human steward | Defines scope, risk tolerance, and merge authority | Owns final acceptance |
| Implementer agent/model | Proposes patches, tests, docs, schemas, or examples | Does not self-approve |
| Spec reviewer agent/model | Checks whether the change matches the stated task | Reviews scope compliance first |
| Quality reviewer agent/model | Checks maintainability, safety, tests, and clarity | Reviews after spec fit |
| Runtime/eval agent/model | Runs validation and summarizes evidence | Reports results, not authority |

For small docs changes, one agent may implement and self-check, but the PR should
still state what was verified. For runtime changes, separate implementer and
reviewer roles are preferred.

## Agent/Model Disclosure in PRs

If an AI model or agent materially contributed to a change, include a concise
coordination note in the PR body:

```text
Agent/model involvement:
- Implementer: <agent/model/tool, if known>
- Reviewer: <agent/model/tool, if used>
- Human steward: <person approving scope>
- Scope granted: <files/resources/tools touched>
- Effects performed: <file writes, commands, tests, network/API calls>
- Evidence: <tests, traces, logs, schema validation, manual review>
- Uncertainty/deferred questions: <known doubts or follow-ups>
```

Do not include hidden chain-of-thought. Use structured rationale, assumptions,
evidence, decision records, and known doubts instead.

## Safe Model Usage

Models may help with:

- proposing examples, schemas, tests, and documentation;
- refactoring small, well-scoped modules;
- generating denial-path cases;
- reviewing diffs against the charter and rubric;
- summarizing test evidence and open questions.

Models must not:

- treat their own output as verified truth;
- widen scope silently;
- commit secrets, credentials, tokens, passwords, or connection strings;
- perform destructive or external effects without explicit scope and approval;
- hide uncertainty behind confident prose;
- make Fermata depend on private chain-of-thought capture;
- blur proposal, approval, and committed-effect states.

If a real secret appears in logs or source, redact it as `[REDACTED]`, assume
rotation is needed, and consider history cleanup before widening access.

When sharing evidence, summarize and redact raw prompts, tool logs, API payloads,
local machine details, personal data, proprietary endpoints, and any externally
provided confidential material. Keep enough structure for review without turning
the PR into a transcript dump.

## Handoff Packet Template

Use this when passing work between humans, agents, or models:

```markdown
## Task
<one focused change>

## Scope
Allowed files/resources:
- <path or resource>

Out of scope:
- <what not to touch>

## Relevant docs
- README.md
- docs/charter-v0.md
- docs/runtime-contract-authoring-model.md

## Current state
- Branch: <branch>
- Unrelated WIP: <none / list paths to avoid>
- Known failing checks: <none / list>

## Required gates
- [ ] Scope gate: no unrelated files touched
- [ ] Evidence gate: tests or explicit manual verification attached
- [ ] Safety gate: no hidden chain-of-thought, no secrets, no widened authority
- [ ] Review gate: spec and quality review complete for runtime changes
- [ ] SCM commit gate: only intended files staged and pushed
```

## Local Workflow

1. Start from a clean or explicitly understood working tree:

   ```bash
   git status --short --branch
   ```

2. Create a focused branch for non-trivial work:

   ```bash
   git checkout main
   git pull origin main
   git checkout -b docs/short-description
   ```

3. Read before editing. For runtime changes, trace the relevant code path before
   proposing a fix.
4. Keep changes small. A good change should fit one sentence.
5. Stage only intended files:

   ```bash
   git add <intended paths>
   git diff --cached --name-only
   ```

6. Use conventional Git commit messages:

   ```text
   docs: clarify agent contribution protocol
   feat: add governed effect evaluator module
   test: add denial-path golden trace
   fix: reject path escapes before adapter commit
   ```

## Validation

For docs-only changes, run the lightweight checks when possible:

```bash
python3 -m compileall scripts src
python3 -m json.tool references/governed-effect-ir-v0.schema.json >/tmp/fermata_schema.json
python3 -m json.tool references/tongue-golden-tests-v0.json >/tmp/fermata_golden.json
python3 scripts/run_tongue_golden_tests.py
```

For runtime changes, add or update golden fixtures and include denial paths. At
minimum, verify:

- allowed file write commits with read-back evidence;
- path escape is rejected before adapter commit;
- missing capability is rejected before adapter commit;
- approval-required write pauses without touching the target.

When this guide says **Git commit** or **SCM commit**, it means a version-control
commit. When Fermata says **committed effect**, it means the runtime state reached
after a governed adapter acknowledgement and verification.

## Review Gates

Use these gates before merge:

1. **Scope gate** — does the diff touch only the stated files?
2. **Semantic gate** — does it preserve proposal vs intent vs committed effect?
3. **Evidence gate** — are claims backed by tests, schemas, traces, or docs?
4. **Safety gate** — no secrets, no hidden chain-of-thought dependency, no
   widened authority.
5. **Taste gate** — does the change keep the project boring, inspectable, and
   practice-oriented?

## Public Language Standard

Use plain, auditable language:

- Say "the agent proposes" instead of "the agent does" until an adapter commits.
- Say "verified by" and name the evidence.
- Say "paused" or "rejected" as normal runtime outcomes, not failures to hide.
- Say "model-assisted" when a model materially shaped a contribution.
- Prefer examples before abstractions and interpreter behavior before syntax.

## What Good Contributions Look Like

Good:

- one denial-path test plus one doc sentence explaining the safety boundary;
- one schema field with a golden fixture and renderer/parser check;
- one adapter behavior with trace evidence and read-back verification;
- one small clarifying doc change that removes ambiguity around commit semantics.

Not good:

- a new orchestration framework layer;
- broad syntax proposals without executable semantics;
- large agent-generated rewrites without provenance or tests;
- claims of safety without evidence;
- hidden chain-of-thought formats or prompt transcripts as core runtime state.
