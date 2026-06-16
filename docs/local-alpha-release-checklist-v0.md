# Local Alpha Release Checklist v0

**Created:** June 16, 2026
**Last Updated:** June 16, 2026
**Status:** Draft

---

> **Agents may propose; only governed effects may commit.**

This checklist defines the current "local alpha" gate for the checked-in
Fermata runtime seed. It is intentionally narrower than hosted or service
readiness.

## Required Command

Install the package in editable mode:

```bash
python3 -m pip install -e '.[dev]'
```

Then run the validator:

```bash
python3 scripts/validate_local_alpha.py
```

Expected top-level result:

```json
{
  "status": "passed"
}
```

The installed console equivalent is:

```bash
fermata-local-alpha-validate
```

If the console command is not present after changing entry points, rerun the
editable install command.

## Gates Covered

The validator currently covers:

- Python compilation for `scripts` and `src`;
- canonical governed-effect schema JSON parse;
- golden fixture JSON parse;
- golden checks for parser, renderer, adapters, interpreter, CLI, surfaces, and
  trace ledger;
- installed `fermata` CLI smoke, proving `interpret` pauses without writing and
  `run` commits with adapter acknowledgement and verification;
- run-bundle contract fixtures for `file.write` and `memory.write` paused,
  rejected, and committed outcomes;
- package-level runtime API checks for `interpret` and `run`, including paused,
  rejected, and committed outcomes without shelling out;
- `git diff --check`.

## Release-Ready Conditions

Before presenting a local alpha:

- validator status is `passed`;
- CI has passed on the release commit;
- no generated CLI smoke outputs are staged;
- no secrets, credentials, tokens, passwords, or connection strings are present;
- examples remain local sandbox examples;
- docs still distinguish local CLI/runtime readiness from hosted or multi-user
  service readiness;
- changes preserve proposal, intent, approval, and committed-effect boundaries.

## Evidence To Include In Handoff

For `Tests/evidence`, include:

```bash
python3 scripts/validate_local_alpha.py
```

and the top-level JSON status. If the change discusses publication or tagging,
also include the passing CI run for the release commit.

## Still Not v1

Passing local alpha validation does not imply:

- hosted or multi-user service is implemented;
- remote adapters are safe;
- OS-level adapter process isolation is implemented;
- multi-user approval queues exist;
- trace records are cryptographically sealed;
- Fermata is a general-purpose programming language.

It means the checked-in local runtime, JSON records, CLI path, runtime API,
golden checks, and validation command are coherent enough for local alpha
review.
