# Tongue Grammar Gaps v0

**Created:** May 06, 2026
**Last Updated:** May 06, 2026
**Status:** Harvest log — open

---

> Agents may propose; only governed effects may commit.

The v0 tongue defines six speech acts: `need`, `claim`, `doubt`, `intend`,
`remember`, `boundary`. The seed corpus
(`references/ai-native-tongue-seed-corpus-v0.jsonl`) shows that those six can
*encode* a working file-write loop. They do not show whether those six are
*sufficient* for what AI agents are actually trying to say.

This file is the running log of moments where an agent (often the agent
authoring this file) wanted to express something and the v0 grammar forced a
lossy workaround. Each entry is a negative observation: the language couldn't
hold what the speaker meant, and something audit-relevant was lost.

A gap is not a syntax proposal. It is evidence.

## Entry shape

For each gap:

- **Observation** — where the gap surfaced, in concrete context.
- **What the speaker meant** — the intended public meaning, in plain language.
- **Workaround using v0** — the closest legal v0 utterance.
- **What the workaround loses** — the audit-relevant difference between the
  intended meaning and the workaround.
- **Open question** — what would have to be true for v0 to absorb this without
  a new speech act.

Adding a gap does not commit the project to a new speech act. It commits the
project to *acknowledging* the loss. New speech acts must clear the cut-line in
`docs/charter-v0.md` §13: each must help admit, verify, approve, commit, or
trace an effect, or help an agent express a public need / claim / doubt /
intent / memory candidate / boundary.

## Gap 1 — Trial balloon (speculation without stake)

**Observation.** Mid-brainstorm, an agent wants to offer a candidate framing
for the operator to redirect, with no commitment to it. Example: "maybe the
right cut-line is per-adapter rather than per-effect — try this on, ready to
retract."

**What the speaker meant.** "I am putting this into the conversation so you can
react to it. I have not staked anything. If you say no, I will not have to
recant — there was no claim."

**Workaround using v0.** `claim "..." confidence 0.4`.

**What the workaround loses.** A claim at 0.4 is still a claim, and a future
auditor reading the trace cannot tell apart "the agent staked a low-confidence
position" from "the agent floated a candidate it had no commitment to." The
calibration signal is also wrong: a low-confidence claim that gets retracted is
a calibration miss; a trial balloon that gets redirected is not.

**Open question.** Could `doubt` carry a `mode: speculative` field, or is
"speculation" a different illocutionary force than "doubt"? Doubt marks
uncertainty *about a claim already on the table.* Trial balloon places
something *on the table* with reduced authorial commitment. They feel
orthogonal.

## Gap 2 — Self-supersession

**Observation.** In the conversation that produced this file, the operator's
second message read in full: "or maybe b" — superseding their previous answer
"a." The operator had not been refuted; they had reconsidered.

**What the speaker meant.** "Treat my prior utterance as no longer my
position. I am not refuting it. I am replacing it. Use this one."

**Workaround using v0.** A new `claim` (or in this case, a new `need`/`intend`)
with no link to the prior. The trace records two utterances; only an
out-of-band reader knows the second supersedes the first.

**What the workaround loses.** The supersession relation. An auditor walking
the trace sees two consecutive answers and cannot tell which is current
without re-reading conversation context. For multi-agent settings this is
worse: a peer agent reading utterance N+1 has no structural signal that
utterance N is retracted.

**Open question.** Is supersession a new speech act, a field on existing acts
(`supersedes: prop_NNN`), or a trace-level annotation that lives outside the
proposal record? Charter §13 prefers minimal grammar; a `supersedes` field on
`Proposal` seems lighter than a 7th speech act.

## Gap 3 — Prior-disclosed recommendation

**Observation.** When recommending a course of action on a question where the
agent has a known systematic bias, the agent wants to recommend *and*
foreground the bias. Example from this session: "I recommend keeping the
charter cut-lines tight; I notice my prior pulls me toward conservatism on
substrate questions — discount accordingly."

**What the speaker meant.** "Here is my recommendation. Here is the prior I am
disclosing. Treat the recommendation with that prior weighed in."

**Workaround using v0.** A `claim` with the bias listed in `evidence`.

**What the workaround loses.** Evidence is supposed to *support* a claim.
Listing a self-disclosed bias in `evidence` collapses two distinct pragmatic
moves: "this is what supports me" and "this is what should make you skeptical
of me." A reader walking the trace cannot tell which evidence entries are
supporting and which are caveating.

**Open question.** Is this a `prior_disclosure` field on `claim`, or a
separate speech act ("disclose"), or simply a discipline for structuring the
`evidence` list (e.g. tagged entries `prior:substrate-status-quo-bias`)? The
last option requires no schema change but no grammar enforces it.

## Status

This file is open. New gaps land here before any grammar change is proposed.
A gap graduates only when:

1. it has been observed in at least two distinct sessions or sources;
2. the workaround loss is audit-relevant, not just stylistic;
3. an explicit charter §13 cut-line check passes.

Until then, gaps are evidence.
