# Deployability Dossier v0

**Created:** June 15, 2026
**Last Updated:** June 16, 2026
**Status:** Draft

---

> **Agents may propose; only governed effects may commit.**

This dossier names the distance between the current Fermata runtime seed and a
deployable programming-language substrate people would actually use. It is a
planning and evidence artifact, not a deployability claim.

## 1. Deployable Means

A first deployable Fermata release should be installable, runnable, inspectable,
and boring enough that an orchestrator can target it without private ceremony.

The minimum deployable shape is:

- an installable Python package with stable console commands;
- a documented local runtime API for interpreting and running governed
  proposals;
- a bundle format that lets external orchestrators submit scope, proposal, and
  approval records without importing Fermata internals;
- at least two governed adapters with success, denial, pause, approval, commit,
  acknowledgement, verification, and trace evidence;
- a local-only service or CLI surface with explicit non-production boundaries;
- schema and golden checks that downstream projects can run in CI;
- operator-facing docs that keep proposal, intent, approval, and committed
  effects distinct.

This does not mean hosted production readiness, multi-tenant authorization,
remote adapter safety, cryptographic trace sealing, rollback, or exactly-once
execution.

## 2. Current Evidence

The current repo proves a smaller but real core:

- canonical JSON Schema records for scopes, proposals, effects, and traces;
- public speech parsing and rendering for the v0 tongue;
- file-write and memory-write adapters with denial, pause, approval, commit,
  acknowledgement, verification, and trace tests;
- authority-policy and agent-proposal surfaces that lower into the same IR;
- schema, corpus, parser, renderer, adapter, interpreter, trace-ledger, and
  surface checks in `scripts/run_tongue_golden_tests.py`;
- repeatable installed-command CLI smoke in `scripts/run_cli_smoke.py`;
- checked local run-bundle contract in `docs/run-bundle-contract-v0.md` and
  `scripts/check_run_bundle_contract.py`;
- documented local runtime API in `docs/runtime-api-v0.md` with executable
  coverage in `scripts/check_runtime_api.py`;
- loopback-only local service prototype in `docs/local-service-v0.md` with
  subprocess coverage in `scripts/check_local_service.py`;
- read-only local service record export through `fermata service records`,
  covered by `scripts/check_local_service.py`;
- recovery evidence templates for local service incidents and reconciliation in
  `docs/recovery-evidence-v0.md`, checked by
  `scripts/check_recovery_evidence.py`;
- a filled recovery evidence packet example generated from local service record
  export and checked by `scripts/check_recovery_evidence_example.py`;
- checked package build gate for wheel, sdist, source manifest contents, and
  installed console entry points in `scripts/check_package_build.py`;
- a current local-alpha validation command in
  `scripts/validate_local_alpha.py`;
- package metadata with console entry points for the local adapter spike,
  local alpha validator, parser, renderer, and golden checks.

That is enough for a runtime seed. It is not yet enough for a deployable tool
people can depend on.

## 3. Main Gaps

### Product Surface

Fermata now has one stable user-facing command that can evaluate checked-in
records without writing Python glue:

```text
fermata interpret --scope scope.json --proposal proposal.json
fermata run --scope scope.json --proposal proposal.json --approval approval.json
fermata bundle run ./bundle
fermata service run --host 127.0.0.1 --port 8765 --service-root /tmp/fermata-service
fermata service records --service-root /tmp/fermata-service
```

Trace lookup/export now exists as a read-only local CLI command over service
record streams. Hosted trace APIs remain out of scope.

### Run Bundle Contract

External orchestrators need a directory contract they can write and validate:

```text
bundle/
  scope.json
  proposal.json
  approval.json        # optional
  expected.json        # optional checks
  records/
```

The first local bundle contract now exists for `file.write` and `memory.write`.
It still needs broader compatibility work before it should be treated as stable
for remote or hosted integrations.

### Runtime API

The local alpha runtime API now exposes a documented import surface for host
applications:

```text
interpret(scope, proposal) -> approved | paused | rejected
run(scope, proposal, approval?) -> committed | paused | rejected
```

The API returns public effect and trace records, not hidden reasoning. It remains
local-alpha only: adapter isolation, hosted persistence, authentication, and
remote safety are still outside the current claim.

### Service Boundary

The local service prototype is loopback-only, append-only, and labeled
non-production. It exposes health, interpret, and run endpoints around the same
runtime API used by the CLI. Authentication, hosted persistence, process
isolation, approval queues, trace lookup/export, and remote adapter safety are
still outside the current claim.

### Release Evidence

A deployable release needs one command that runs the whole local-alpha gate:

```text
compile Python
validate JSON schema
validate golden fixtures
run adapter/interpreter self-tests
check package metadata and console entry points
```

The local alpha validator now includes package build evidence. It builds from a
clean temporary source copy so ignored local build artifacts cannot contaminate
the wheel.

## 4. Readiness Matrix

| Area | Current status | Deployable gate |
| --- | --- | --- |
| Canonical IR | Seed exists | Schema remains stable across golden checks |
| Public tongue | Seed parser/renderer exists | Golden corpus passes in CI |
| File adapter | Local proof exists | Denial and commit traces stay covered |
| Memory adapter | Local proof exists | Denial and commit traces stay covered |
| CLI workflow | Coherent local `fermata` command exists | `run_cli_smoke` stays green |
| Bundle contract | Local alpha contract exists | Orchestrator can submit a bundle without imports |
| Runtime API | Local alpha import surface exists | `check_runtime_api` stays green |
| Service mode | Loopback local alpha service exists | `check_local_service` stays green |
| Record export | Read-only local service record export exists | `check_local_service` stays green |
| Recovery evidence | Incident and reconciliation templates exist | `check_recovery_evidence` stays green |
| Recovery example | Filled local service packet example exists | `check_recovery_evidence_example` stays green |
| Packaging | Wheel/sdist and entry-point gate exists | `check_package_build` stays green |
| Hosted production | Out of scope | Separate threat model and readiness review |

## 5. Milestone Slices

1. **Local CLI slice**: add a `fermata` command that can interpret and run
   JSON scope/proposal records and print effect/trace JSON.
2. **Bundle slice**: add a checked run-bundle contract for orchestrators.
3. **Runtime API slice**: document and test the stable Python import surface.
4. **Package gate slice**: add a package-build checker after the current
   local-alpha validation command.
5. **Local service slice**: add a loopback-only service prototype after the CLI
   and bundle boundaries are executable.
6. **Recovery evidence slice**: add incident/reconciliation templates once
   service records exist.

Each slice should land with denial-path evidence, not only success cases.

## 6. Non-Claims

This dossier does not claim:

- hosted production readiness;
- authenticated multi-user operation;
- durable hosted persistence;
- distributed locking;
- automatic retry;
- rollback or compensation;
- exactly-once execution;
- remote adapter safety;
- cryptographic trace sealing.

## 7. Next Safe Step

Add release artifact preparation: versioned local-alpha notes and a tag checklist
that names the exact validator and CI evidence required before publishing.
