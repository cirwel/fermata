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

The versioned local-alpha release packet for package version `0.1.0` lives at:

- `docs/releases/local-alpha-v0.1.0.md`
- `docs/releases/local-alpha-v0.1.0-tag-checklist.md`

Check those release artifacts with:

```bash
python3 scripts/check_local_alpha_release_artifacts.py
```

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
- loopback local service checks for health, interpret, run, service-root
  confinement, non-loopback bind rejection, append-only records, and read-only
  record export;
- recovery evidence template checks for service incident and reconciliation
  reports, including stream names, wrapper record types, and sample
  classifications;
- recovery evidence example checks that validate a checked packet and generate
  a fresh packet from an actual loopback local service run;
- release artifact checks that keep the versioned local-alpha notes and tag
  checklist aligned with package metadata and validator gates;
- package build checks for wheel, sdist, source manifest contents, and installed
  console entry points;
- `git diff --check`.

## Release-Ready Conditions

Before presenting a local alpha:

- validator status is `passed`;
- CI has passed on the release commit;
- no generated CLI smoke outputs are staged;
- no secrets, credentials, tokens, passwords, or connection strings are present;
- examples remain local sandbox examples;
- service runs only on loopback hosts and remains labeled non-production;
- service record export remains read-only and local to `--service-root`;
- recovery evidence templates remain evidence packets, not automatic retry,
  rollback, approval, or production incident response;
- versioned release notes and tag checklist name the same package version, tag,
  validator command, CI evidence, and non-claims;
- wheel and sdist artifacts are built from a clean temporary source copy, not an
  ignored local `build/` directory;
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
- approval queues, trace lookup/export, or service authentication are
  implemented;
- remote adapters are safe;
- OS-level adapter process isolation is implemented;
- multi-user approval queues exist;
- trace records are cryptographically sealed;
- recovery templates automatically reconcile or repair service records;
- Fermata is a general-purpose programming language.

It means the checked-in local runtime, JSON records, CLI path, runtime API,
golden checks, and validation command are coherent enough for local alpha
review.
