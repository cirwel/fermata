# Tongue Evaluation Rubric v0

**Created:** May 05, 2026
**Last Updated:** May 06, 2026
**Status:** Draft

---

## Purpose

Evaluate whether the governed-effect tongue is useful as a public agent language, not whether the syntax is pretty.

The language should be:

- parseable into typed records;
- readable by a human in Discord;
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
   - approval-required write pauses before commit.

Run them with:

```bash
python3 -m pip install -e '.[dev]'
python3 scripts/run_tongue_golden_tests.py
```

## Machine Checks

### Parser

Passes if:

- each supported utterance returns a `record_type: proposal` object;
- `speech_act` is one of the six v0 acts;
- payload fields preserve the public meaning;
- unsupported effect intents are not parsed by the tiny speech parser.

### Renderer

Passes if:

- output is one or two short human-readable sentences;
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

## Human Taste Rubric

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
