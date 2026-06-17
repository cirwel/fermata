# Fermata Local Alpha v0.1.1 Release Notes

**Created:** June 17, 2026
**Last Updated:** June 17, 2026
**Status:** Release candidate

---

> **Agents may propose; only governed effects may commit.**

These notes are the local-alpha release packet for Fermata package version
`0.1.1`. This is a **release candidate**: no source-control tag has been
created or pushed, and these notes are not maintainer approval. The tag is a
separate governed effect that must wait for explicit approval.

`v0.1.1` is a patch release. It folds the forward fixes already on `main` since
`v0.1.0` into a coherent, installable package and makes the release-evidence
machinery version-aware.

## Release Identity

- Package version: `0.1.1`
- Intended tag: `v0.1.1`
- Predecessor: `v0.1.0` (<https://github.com/cirwel/fermata/releases/tag/v0.1.0>)
- Required validator: `python3 scripts/validate_local_alpha.py`
- Release-candidate dry run: `python3 scripts/check_local_alpha_release_candidate.py`
- Release-candidate record: `references/release-candidates-v0/local-alpha-v0.1.1-rc1.json`
- Tag approval packet: `references/release-approvals-v0/local-alpha-v0.1.1-tag-approval-packet.json`
- Tag approval packet check: `python3 scripts/check_local_alpha_tag_approval_packet.py`
- Tag publication preflight: `python3 scripts/check_local_alpha_tag_publication_preflight.py --approval-reference <approval-reference>`
- Release scope: local runtime seed, local CLI/API, loopback service, governed
  `file.write` / `memory.write` / `network.fetch` adapters, and evidence
  fixtures.

## What Changed Since v0.1.0

`v0.1.1` packages the post-tag forward fixes that already landed on `main` and
hardens the release process itself:

- post-tag validation accepts an existing release tag whose target is an
  ancestor of `HEAD`;
- installed golden checks carry packaged schema, golden, and seed-corpus
  reference data so `fermata-golden-checks` runs outside a source checkout;
- the governed `network.fetch` adapter (third effect) ships under scope;
- idempotent commits give at-most-once governed effects per
  `(scope, idempotency_key)`;
- the release-evidence checkers are now **version-aware**: they read the package
  version from `pyproject.toml` and derive every artifact path, tag name, and
  required fragment from it, instead of pinning `0.1.0`;
- the release-candidate record supports a documented pre-merge `pending_ci`
  state, so a version bump stays honestly green in CI: the candidate record
  claims no commit or CI evidence it cannot yet have, and names the exact
  requirements to fill before it becomes a `pre_tag_candidate`.

## Candidate State

This packet is a release candidate. Status of the remaining gates:

- the version bump merged to `main` in PR #45 as commit
  `71ec78ca39291dd7cc4a923703ba880cb668cbb4` with green `ci / golden`;
- the release-candidate record at
  `references/release-candidates-v0/local-alpha-v0.1.1-rc1.json` is upgraded to
  `pre_tag_candidate` with the merged commit, two green `ci / golden` run URLs,
  and a strict release-candidate dry-run snapshot;
- the maintainer tag approval packet remains `not_granted`: explicit maintainer
  approval is still required before the `v0.1.1` tag is created or pushed.

## What This Local Alpha Includes

- canonical JSON Schema records for scopes, proposals, effects, and traces;
- public v0 tongue parsing and rendering for agent speech acts;
- governed `file.write`, `memory.write`, and `network.fetch` adapters with
  pause, reject, approval, commit, acknowledgement, verification, and trace
  coverage;
- at-most-once governed effects per `(scope, idempotency_key)`;
- a `fermata` CLI for `interpret`, `run`, `bundle run`, and loopback service
  commands;
- a local run-bundle contract external orchestrators can write without importing
  Fermata internals;
- a documented Python runtime API for `interpret(...)` and `run(...)`;
- a loopback-only local service with append-only request, response, trace, and
  error record streams, plus read-only record export;
- recovery evidence templates and one filled recovery packet;
- package build checks for wheel, sdist, source manifest contents, packaged
  reference data, and console entry points;
- one local-alpha validator command that runs the complete checked gate.

## Required Evidence Before Tagging

Before `v0.1.1` is created or pushed, the required evidence is:

- `python3 scripts/validate_local_alpha.py` returns top-level
  `"status": "passed"`;
- GitHub Actions `ci / golden` passed on the exact release commit;
- `python3 scripts/check_local_alpha_release_artifacts.py` passes;
- `python3 scripts/check_local_alpha_release_candidate.py` passes from a clean
  `main` checkout matching `origin/main`;
- `python3 scripts/check_local_alpha_release_candidate_record.py` passes for a
  `pre_tag_candidate` record (no longer `pending_ci`);
- `python3 scripts/check_local_alpha_tag_approval_packet.py` passes;
- `python3 scripts/check_local_alpha_tag_publication_preflight.py --approval-reference <approval-reference>`
  passes and records no tag creation or push;
- `git status --short --branch` is clean on the release commit;
- no secrets, credentials, tokens, passwords, or connection strings were added.

## Validator Gate Names

The required validator currently reports these gate IDs:

- `compileall`
- `schema_json`
- `golden_json`
- `golden_checks`
- `cli_smoke`
- `run_bundle_contract`
- `approval_surface`
- `runtime_api`
- `local_service`
- `recovery_evidence`
- `recovery_evidence_example`
- `release_artifacts`
- `release_candidate_record`
- `tag_approval_packet`
- `tag_publication_preflight`
- `package_build`
- `diff_check`

## Non-Claims

This local alpha does not claim:

- hosted production readiness;
- authenticated multi-user operation;
- durable hosted persistence;
- approval queues;
- remote adapter safety;
- OS-level adapter process isolation;
- cryptographic trace sealing;
- rollback, compensation, automatic retry, or exactly-once execution;
- that Fermata is a general-purpose programming language.

The claim is narrower: the checked-in local runtime seed is installable,
runnable, inspectable, packageable, and validated enough for local-alpha review
without blurring proposal, intent, approval, and committed-effect boundaries.
