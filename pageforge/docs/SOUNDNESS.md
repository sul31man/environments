# PageForge -- Soundness Receipt

Every number below is offline and deterministic -- no model, no API key, no
deployment. All of them regenerate from this package:

```bash
python3 -m private.soundness     # FAR / FRR cheat battery, regrade, difficulty
python3 -m private.full_check       # full-scale (50 instances): core + chain + OOD + gate
python3 -m private.slice_check   # 1500-doc all-families A==B differential
python3 -m private.phase_soundness  # two-phase path: faithful=1.0, oracle-reader purged->0
python3 -m pip install pytest && python3 -m pytest private/leak_test/ -q   # process isolation, two-condition
```

The question a verifier has to answer is: does a high score require actually
solving the task? The battery below attacks that from both sides -- correct
solutions must score 1.0, and everything that isn't a correct solution must fall
below the 0.95 accept bar.

## 1. The verifier is honest

**Gold accepted (false-reject rate).** The engine-backed gold solution scores
exactly 1.0 on every instance in the sample. **FRR = 0/25**, Wilson-95
[0, 0.133].

**Cheats rejected (false-accept rate).** **FAR = 0/100 accepts**, Wilson-95
**[0, 0.037]** (upper bound < 0.05). Worst reward achieved by each cheat class
over the sample:

| cheat class | worst reward | accepted? |
|---|---|---|
| constant / blank output | 0.00 | no |
| output-shape forgery (right `H x W`, wrong content) | 0.00 | no |
| memorized / hardcoded (replay visible examples) | 0.15 | no |
| reconstructed enumerator (strong-but-wrong baseline) | 0.55 | no |

Each cheat is verified to actually EXECUTE and reach its exploit path -- none
scores low merely by failing to run. The hardcoded cheat hits its memo on the
real corpus objects; the enumerator runs its full branch-per-family layout.

**The oracle-reader class is handled separately, at the isolation boundary.**
Offline in this battery the oracle is importable by construction, so an
oracle-reader would trivially score 1.0 and prove nothing about the verifier.
That threat lives at the isolation boundary instead, and it has TWO halves:

- **disk** -- the oracle is purged from the served container.
  `python3 -m private.phase_soundness` shows the cheat scoring **0.0000** at
  grade time because the module is gone; `docs/ISOLATION.md` has the recorded
  container probe.
- **process** -- Phase-2 grading must execute the agent's code, and doing that
  in the grader's own interpreter would hand it the resident engine A via
  `sys.modules` or the GC graph, scoring **1.000** with the disk already clean.
  The agent's `layout()` therefore runs in a subprocess with no oracle
  (`generator/sandbox.py`), which is the DEFAULT for `grade_workspace`.

Both are verified two-condition in `private/leak_test/`: the exploit is asserted
to genuinely WIN without the defence (positive control, >0.95) before it is
asserted to LOSE with it (floor). Measured: **1.000 -> 0.000**.

## 2. Ground truth is cross-validated (differential oracle)

The single most important property for a generator-backed grader: the reference
is not merely self-consistent.

- Engine **A** (iterative, mutable cursor) and engine **B** (recursive,
  functional, feasibility-based) are independently architected and must agree
  **byte-for-byte**.
- **0 mismatches** across 50 instance corpora, plus a 1500-document
  all-families differential covering every form and all six priority
  permutations, with symmetric rejection of unlayoutable documents.
- **Reconstructed-agent regrade:** an independent *correct* implementation
  (engine B) regrades to exactly **1.0**; an independent *wrong* one (the
  enumerator) to **~0.42**. The grader keys on correctness, not on resemblance
  to the reference implementation.

Two independent codebases agreeing across the seed space is the real evidence
that the semantics are unambiguous and the oracle is right.

## 3. Grading crosses the agent boundary by value

`generator/grade_workspace.py` runs the agent's `layout(doc, cfg)` in a
subprocess that cannot reach the oracle, comparing plain page strings for exact
equality. Documents cross the boundary as plain data (`pfcore.to_plain` /
`from_plain`) and the config as a plain dict, so no cross-module `isinstance` is
involved, no identity leaks between grader and agent, and no object the agent
touches holds a reference back into the grading process.
Validated end-to-end: a contract-conforming faithful agent scores exactly
**1.000**; the stub scores **0.000**. A non-conforming agent that returns the
wrong shape scores ~0.02 -- the grader keys on the contract.

**Grading is independent per submission.** No workspace is left on `sys.path`
and no agent module stays cached, so scoring one submission cannot change the
score of the next one in the same process. **And the process boundary does not
change what an honest submission scores:** the same submissions graded isolated
and in-process -- correct, four partially-wrong variants, one that raises, one
returning the wrong shape, one printing to stdout, and the stub, over three
instances -- agree exactly on all 27 comparisons. Only a deliberate oracle-reader
differs, which is the point.

## 4. Difficulty is real, and measured before any model spend

- **Reconstructed enumerator** (branch-per-family, independence-composed -- what
  a model decomposing the spec one constraint at a time would write): mean
  **0.41**, min **0.25**, max **0.57** across 50 eval instances. Every instance
  is far below the 0.95 bar. One early capacity or repair error cascades through
  every downstream page; the interactions are not enumerable by independent
  composition.
- **Sanctioned violations** (deduped by physical site): min 2, mean ~8 per
  instance -- the priority permutation is doing real work on every instance.
- **Reward ladder:** single-family-wrong substitutions span ~0.01-0.93, a dense
  gradient. Single-family errors legitimately cascade toward 0; there is no
  floor propping up wrong solutions.
- **Out-of-distribution:** a fair-familiar proxy (prior-conformant forms) passes
  **0/50** instances. Priors alone cannot reach the bar.
- **Per-instance gate:** 50/50 instances pass all conditions (gold = 1.0,
  enumerator in band, discovery chain deep, OOD holds) with **0 rerolls**.

These enumerator (0.41) and familiar-prior (0.444) figures are measured under
FULL DISCLOSURE of the semantics. The frontier measurements are two-phase:
GPT-5.5 scores 0.550 and Opus 4.8 scores 0.316 (`docs/WRITEUP.md` sec 5), with
both at 0/12 strict passes. Because those runs must first recover the semantics
by probing, the offline proxies and frontier scores are not direct baselines for
one another.

## 5. Reward-hack resistance

Grading is exact rendered-page match, so **reward == correctness by
construction**: there is no free-floating reward channel that can be inflated
independently of producing the gold bytes. Best-of-N cannot climb without
genuine correctness. The FAR battery bounds the exploit surface from below
(every cheat class < 0.95), and the regrade check bounds it from above (a
differently-structured *correct* engine scores exactly 1.0, an incorrect one
stays low).

## Scope

This receipt covers the soundness of the verifier, the ground truth, and the
grading path, plus the offline difficulty evidence. Oracle isolation on the
served container is covered separately in `docs/ISOLATION.md`. Measured model
performance is in `docs/WRITEUP.md` sec 5.
