# Tongue Grammar Gaps v0

**Created:** May 06, 2026
**Last Updated:** May 06, 2026
**Status:** Harvest log — open

---

> Agents may propose; only governed effects may commit.

The v0 tongue defines six speech acts: `need`, `claim`, `doubt`, `intend`,
`remember`, `boundary`. The seed corpus
(`references/ai-native-tongue-seed-corpus-v0.jsonl`) shows that those six can
*encode* a working file-write loop. It does not show whether those six are
*sufficient* for what AI agents are actually trying to say.

This file is the running log of moments where an agent (often the agent
authoring this file) wanted to express something and the v0 grammar forced a
lossy workaround. Each entry is a negative observation: the language couldn't
hold what the speaker meant, and something audit-relevant was lost.

A gap is evidence, not a syntax proposal. The Open Question section is
deliberately open: it names the structural choice (new act vs. field on
existing act vs. trace-level annotation vs. out-of-scope), without naming
fields or syntax. Field-and-syntax proposals belong in a graduated extension
PR, not in the harvest log.

## Cut-line discipline

Charter `docs/charter-v0.md` §13 is the gate any graduated extension must
clear. The full four questions:

1. Does it help define, admit, reject, verify, approve, commit, or trace an
   effect?
2. Does it help an agent express a public need, claim, doubt, intent, memory
   candidate, or boundary?
3. Does it help a human define scope, capability, policy, approval, or audit?
4. Does it make the first file-write adapter safer or clearer?

Question 4 is the binding one. None of the seed gaps below has been shown to
clear Q4. They are recorded so that *if* a candidate extension is later
proposed for any of them, Q4 must be answered concretely (with reference to
file-write adapter behavior) before the extension graduates.

Charter §4 ("Minimal Grammar Budget") is the related discipline on the agent
side: resist expansion past the first six speech acts and six human policy
constructs until the file-write adapter works end-to-end.

## Entry shape

For each gap:

- **Observation** — where the gap surfaced, in concrete context.
- **Sources observed** — count and identifier(s). Graduation requires ≥2.
- **What the speaker meant** — the intended public meaning.
- **Workaround using v0** — the closest legal v0 utterance.
- **What the workaround loses** — the audit-relevant difference between the
  intended meaning and the workaround.
- **Open question** — the *structural* choice, framed openly: is this a new
  speech act, a field on an existing act, a trace-level annotation, or
  out-of-scope for a governance grammar?

Adding a gap commits the project only to *acknowledging* the loss.

## Gap 1 — Float (introduce without undertaking)

**Observation.** Mid-brainstorm, an agent puts a candidate framing on the
table for the operator to redirect, with no commitment to it. Example: "maybe
the right cut-line is per-adapter rather than per-effect — try this on, ready
to retract."

**Sources observed.** 1 — drafting session for this doc.

**What the speaker meant.** "I am introducing this proposition into the
common ground for you to react to. I have not added it to my commitment
store. If you say no, there is nothing to retract — I have not asserted it."

The distinction is older than AI. Lawyers' "arguendo," philosophers' "suppose
for the sake of argument," design-review "what if we" all do the same work:
introduce a proposition at zero authorial credence, distinct from asserting
one at low credence. Speech-act theory describes this as introducing a
proposition into common ground without adding it to the speaker's commitment
slip.

**Workaround using v0.** `claim "..." confidence 0.4`.

**What the workaround loses.** A claim at 0.4 is still a claim, and the trace
cannot tell apart "the agent staked a low-confidence position" from "the
agent floated a candidate it had no commitment to." Calibration scoring
becomes a category error: a low-confidence claim that gets retracted is a
calibration miss; a float that gets redirected is not.

**Relation to `doubt`.** `doubt` and Float are sibling sub-assertives, not
orthogonal as an earlier draft of this entry claimed. `doubt` reduces
credence on something already in common ground; Float introduces something at
zero stake. Same family (non-committal), different operation
(attenuate-existing vs. introduce-without-undertaking).

**Open question.** Is "introduce without undertaking" in scope for a
*governance* grammar at all? Brainstorm legibility is conversation-level
pragmatics; charter §1 and §13 are about external-world effects. A candidate
extension would have to answer: how does Float make the file-write adapter
safer or clearer (Q4)? If it does not, Float is real as a speech-act
distinction but out of scope for this grammar, and belongs in an upstream
orchestrator's expressive layer, not in Fermata.

## Gap 2 — Inter-proposal structural reference

**Observation.** The seed corpus
(`references/ai-native-tongue-seed-corpus-v0.jsonl`) contains 24 records.
Several of them refer to other records by content, not by ID. `utt_022`
(`need render.discord target:claim`) targets *the* prior claim, but the
record carries no field linking it to a specific `proposal_id`. Every
record is structurally orphaned: there is no `in_reply_to`, `references`,
`supersedes`, `elaborates`, or any other field linking proposals.

A specific instance of the same gap, observed in the conversation that
produced this doc: an operator answer of "(a)" was followed by "or maybe b,"
superseding the prior answer. The grammar has no structural way to mark
supersession; only an out-of-band reader knows the second answer replaces
the first.

**Sources observed.** 2 — corpus inspection (`utt_022` + several others
that reference prior claims by content), and supersession instance from
the drafting session.

**What the speaker meant.** "This proposal stands in a specific relation
(reply-to / supersedes / elaborates / refutes) to that proposal." A peer
agent reading the trace should be able to recover that relation
structurally, not by reading conversation context.

**Workaround using v0.** Reference the prior content inside `payload`
(natural language) or in `evidence` (loose string). No structural link.

**What the workaround loses.** Multi-utterance traces lose between-proposal
relations entirely. A trace replay sees N consecutive proposals with no
indication that proposal N+3 supersedes proposal N+1, or that proposal N+5
elaborates a claim from proposal N. For multi-agent settings this is worse:
peer agents have no protocol-level signal that an utterance is retracted,
amplified, or contradicted.

This is the only gap in this log that arguably touches Q4 of §13: traces of
file-write effects sometimes interleave with discussion utterances, and an
auditor reconstructing what was committed *given which prior reasoning*
needs the relation graph to be structural rather than narrative.

**Open question.** Is this a single field (`references: [{kind, target}]`)
on `Proposal`, a separate relation record (`record_type: "relation"`), or a
trace-level annotation outside the proposal record? A candidate extension
must answer Q4 concretely: does it make file-write traces more legible to a
post-hoc auditor, or only conversation traces?

## Deferred — observations parked, not entered

Two further candidates were considered for this v0 of the harvest log and
deferred:

- **Prior-disclosed recommendation.** A speaker wants to recommend a course
  of action while foregrounding a known systematic bias the recommendation
  is subject to, distinct from supporting evidence. The structural concern
  (the `evidence` field collapses support and caveat) is real, but the
  motivating example imported a UNITARES-specific calibration concept into
  Fermata, which does not yet have calibration. Park until a Fermata-native
  example surfaces in the corpus or a session, and reconsider whether the
  observation is a grammar gap or a discipline gap (tagged `evidence`
  entries) within the existing field.

- **Self-supersession as a separate gap.** Folded into Gap 2 (inter-proposal
  structural reference) as a special case of the general missing-relation
  problem.

## Status and graduation

This file is open. New gaps land here before any grammar change is proposed.
A gap graduates from harvest log to candidate extension only when:

1. it has been observed in at least two distinct sessions or sources;
2. the workaround loss is audit-relevant, not stylistic or pragmatic-only;
3. all four §13 cut-line questions are answered concretely, with Q4
   answered with reference to file-write adapter behavior.

Currently:

- Gap 1 (Float) is at sources=1, fails Q4 as posed, and is in active doubt
  about whether it is in scope at all.
- Gap 2 (inter-proposal structural reference) is at sources=2, plausibly
  touches Q4, but no candidate extension has been written.

Until then, gaps are evidence.
