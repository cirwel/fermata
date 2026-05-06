# Fermata

**Created:** May 05, 2026
**Last Updated:** May 06, 2026
**Status:** v0 governed-effect runtime seed

---

> **Agents may propose; only governed effects may commit.**

Fermata is a governed-effect runtime seed for AI agents. It is not another agent
orchestration framework, and it is not YAML for workflows. It is the runtime
contract layer between agent proposals and committed external-world effects.

```text
orchestrators above
        ↓ propose
governed runtime in the middle
        ↓ admits / rejects / verifies / pauses / commits
committed effects below
```

The first boring case is a governed file write: an agent proposes `file.write`,
the runtime checks scope and capability, pauses when approval is required, commits
only through the file adapter, and verifies by reading back the resulting bytes and
SHA-256 hash.

## Why "Fermata"?

A fermata is a deliberate hold. The performer does not rush through the note; the
system waits at a meaningful boundary until the next action is warranted. This repo
uses that metaphor for AI effects: pause at the boundary, verify the conditions,
and only then commit.

## Current v0 artifacts

```text
docs/
  charter-v0.md
  runtime-contract-authoring-model.md
  katas-v0.md
  tongue-eval-rubric-v0.md
  ai-native-tongue-toolkit.md
references/
  governed-effect-ir-v0.schema.json
  ai-native-tongue-seed-corpus-v0.jsonl
  tongue-golden-tests-v0.json
scripts/
  governed_effect_file_write_spike.py
  parse_tongue_line.py
  render_tongue_record.py
  run_tongue_golden_tests.py
src/
  fermata/
    __init__.py
    governed_effects.py
```

## State model

```text
Proposal
→ Intent
→ AdmissibleEffect
→ VerifiedEffect
→ ApprovedEffect
→ CommittedEffect
```

with first-class `Rejected` and `Paused` outcomes.

## Definition of committed

An effect is committed only after the governed runtime invokes the concrete effect
adapter and obtains an adapter-specific durable acknowledgement that the external
target state has changed or accepted the change.

For the v0 file-write adapter, committed means:

```text
bytes written
+ file closed/flushed
+ runtime can read back/stat/hash expected result
+ trace records actor, scope, adapter, target, ack/evidence
```

## Run the checks

The v0 runtime code uses only the Python standard library. The schema-validating
golden checks use the `dev` extra.

```bash
python3 -m pip install -e '.[dev]'
python3 -m json.tool references/governed-effect-ir-v0.schema.json >/tmp/fermata_schema.json
python3 -m json.tool references/tongue-golden-tests-v0.json >/tmp/fermata_golden.json
python3 scripts/run_tongue_golden_tests.py
```

Expected final status:

```json
{"status": "passed"}
```

## Try the public speech parser

```bash
python3 scripts/parse_tongue_line.py   'boundary cannot commit effect:file.write reason:approval_missing offer:dry_run'
```

## Render seed corpus examples

```bash
python3 scripts/render_tongue_record.py references/ai-native-tongue-seed-corpus-v0.jsonl --limit 6
```

## Non-goals

- Not a hidden chain-of-thought transcript format.
- Not a general-purpose replacement for Python, Elixir, Rust, or TypeScript.
- Not an unrestricted autonomous action system.
- Not an agent framework competing with LangGraph, AutoGen, Hermes, Claude, or similar orchestrators.

Those systems may propose. Fermata decides whether proposed effects can become
committed effects.
