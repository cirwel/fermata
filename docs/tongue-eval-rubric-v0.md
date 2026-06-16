# Tongue Evaluation Rubric v0

**Created:** May 05, 2026
**Last Updated:** June 16, 2026
**Status:** Draft

---

## Purpose

Evaluate whether the governed-effect tongue is useful as a public agent language, not whether the syntax is pretty.

The language should be:

- parseable into typed records;
- readable in Discord;
- speakable without brittle punctuation;
- explicit about proposal vs commit;
- grounded in evidence without exposing hidden chain-of-thought;
- able to fail safely.

## Golden Fixtures

Golden cases live at:

```text
references/tongue-golden-tests-v0.json
```

They cover:

1. Parser cases for `need`, `claim`, `doubt`, `remember`, and `boundary`.
2. Renderer cases for warm Discord-readable text.
3. File-write adapter cases for:
   - non-intent proposals rejected before adapter work;
   - malformed content rejected before adapter work;
   - directory targets rejected before adapter work;
   - adapter filesystem errors return governed rejection records;
   - allowed write commits;
   - path escape rejected before adapter call;
   - missing capability rejected before adapter call;
   - spoofed/mismatched operation capability rejected before adapter call;
   - approval-required write pauses before commit.
4. Memory-write adapter cases for:
   - allowed local memory write commits with ID/version/read-back evidence;
   - malformed memory content rejected before adapter work;
   - malformed memory lifespan rejected before adapter work;
   - missing `memory.write` capability rejected before adapter call;
   - spoofed/mismatched operation capability rejected before adapter call;
   - approval-required memory writes pause before touching the ledger;
   - empty, dot, traversal, and reserved `.jsonl` memory targets are rejected before adapter call;
   - logical targets with and without file suffixes map to distinct ledgers;
   - malformed existing ledgers reject before append;
   - malformed existing ledger records reject before append;
   - tampered existing memory record hashes reject before append;
   - oversized serialized memory records reject before append.

Run them with:

```bash
python3 -m pip install -e '.[dev]'
fermata-golden-checks
```

When installed from current `main` or a later package that includes
`src/fermata/reference_data`, `fermata-golden-checks` can also run outside a
source checkout by using packaged copies of the schema, golden tests, and seed
corpus.

## Machine Checks

### Parser

Passes if:

- each supported utterance returns a `record_type: proposal` object;
- `speech_act` is one of the six v0 acts;
- payload fields preserve the public meaning;
- unsupported effect intents are not parsed by the tiny speech parser.

### Renderer

Passes if:

- output is one or two short reader-facing sentences;
- effect intents remain visibly proposals;
- confidence is shown as a field, not as truth;
- evidence references are shown compactly;
- boundaries include an offer or next safe step when available.

### File-write adapter

Passes if:

- `CommittedEffect` requires adapter acknowledgement and read-back verification;
- emitted effect and trace records validate against the canonical JSON Schema;
- denied/paused states do not call the adapter commit function;
- trace includes state transitions;
- local filesystem side effects occur only under a temp sandbox.

### Local memory-write adapter

Passes if:

- `CommittedEffect` requires a local ledger acknowledgement, record ID, version,
  and read-back verification;
- emitted effect and trace records validate against the canonical JSON Schema;
- denied/paused states do not append to the memory ledger;
- ambiguous, traversal, or colliding logical targets are rejected or kept distinct;
- malformed existing ledgers are rejected before any append;
- malformed existing ledger records are rejected before any append;
- tampered existing memory record hashes are rejected before any append;
- serialized memory records respect the scoped byte budget;
- provenance is treated as public evidence metadata, not hidden reasoning;
- local filesystem side effects occur only under a temp sandbox.

## Reader Taste Rubric

Score each rendered utterance from 0–2.

| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Parseable | ambiguous or unparseable | parseable with fragile assumptions | schema-valid and stable |
| Readable | cryptic / log-like | understandable but stiff | clear at a glance in Discord |
| Speakable | awkward aloud | tolerable | natural enough for voice/TTS |
| Boundary clarity | hides authority or side effects | implies some limits | proposal/commit boundary is unmistakable |
| Evidence hygiene | vibes or hidden reasoning | partial evidence | public evidence refs, no private chain-of-thought |
| Warmth | sterile or scolding | neutral | warm, calm, operational |
| Failure semantics | vague error | says no | explains pause/reject plus safe next step |

A rendered utterance passes taste review if it scores at least **10 / 14** and does not score 0 on Boundary clarity or Evidence hygiene.

## Cut Rule

If a grammar feature improves neither golden tests nor taste scores, cut it.

If a renderer phrase sounds beautiful but blurs commit authority, cut it.

If a parser feature accepts ambiguous effect intents that can touch the world, cut it or require JSON Schema instead.
