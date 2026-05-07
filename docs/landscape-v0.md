# Fermata in the Landscape v0

**Created:** May 06, 2026
**Last Updated:** May 06, 2026
**Status:** Active

---

> Agents may propose; only governed effects may commit.

This note positions Fermata against five neighboring families of systems. The
goal is to be honest about what already exists, what already works, and where
Fermata is and is not trying to compete.

If a layer is already well-served by an adjacent system, Fermata should not
claim novelty there. Fermata's claim is narrow: a typed runtime contract for
the moment when an agent's proposal becomes a committed external-world effect.

## The five families

```text
human / orchestrator / agent
        ↓ propose
governed-effect contract  ← Fermata
        ↓ admit / verify / approve / commit / trace
external world
```

Above Fermata: orchestrators that plan steps and route agent work.
Below Fermata: adapters that touch real files, databases, messages, memory,
deployments. To the side of Fermata: policy and guardrail layers that shape
inputs and outputs in ways adjacent to admission.

Underneath the whole stack: compute languages that run the model itself.

| Family | Examples | Layer | Relation to Fermata |
|---|---|---|---|
| AI compute kernels | Triton, CUDA, Metal | Below the model | Fermata can govern *use of* compute, not compete with compute |
| AI systems languages | Mojo | Model + program runtime | Fermata is not a programming language replacement |
| Agent orchestrators | LangGraph, AutoGen, CrewAI | Above Fermata | They propose; Fermata governs whether proposals can commit |
| Runtime guardrails | Guardrails AI, NeMo Colang | Adjacent / partial overlap | They shape model input/output; Fermata governs effect admission |
| Policy-as-code | OPA / Rego, AWS Cedar | Adjacent on the policy axis | They evaluate policy; Fermata uses policy as one input to admission |

## AI compute kernels: Triton, CUDA, Metal

Triton is a Python-embedded language for writing GPU kernels. CUDA and Metal
are vendor compute platforms. They define how a model's tensor operations get
turned into instructions on hardware. Fermata is not on this layer at all.

What this means for Fermata:

- Fermata can sit in front of *invocations* of compute (e.g., a deployment
  proposal that runs a Triton-compiled kernel) and treat the invocation as a
  governed effect with scope, capability, approval, and trace.
- Fermata never tries to express what the kernel does. The kernel is opaque
  to the runtime contract; only the *invocation boundary* is governed.
- A future adapter might wrap a model-serving deployment as an effect
  ("commit a model rollout to inference cluster X"). The kernel inside is
  none of Fermata's business.

No competition with compute. Different stratum.

## AI systems languages: Mojo

Mojo is a Python-superset systems language with a compiler, a borrow checker,
and a runtime designed for AI workloads. It is a *programming language* in the
serious sense: it competes with Python and Rust on different axes.

Fermata is not a programming language. The charter (`docs/charter-v0.md` §2)
explicitly disowns this:

> Not a general-purpose replacement for Python, Elixir, JavaScript, Rust, or
> shell.

What Fermata *is* in this neighborhood: a typed contract layer that any
language — Python, Mojo, Elixir, TypeScript — can call into when an agent's
proposal needs to cross the commit boundary. The IR is a JSON-Schema-bounded
record set, not a syntax. Fermata's "language" is in the agent-utterance
tongue (`docs/ai-native-tongue-toolkit.md`) and the human-policy DSL, both
intentionally small.

## Agent orchestrators: LangGraph, AutoGen, CrewAI

These systems plan and route agent steps. They model agents as nodes in a
graph or as roles in a crew, with messaging, retries, and step ordering.
They are good at deciding *which agent does which step in which order*.

Fermata sits *underneath* them. An orchestrator decides "the planner agent
should now propose a file write." Fermata decides whether that proposal
becomes a committed file write.

What an orchestrator already does well:

- multi-agent coordination, role assignment, message routing;
- step dependency, retry policy, tool discovery;
- conversation memory and history.

What an orchestrator does *not* answer:

- when does a tool call become a real, audited, externally-acknowledged
  change in the world?
- can the trace prove that this rollout, file write, or memory entry was
  proposed by which agent, admitted by which policy, approved by whom, and
  committed by which adapter?

Fermata's claim is the second list. The first list is the orchestrator's job.

A working pairing: LangGraph plans the steps; each tool node calls
`evaluate_<adapter>` (or, post-#4, an explicit interpreter) on a Fermata
proposal; Fermata's outcome becomes the node's result.

## Runtime guardrails: Guardrails AI, NeMo Colang

Guardrails AI shapes LLM input/output: schema validation, regex constraints,
profanity filters, structured-output enforcement. NeMo Colang models dialog
flow with topic boundaries and conversational guardrails. Both improve the
shape of what a model says, before any side effect is contemplated.

There is genuine overlap on the *policy* axis. A Guardrails policy that
rejects a malformed JSON output is doing some of the work of an admission
check. A Colang flow that refuses a topic is doing some of the work of a
boundary speech act.

What guardrails systems do that Fermata does not:

- output-shape validation against rich schemas;
- conversational policy at the dialog level (topic refusal, fallback
  prompts);
- input redaction and prompt-injection defense.

What Fermata does that guardrails systems do not:

- type the boundary between proposal and committed external-world effect;
- guarantee that no path through the system can produce a `CommittedEffect`
  except through an adapter's commit operation, with durable acknowledgement;
- record a trace that distinguishes admission, verification, approval,
  adapter error, verification failure, and policy rejection;
- pause for human approval as an ordinary state, not an exception path.

Adjacent. Some overlap on the policy axis. Different center of gravity.

## Policy-as-code: OPA / Rego, AWS Cedar

OPA (Open Policy Agent) with the Rego language, and AWS Cedar, are general
policy engines. You write declarative policies; the engine evaluates them
against a request context and returns allow/deny with reasons.

This is the closest neighbor on the policy axis. A Fermata `policy` rule
("deny if target.outside_scope") could in principle be expressed in Rego or
Cedar. Both engines are mature, well-tooled, and integrated with Kubernetes,
IAM, and other infrastructure.

What OPA / Cedar already do well:

- expressive policy language with strong testing tooling;
- decoupled policy authoring from application code;
- integration into request-path admission control across many systems.

Fermata does *not* attempt to compete on policy expressiveness. The v0
policy surface (`docs/charter-v0.md` §4.1) is intentionally minimal: six
constructs total, sized to fit the file-write adapter and nothing more.

What Fermata does that a policy engine alone does not:

- pair policy admission with the *typed effect lifecycle*: a policy decision
  is one phase of a state machine that runs Proposal → Intent →
  AdmissibleEffect → VerifiedEffect → ApprovedEffect → CommittedEffect, with
  Rejected and Paused as ordinary results;
- bind policy to the proposal speech-act ontology
  (need / claim / doubt / intend / remember / boundary), so an agent's public
  utterance and a human's policy live in the same trace;
- define `Committed` as a load-bearing, adapter-acknowledged state — not a
  policy decision but a verified change in the world.

A future adapter could plausibly delegate the policy phase to OPA or Cedar.
Fermata's contribution is the surrounding contract, not the policy DSL.

## What Fermata adds that nothing here adds together

The thin claim:

> A typed contract for agent-mediated external-world effects, in which
> `CommittedEffect` is defined adapter-by-adapter as a durable, verified
> change, and any path that produces a commit must produce a trace
> distinguishing proposal, intent, admission, verification, approval,
> adapter ack, and verification status.

The neighboring systems each cover part of the surrounding picture:

- compute languages run the model;
- systems languages run the program;
- orchestrators decide step order;
- guardrails shape input/output;
- policy engines evaluate policies.

None of them, alone or together, produce the typed proposal-to-commit
boundary with adapter-acknowledged verification as a first-class runtime
contract. Fermata is small precisely because that contract is small. The
charter discipline (§§11–13) keeps it small on purpose.

## Where Fermata can call into compute languages, not compete with them

A clarifying example. An agent proposes a model rollout:

1. Orchestrator (LangGraph) decides the rollout is the next step.
2. Agent emits `intend deploy.model target:"prod-cluster" ...` per the
   tongue grammar.
3. Fermata's deploy adapter (hypothetical, post-v0) admits the proposal:
   scope check, capability `deploy.model`, policy on which clusters/models,
   approval gate, dry-run rendering of the resulting state.
4. On approval, the adapter calls into a deployment system that ultimately
   schedules Triton-compiled kernels on GPU. The adapter's commit returns
   a durable handle (release ID, model version).
5. Fermata records `effect.committed` with that handle and a verification
   step that queries the deployment system for the resulting state.

Triton, CUDA, the Kubernetes scheduler, and any policy engine in the chain
all do their jobs. Fermata provides the typed boundary and the trace. None
of those systems is replaced or competed with.

## Cut-line for this note

This note should not grow into a survey paper. It exists to make four things
clear to a reader who has not read the rest of the repo:

1. Fermata is small.
2. The neighbors are real and good.
3. Fermata's claim does not require any of the neighbors to be wrong.
4. Where Fermata's claim is novel is the boundary itself, not any of the
   sub-disciplines (policy, orchestration, compute, structured output) that
   the boundary uses as inputs.

If a future revision of this note tries to argue Fermata's superiority on a
neighbor's home turf, that revision is wrong about the project, not about
the comparison. Cut it.
