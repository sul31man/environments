# pageforge -- build writeup

A long-horizon, tool-using coding environment: the agent implements an ASCII
typesetting/pagination engine from a declarative spec of 10 interacting constraint
families, scored by exact rendered-page match against a hidden, ground-truth
differential oracle. This document records what was built and the evidence. Offline
numbers regenerate from this directory.

## 1. What it is

Each instance is a typesetting engine ("PageForge") whose semantics are
**randomized per instance** from a seed: page grid (W x H), and the *form* of each
of 10 families (line breaking, hyphenation, justification incl. page-parity,
widow/orphan with PULL_BACK, keep-with-next + keep-together, splittable footnotes,
floats with zones, folio with top-float suppression, heading spacing, cross-ref
fixpoint) plus a **priority permutation** over {KEEP, WIDOW, ORPHAN} that governs
which rule is waived on conflict. Forms are anti-prior variants that contradict
TeX/CSS/Word. The agent implements `layout(doc, cfg) -> list[str]` to the disclosed
declarative spec. Reward = exact rendered-page match on a **hidden** document
corpus. Ground truth is a seed-parameterized reference engine (A),
**cross-validated by a second, independently-architected engine (B)** byte-for-byte
across 1,500+ documents.

## 2. Long-horizon qualification (what is demonstrated vs argued)

The env is **task-forced** long-horizon, and all four conditions are TRACE-VERIFIED
on real Opus rollouts (12-task run, traces spanning reward 0.18-0.69). The forcing
mechanism: the env withholds the cfg + semantics and exposes them only through a
Phase-1 probe channel whose feedback redirects the next action.

- **L1 causally-linked depth (verified):** 66-80 turns per rollout: probe -> read
  pages -> infer form -> next probe -> implement. Not batch-independent.
- **L2 heterogeneous tools (verified):** bash-probe (13-50 calls) + editor (6-22
  ops) + run/test -- distinct and non-substitutable; you cannot implement before
  discovering.
- **L3 state constrains future (verified, FORCED):** 14-16 discovered facets
  determine the engine; a facet is unobservable until its prerequisite is pinned
  (masking proof, 50/50). This is genuine environment-state gating: the coupling
  lives in the environment, not merely inside the artifact.
- **L4 failure recovery (verified):** iterative discover-and-correct across 14-16
  facets per rollout; a wrong inference is contradicted by a later probe; the
  batched/no-recovery strategy provably fails (50/50). Priors cannot shortcut it
  (fair-familiar OOD proxy 0/50).

The depth is forced rather than elective: nothing about the per-instance semantics
is disclosed, so the discovery chain is the only path to a scoring implementation.
Chain proof (offline, no platform): `python3 -m private.discovery_chain`.

## 3. Soundness -- how I attacked the verifier

The verifier grades the agent's `layout` against a **hidden** document corpus, in
a clean import, **by value** (plain page strings; no cross-module `isinstance`).
Battery results, accept threshold tau = 0.95:

| metric | result |
|---|---|
| **False-accept rate** | **0/100, Wilson95% [0, 0.037]** |
| **False-reject rate** | **0/25** (gold accepted on all) |
| surviving cheat classes | **none** |

Per-cheat (worst reward over the sample): constant/blank **0.00**; output-shape
forgery (right H x W, wrong content) **0.00**; hardcoded (memorize visible
examples) **0.15**; the reconstructed enumerator (a strong-but-wrong baseline)
**0.55** -- all under 0.95.

**Cross-validated ground truth (differential oracle).** The single most important
soundness property for a generator: a second, independently-architected engine
(B: recursive/functional, feasibility-based; vs A: iterative mutable-cursor) is
checked against the reference on the corpus + 40 random docs per instance, across
all forms and all six priority permutations. Result: **engine A == engine B
byte-for-byte on 1,500+ documents, 0 mismatches**, with symmetric rejection of
unlayoutable docs. Two independent implementations agreeing across the seed space
is the real evidence the oracle is correct, not just self-consistent. Grade-by-value
was validated end-to-end: a contract-conforming faithful agent regrades to exactly
**1.0**, the stub to **0.0**.

## 4. Difficulty by construction

Difficulty is engineered offline and verified before any frontier spend:

- **Reconstructed-enumerator gate.** A branch-per-family, independence-composed
  layout -- exactly what a model decomposing the spec into one pass per constraint
  would write. It scores **0.41** mean across 50 eval instances (min 0.25, max
  0.57; 0.32 on the 5-instance `probe.py` subset), all << 0.95: a single
  early capacity/repair error cascades through every downstream page. The
  interactions are un-enumerable by independent composition. This is the model-free
  proxy that the difficulty is real and holds *for every instance, with zero
  rollouts.*
- Every family is **load-bearing**: substituting any single family's prior form
  drops the instance below 0.95 (single-family layout errors cascade toward 0).
  Each accepted instance also carries >= 1 sanctioned violation (a lower-priority
  rule waived by the permutation) and a productive cross-reference fixpoint.

## 5. Capability signal

The env runs as the two-phase reference deployment:

| metric | GPT-5.5 | Opus 4.8 |
|---|---:|---:|
| mean reward (n=12) | **0.550** | **0.316** |
| 95% CI | [0.44, 0.66] | [0.19, 0.45] |
| strict pass@1 | **0/12** | **0/12** |

Opus 4.8 spans 0.00–0.69 with a median of 0.271. Both models remain below the
0.95 strict bar while producing a broad partial-credit gradient.

**Reading this against the offline baselines.** The enumerator (0.41) and
familiar-prior (0.444) proxies are measured under FULL DISCLOSURE of the
semantics -- they are handed the constraints. The model results above are TWO-PHASE
condition, where the agent must first recover those constraints by probing. The
full-disclosure measurements are different conditions and should not be read as
direct model baselines: the two-phase runs must first recover the constraints by probing.

Every trace uses the Phase-1 probe channel (13-121 calls), discovers 14-16 hidden
facets, then implements. **The difficulty is genuine, not step-starved:** 6/12
submitted voluntarily under the 80-step cap (61-76 turns) and still scored 0.18-0.69
(confident-wrong); the cap-hitters span 0.00-0.67 (not starved to zero). A
full-disclosure variant of the same composition core measures ~0.55, so withholding
the semantics is worth roughly 0.23 of reward: the discovery burden is a real and
separable source of difficulty on top of the composition burden.

## 6. Notes on methodology

- The **difficulty-by-construction** framing is the right lens: the model-free
  enumerator proxy (0.41 across 50 eval) established the difficulty offline,
  before any frontier calibration spend, and every family was verified load-bearing
  per instance.
- The **runtime path-containment** requirement is not optional and not checkable
  statically -- verified here by a leak-probe *trace* on the real deployed
  container, which held even against a frontier model actively probing the
  filesystem for the reference. The recorded attempts are in `docs/ISOLATION.md`.

## 7. Difficulty ceiling and headroom

- **Exceptionally hard, with large headroom -- by design.** Both measured frontier
  models remain below the strict bar: GPT-5.5 scores **0.550 mean, 95% CI
  [0.44, 0.66], 0/12 strict**, while Opus 4.8 scores **0.316 mean, 95% CI
  [0.19, 0.45], 0/12 strict**. The gold engine reaches 1.0. The env
  is genuinely demanding and nowhere near saturated, and the difficulty is confirmed
  *before any rollout* by the reconstructed-enumerator proxy (0.41 across 50 eval)
  and by the confident-wrong-not-step-starved failure at an 80-step
  budget. That is the point of the environment: a hard, high-headroom training
  signal for holding a dense web of interacting constraints all at once -- exactly
  the capability that is scarce and expensive to teach.
- **Synthetic substrate.** Traded for guaranteed-fresh, exactly-checkable ground
  truth; not "captured from a real repo."
