# Fermata

**Created:** May 05, 2026
**Last Updated:** June 16, 2026
**Status:** v0.1.0 local alpha published; main has forward fixes

---

> **Agents may propose; only governed effects may commit.**

Fermata is a small governed-effect runtime seed for AI agents. It is not another
agent orchestration framework, and it is not YAML for workflows. It is the runtime
contract layer between agent proposals and committed external-world effects.

```text
orchestrators above
        ↓ propose
governed runtime in the middle
        ↓ admits / rejects / verifies / pauses / commits
committed effects below
```

The first boring proof is a governed file write: an agent proposes `file.write`,
the runtime checks scope and capability, pauses when approval is required, rejects
unsafe or malformed paths, commits only through the file adapter, and verifies by
reading back the resulting bytes and SHA-256 hash.

The second local proof is a governed memory write: an agent proposes
`memory.write`, the runtime checks capability, provenance, byte budget, and
approval gates, commits only by appending a scoped JSONL memory record, and
verifies by reading the record back by ID, version, and SHA-256 evidence.

## Current Release State

Fermata has a published local-alpha prerelease:

- GitHub Release: <https://github.com/cirwel/fermata/releases/tag/v0.1.0>
- Annotated tag: `v0.1.0`
- Tag target: `1934721f0ba4bd71bd8bc4daf82cba096ef65df4`
- Package version: `0.1.0`

The published tag is intentionally unchanged. Current `main` is ahead of that
tag with forward fixes for post-tag validation and installed golden-check
reference data. Install from current `main` or a later release when you need the
installed `fermata-golden-checks` command to run outside a source checkout.

## Why "Fermata"?

A fermata is a deliberate hold. The performer does not rush through the note; the
system waits at a meaningful boundary until the next action is warranted. This repo
uses that metaphor for AI effects: pause at the boundary, verify the conditions,
and only then commit.

## What Fermata is

- A runtime contract for governed external effects.
- A typed record shape for scopes, proposals, intents, effect outcomes, and traces.
- A testable boundary between model/orchestrator proposals and durable side effects.
- A place to practice effect admission, denial, pause, approval, commit, and audit.
- A readable account a non-coder steward can use to decide intent and impact:
  what was proposed, what the runtime verified, why it paused, who approved it,
  and what actually committed.

## What Fermata is not

- Not a hidden chain-of-thought transcript format.
- Not a general-purpose replacement for Python, Elixir, Rust, or TypeScript.
- Not an unrestricted autonomous action system.
- Not an agent framework competing with LangGraph, AutoGen, Hermes, Claude, or similar orchestrators.

Those systems may propose. Fermata decides whether proposed effects can become
committed effects.

## Current v0 artifacts

```text
CONTRIBUTING.md
AGENTS.md
MANIFEST.in
.github/PULL_REQUEST_TEMPLATE.md
docs/
  charter-v0.md
  runtime-contract-authoring-model.md
  katas-v0.md
  tongue-eval-rubric-v0.md
  ai-native-tongue-toolkit.md
  deployability-dossier-v0.md
  local-alpha-release-checklist-v0.md
  local-service-v0.md
  recovery-evidence-v0.md
  releases/
    local-alpha-v0.1.0.md
    local-alpha-v0.1.0-tag-checklist.md
  run-bundle-contract-v0.md
  runtime-api-v0.md
  ugly-trace-v0.md
references/
  governed-effect-ir-v0.schema.json
  ai-native-tongue-seed-corpus-v0.jsonl
  recovery-evidence-examples-v0/
  recovery-evidence-templates-v0/
  release-approvals-v0/
  release-candidates-v0/
  run-bundle-contract-fixtures-v0/
  tongue-golden-tests-v0.json
scripts/
  check_package_build.py
  check_local_service.py
  check_local_alpha_release_artifacts.py
  check_local_alpha_release_candidate.py
  check_local_alpha_release_candidate_record.py
  check_local_alpha_tag_approval_packet.py
  check_local_alpha_tag_publication_preflight.py
  check_run_bundle_contract.py
  check_recovery_evidence.py
  check_recovery_evidence_example.py
  check_runtime_api.py
  governed_effect_file_write_spike.py
  parse_tongue_line.py
  render_tongue_record.py
  run_cli_smoke.py
  run_tongue_golden_tests.py
  validate_local_alpha.py
examples/
  local-alpha/
    file-scope.json
    file-write-proposal.json
    file-write-approval.json
    run-bundle/
src/
  fermata/
    __init__.py
    cli.py
    file_adapter.py
    governed_effects.py
    interpreter.py
    local_alpha_validator.py
    memory_adapter.py
    policy_parser.py
    runtime_core.py
    runtime_ir.py
    self_tests.py
    service_records.py
    service.py
    reference_data/
      governed-effect-ir-v0.schema.json
      tongue-golden-tests-v0.json
      ai-native-tongue-seed-corpus-v0.jsonl
```

## Runtime state model

```text
Proposal
→ Intent
→ AdmissibleEffect
→ VerifiedEffect
→ ApprovedEffect
→ CommittedEffect
```

with first-class `Rejected` and `Paused` outcomes.

For the v0 local adapters, denial paths are part of the proof.

File-write denial paths:

- non-intent proposals are rejected before adapter work;
- malformed target, input, or content is rejected before adapter work;
- path escapes are rejected before adapter work;
- missing capability is rejected before adapter work;
- spoofed or mismatched operation capability is rejected before adapter work;
- directory targets are rejected before adapter work;
- adapter filesystem errors return governed rejection records;
- approval-required writes pause without touching the target.

Memory-write denial paths:

- malformed memory target, input, content, lifespan, or provenance is rejected before adapter work;
- empty, dot, traversal, reserved `.jsonl`, or out-of-scope memory targets are rejected before adapter work;
- missing `memory.write` capability is rejected before adapter work;
- spoofed or mismatched operation capability is rejected before adapter work;
- invalid provenance is rejected before adapter work;
- malformed existing memory ledgers are rejected before append;
- malformed existing memory ledger records are rejected before append;
- tampered existing memory record hashes are rejected before append;
- oversized serialized memory records are rejected before append;
- approval-required memory writes pause without touching the memory ledger.

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

For the v0 local memory-write adapter, committed means:

```text
JSONL memory record appended and fsynced under the scoped sandbox
+ record carries ID, version, provenance, actor, intent, trace, and content hash
+ runtime can read the record back by ID/version
+ trace records adapter acknowledgement and verification evidence
```

## Quickstart

The v0 runtime code uses only the Python standard library. The schema-validating
golden checks use the `dev` extra.

From a source checkout:

```bash
python3 -m pip install -e '.[dev]'
python3 -m json.tool references/governed-effect-ir-v0.schema.json >/tmp/fermata_schema.json
python3 -m json.tool references/tongue-golden-tests-v0.json >/tmp/fermata_golden.json
fermata-golden-checks
python3 scripts/check_runtime_api.py
python3 scripts/check_local_service.py
python3 scripts/check_recovery_evidence.py
python3 scripts/check_recovery_evidence_example.py
python3 scripts/check_local_alpha_release_artifacts.py
python3 scripts/check_local_alpha_release_candidate.py --allow-current-branch
python3 scripts/check_local_alpha_release_candidate_record.py
python3 scripts/check_local_alpha_tag_approval_packet.py
python3 scripts/check_local_alpha_tag_publication_preflight.py
python3 scripts/check_package_build.py
python3 scripts/validate_local_alpha.py
```

From current `main`, without keeping a checkout:

```bash
python3 -m pip install 'fermata-runtime[dev] @ git+https://github.com/cirwel/fermata.git@main'
fermata --help
fermata-golden-checks
```

The installed `fermata-golden-checks` command on current `main` falls back to
packaged reference data when no checkout-local `references/` tree is present.
The published `v0.1.0` tag predates that packaged-reference fix; its core
CLI/API install path works, but installed golden checks should be run from a
checkout or from current `main`.

Expected final status:

```json
{"status": "passed"}
```

The distance from the current runtime seed to a deployable local alpha is tracked
in [docs/deployability-dossier-v0.md](docs/deployability-dossier-v0.md).
The current local-alpha gate is documented in
[docs/local-alpha-release-checklist-v0.md](docs/local-alpha-release-checklist-v0.md).
Versioned local-alpha release notes and the tag checklist live in
[docs/releases/local-alpha-v0.1.0.md](docs/releases/local-alpha-v0.1.0.md) and
[docs/releases/local-alpha-v0.1.0-tag-checklist.md](docs/releases/local-alpha-v0.1.0-tag-checklist.md).
The pre-tag maintainer approval packet lives at
[references/release-approvals-v0/local-alpha-v0.1.0-tag-approval-packet.json](references/release-approvals-v0/local-alpha-v0.1.0-tag-approval-packet.json).

To see the local adapter evidence directly:

```bash
fermata-local-adapter-spike
```

## Try the local alpha CLI

`fermata interpret` runs the governed state machine without committing an
external-world effect. `fermata run` can commit, but only through the adapter
boundary and the supplied scope and approval records.

```bash
rm -rf /tmp/fermata-cli
fermata interpret \
  --scope examples/local-alpha/file-scope.json \
  --proposal examples/local-alpha/file-write-proposal.json \
  --sandbox-root /tmp/fermata-cli
fermata run \
  --scope examples/local-alpha/file-scope.json \
  --proposal examples/local-alpha/file-write-proposal.json \
  --approval examples/local-alpha/file-write-approval.json \
  --sandbox-root /tmp/fermata-cli
```

To run the same installed-command path as a repeatable smoke test:

```bash
python3 scripts/run_cli_smoke.py
```

To exercise the directory contract for external callers:

```bash
tmp="$(mktemp -d)"
cp -R examples/local-alpha/run-bundle "$tmp/run-bundle"
fermata bundle run "$tmp/run-bundle"
python3 scripts/check_run_bundle_contract.py
```

To call the local runtime from Python without shelling out:

```python
from fermata import interpret, run

paused = interpret(scope_record, proposal_record, sandbox_root="/tmp/fermata-api")
committed = run(
    scope_record,
    proposal_record,
    approval=approval_record,
    sandbox_root="/tmp/fermata-api",
)
```

The API contract is documented in
[docs/runtime-api-v0.md](docs/runtime-api-v0.md).

## Try the loopback local service

```bash
fermata service run \
  --host 127.0.0.1 \
  --port 8765 \
  --service-root /tmp/fermata-service
```

The service exposes `GET /health`, `POST /v0/interpret`, and `POST /v0/run`.
It binds only to loopback hosts, confines request sandbox roots under
`--service-root`, and appends request/response/trace/error records under
`--service-root/records/`.

To inspect those local records without hand-copying JSONL lines:

```bash
fermata service records --service-root /tmp/fermata-service
```

Run the subprocess smoke check with:

```bash
python3 scripts/check_local_service.py
```

The service contract is documented in
[docs/local-service-v0.md](docs/local-service-v0.md).

Recovery evidence templates for service incident and reconciliation review are
documented in [docs/recovery-evidence-v0.md](docs/recovery-evidence-v0.md) and
checked with:

```bash
python3 scripts/check_recovery_evidence.py
```

The script wrapper `python3 scripts/governed_effect_file_write_spike.py` is kept
for continuity with the first boring adapter.

## Try the public speech parser

```bash
fermata-parse-tongue 'boundary cannot commit effect:file.write reason:approval_missing offer:dry_run'
```

## Render seed corpus examples

```bash
fermata-render-tongue references/ai-native-tongue-seed-corpus-v0.jsonl --limit 6
```

## Contributing

Person and agent contributions are welcome when they preserve the core boundary:
proposal is not commit. Start with:

- [CONTRIBUTING.md](CONTRIBUTING.md) for person/agent/model contribution protocol.
- [AGENTS.md](AGENTS.md) for coding-agent operating rules.
- [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) for review gates.

Prefer small, boring patches with evidence. Keep syntax experiments subordinate to
the runtime contract.

## Near-term roadmap

Public milestone: [v0.1 — governed-effect language seed](https://github.com/cirwel/fermata/milestone/1)

The next milestone keeps the language narrow: strengthen the commit boundary,
add one more governed adapter, make the shared IR surfaces explicit, and expand
examples only where they improve executable traces.

1. [Harden the file adapter against adversarial filesystem races](https://github.com/cirwel/fermata/issues/1).
2. [Add a second adapter with the same proposal/intent/pause/reject/commit trace](https://github.com/cirwel/fermata/issues/2) — landed as local `memory.write`.
3. [Split authority policy surface from agent utterance surface over the same IR](https://github.com/cirwel/fermata/issues/3).
4. [Make the interpreter loop explicit over the shared IR](https://github.com/cirwel/fermata/issues/4).
5. [Expand golden traces into reusable katas for downstream runtimes](https://github.com/cirwel/fermata/issues/5).
6. [Compare Fermata against adjacent AI language and runtime ecosystems](https://github.com/cirwel/fermata/issues/6).
