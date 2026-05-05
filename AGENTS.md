# Agent Instructions for Fermata

**Created:** May 05, 2026  
**Last Updated:** May 05, 2026  
**Status:** Active

---

> **Agents may propose; only governed effects may commit.**

These instructions apply to AI coding agents and model-assisted workflows in this
repo.

## Required Context Before Editing

Read these files before making non-trivial changes:

1. `README.md`
2. `CONTRIBUTING.md`
3. `docs/charter-v0.md`
4. `docs/runtime-contract-authoring-model.md`
5. `docs/tongue-eval-rubric-v0.md`

## Operating Rules

- Preserve the distinction between proposal, intent, approval, and committed
  external-world effect.
- Do not design around hidden chain-of-thought. Use structured rationale,
  assumptions, evidence, doubts, and decision records.
- Do not widen scope silently. Touch only the files required by the task.
- Do not commit secrets, credentials, tokens, passwords, or connection strings.
  Redact accidental exposure as `[REDACTED]`.
- Do not stage unrelated WIP. Inspect `git status --short --branch` before and
  after edits, and stage only intended paths.
- Prefer small verified changes over large clever rewrites.
- For runtime changes, include denial-path evidence, not only success cases.

## Validation Commands

Run these before reporting a change as ready when they are relevant:

```bash
python3 -m compileall scripts src
python3 -m json.tool references/governed-effect-ir-v0.schema.json >/tmp/fermata_schema.json
python3 -m json.tool references/tongue-golden-tests-v0.json >/tmp/fermata_golden.json
python3 scripts/run_tongue_golden_tests.py
```

## Agent Handoff Summary

When handing off, include:

```text
Task:
Files touched:
Scope boundaries:
Tests/evidence:
Unrelated WIP left untouched:
Open doubts:
Next safe step:
```
