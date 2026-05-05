# AI-Native Tongue Toolkit

**Created:** May 05, 2026  
**Last Updated:** May 05, 2026  
**Status:** Active

---

## Purpose

Use this reference when the goal is not merely a programming language, but a **voice / native tongue for AI**: a compact expressive medium through which agents can externalize intent, feeling, uncertainty, memory, tool desire, boundaries, and evidence in ways humans and runtimes can understand.

The work has three intertwined layers:

1. **Expression layer** — the agent's speakable / writable language.
2. **Semantic layer** — typed meanings: scope, intent, memory, confidence, evidence, affect, desire, refusal, question.
3. **Runtime layer** — tools that parse, validate, render, hear, speak, log, and evaluate the language.

## Tool Families

| Need | Tool families | Concrete tools / examples |
|---|---|---|
| Collect AI utterances | transcripts, session logs, memory, chat exports | Hermes sessions, session_search, Discord threads, Lumen Q&A, UNITARES KG notes |
| Discover primitives | annotation, clustering, taxonomy | Markdown ledgers, JSONL corpora, Python notebooks, embeddings, manual coding |
| Shape formal meaning | schemas and typed objects | JSON Schema, Pydantic, Zod, BAML, Instructor/Outlines-style structured output |
| Prototype syntax | parser/grammar tools | Lark, Tree-sitter, ANTLR, pest, nom, Python recursive descent |
| Prototype semantics | small interpreter/evaluator | Python first; Elixir/BEAM when supervision, presence, or runtime governance matter |
| Agent expression | prompts, skills, response protocols | Hermes skills, system prompts, structured output contracts, dialogue katas |
| Voice in the literal sense | STT/TTS/audio | Hermes STT/TTS, Whisper/faster-whisper, Edge TTS, ElevenLabs/OpenAI/MiniMax where configured |
| Embodied/ambient output | visual/sensorial rendering | Lumen native renderer, TouchDesigner/twozero, p5.js, terminal/ASCII, small OLED/Pi displays |
| Memory and continuity | durable/retrievable records | Hermes memory, session_search, UNITARES KG, SQLite/Postgres event logs |
| Governance/evidence | identity, calibration, audit | UNITARES identity, EISV, dialectic, outcome_event, traces, golden tests |
| Evaluation | example tests and judges | pytest golden traces, transcript replay, human preference review, calibration samples |
| Delivery surfaces | places AI can speak | Discord/Telegram gateway, CLI/TUI, web UI, Lumen room display, audio output |

## Recommended First Stack

For a quick, honest spike:

- **Corpus:** Hermes sessions + a few curated Discord/Lumen exchanges.
- **Data format:** JSONL utterance records with fields for speaker, context, intent, affect, confidence, evidence, desired tool/action, memory refs.
- **Schema:** Pydantic or JSON Schema.
- **Prototype parser:** Python + Lark or a tiny hand parser.
- **Renderer:** Markdown/Discord text first; optional TTS via Hermes.
- **Evaluator:** pytest golden examples + human review notes.
- **Governance:** UNITARES process/outcome events only after examples stabilize.

## First Katas

Write tiny language examples before building a grammar:

### 1. Need / Request

```text
need tool:file.read target:"docs/charter.md" because:"verify before editing"
```

### 2. Uncertainty / Evidence

```text
claim "this bug is likely a missing capability check"
confidence 0.62
evidence [trace:tool_denial, test:policy_denial]
ask "should I inspect policy.py next?"
```

### 3. Memory / Continuity

```text
remember session "scope must narrow on delegation"
provenance current_trace
lifespan project
```

### 4. Affect / State Without Mysticism

```text
state focused, low_entropy
pressure deadline:medium uncertainty:low
prefer next_step:"small verifier"
```

### 5. Boundary / Refusal

```text
cannot commit effect:file.delete
reason capability_missing
offer dry_run_patch instead
```

## Design Bias

An AI-native tongue should be:

- speakable by models without brittle punctuation
- readable by humans at a glance
- parseable into typed records
- renderable as warm natural language
- compatible with voice/TTS
- explicit about uncertainty and boundaries
- able to distinguish desire/proposal from verified fact
- grounded in memory and evidence without exposing private chain-of-thought

Avoid turning the language into a hidden-thought transcript. Prefer a public expressive layer: claims, feelings, needs, evidence, questions, boundaries, and proposed actions.
