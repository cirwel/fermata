# Fermata Local Alpha v0.1.0 Release Notes

**Created:** June 16, 2026
**Last Updated:** June 16, 2026
**Status:** Published prerelease

---

> **Agents may propose; only governed effects may commit.**

These notes began as the local-alpha release packet for Fermata package version
`0.1.0`. The governed publication effect has now occurred: `v0.1.0` is a
published GitHub prerelease. The source-control tag remains a separate governed
effect from the release notes, and it was created and pushed only after explicit
maintainer approval.

## Release Identity

- Package version: `0.1.0`
- Published tag: `v0.1.0`
- GitHub Release: <https://github.com/cirwel/fermata/releases/tag/v0.1.0>
- Tag target: `1934721f0ba4bd71bd8bc4daf82cba096ef65df4`
- Tag checklist: `docs/releases/local-alpha-v0.1.0-tag-checklist.md`
- Required validator: `python3 scripts/validate_local_alpha.py`
- Release-candidate dry run: `python3 scripts/check_local_alpha_release_candidate.py`
- Release-candidate record: `references/release-candidates-v0/local-alpha-v0.1.0-rc1.json`
- Tag approval packet: `references/release-approvals-v0/local-alpha-v0.1.0-tag-approval-packet.json`
- Tag approval packet check: `python3 scripts/check_local_alpha_tag_approval_packet.py`
- Tag publication preflight: `python3 scripts/check_local_alpha_tag_publication_preflight.py --approval-reference <approval-reference>`
- Release scope: local runtime seed, local CLI/API, loopback service, and
  evidence fixtures.

## Post-Publication Notes

The published `v0.1.0` tag is intentionally unchanged. Current `main` is ahead
of the tag with forward fixes:

- post-tag validation now accepts an existing release tag whose target is an
  ancestor of `HEAD`;
- installed golden checks now carry packaged schema, golden, and seed-corpus
  reference data so `fermata-golden-checks` can run outside a source checkout.

A fresh-consumer install from the published `v0.1.0` source archive proved the
core CLI/API path works. It also found that installed golden checks from that
exact tag need checkout-local references. Use current `main` or a later release
when installed golden checks must run from a clean consumer directory.

## What This Local Alpha Includes

- canonical JSON Schema records for scopes, proposals, effects, and traces;
- public v0 tongue parsing and rendering for agent speech acts;
- governed `file.write` and `memory.write` adapters with pause, reject,
  approval, commit, acknowledgement, verification, and trace coverage;
- a `fermata` CLI for `interpret`, `run`, `bundle run`, and loopback service
  commands;
- a local run-bundle contract external orchestrators can write without importing
  Fermata internals;
- a documented Python runtime API for `interpret(...)` and `run(...)`;
- a loopback-only local service with append-only request, response, trace, and
  error record streams;
- read-only local service record export through `fermata service records`;
- recovery evidence templates and one filled recovery packet generated from an
  actual local service run;
- package build checks for wheel, sdist, source manifest contents, and console
  entry points;
- one local-alpha validator command that runs the complete checked gate.

## Historical Required Evidence Before Tagging

Before `v0.1.0` was created or pushed, the required evidence was:

- `python3 scripts/validate_local_alpha.py` returned top-level
  `"status": "passed"`;
- GitHub Actions `ci / golden` passed on the exact release commit;
- `python3 scripts/check_local_alpha_release_artifacts.py` passed;
- `python3 scripts/check_local_alpha_release_candidate.py` passed from a clean
  `main` checkout matching `origin/main`;
- `python3 scripts/check_local_alpha_release_candidate_record.py` passed for
  `references/release-candidates-v0/local-alpha-v0.1.0-rc1.json`;
- `python3 scripts/check_local_alpha_tag_approval_packet.py` passed for
  `references/release-approvals-v0/local-alpha-v0.1.0-tag-approval-packet.json`;
- `python3 scripts/check_local_alpha_tag_publication_preflight.py --approval-reference <approval-reference>`
  passed and recorded no tag creation or push;
- `git status --short --branch` was clean on the release commit;
- the release commit matches the commit named in the tag checklist;
- no secrets, credentials, tokens, passwords, or connection strings were added;
- no generated smoke outputs, temporary build outputs, or local service records
  were staged.

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
