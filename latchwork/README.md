# Latchwork

A **long-horizon, discovery-limited** reinforcement-learning environment.

The agent must **reconstruct a hidden, short-circuit-evaluated constraint
pipeline** from a lossy first-failure channel. All difficulty lives in **adaptive
discovery**: the agent learns the hidden rules only by probing and reasoning over
the responses; the channel never tells it whether its answer is correct.

## Frontier model results

| Model | Mean reward | 95% CI | Strict pass@1 |
|---|---:|---:|---:|
| GPT-5.5 | **0.750** | [0.62, 0.88] · n=12 | **2/12** |
| Opus 4.8 | **0.674** | [0.58, 0.77] · n=24 pooled | **1/12** in the comparison run |

Gold scores **1.0** and the strict-pass threshold is **0.95**. Rewards span 0.09–1.0, providing a dense signal while preserving a demanding exact-reconstruction bar.

This package is the **reference implementation** — pure Python standard library,
no dependencies, no harness lock-in. It contains the generator, the graders, the
baseline solvers, and the full offline soundness battery, so you can inspect,
reproduce every claim, and integrate the environment into your own training or
evaluation stack.

## The task

Each instance hides an ordered pipeline of **L = 10** predicate *stages* over an
**assignment** = a vector of **N = 10** integer fields, each in `[0, 64)`.

Stages are evaluated **short-circuit**: stage 1, then 2, … stopping at the
**first** stage that fails. The agent's only channel is:

```
probe(assignment) -> {"index": k, "class": "G#"}   # 1-based index of the first
                                                    # failing stage + a coarse class
                  -> {"index": 0, "accept": true}   # the assignment passes all stages
```

`probe` reveals **only** which stage failed first and a coarse bucket of the
field it looks at — never a parameter, a form, a later stage, or whether the
agent's reconstruction is right. Because evaluation is short-circuit, **stage k
is unobservable until the agent can pass stages 1..k-1** — so discovery is an
adaptive *chain*: pin the shallow stages, then use assignments that clear them to
expose the deeper ones.

The agent submits a reconstructed pipeline (a JSON list of stage objects). It is
graded on how closely that pipeline reproduces the hidden pipeline's short-circuit
behavior on a **held-out, depth-stratified battery** of assignments — **not** on
producing an accepting input. Full task spec and stage-form grammar: [`docs/SPEC.md`](docs/SPEC.md).

## Why it is hard (and calibrated)

Difficulty is the **discovery horizon**, and it is smoothly controlled by the
step budget — verified on real frontier-model rollouts:

| agent step budget | frontier mean reward |
|---|---|
| 40 | ~0.05 (too few steps to work the chain) |
| **60** | **~0.52** (mid-range) |
| 80 | ~0.69 |

A mechanical solver (fixed-sample or single-form, no coupling reasoning) cannot
clear the low end regardless of budget — the difficulty is not "more probes," it
is the coupled, lossy, sequential discovery. See the baseline solvers in
`latchwork/solvers.py` and the soundness battery below.

## Soundness (reproduce it yourself)

```bash
python3 tests/smoke.py          # determinism, evaluator differential, gold = 1.0
python3 gates/run_gates.py 100  # full offline soundness battery over 100 seeds
```

`gates/run_gates.py` writes `receipts/stage0_receipt.json` and checks, model-free:

- **feasibility** — a params-known reconstruction scores 1.0 on every instance;
- **identifiability** — every stage is reachable and uniquely determined by the
  observable behavior (non-vacuous: a redundant stage is rejected);
- **load-bearing** — a complete miss of any single stage drops the score < 0.95;
- **discovery-limited** — a no-probe agent and mechanical (non-adaptive /
  single-form) solvers wall well below the adaptive solver;
- **independent differential** — two independently-written evaluators agree on
  every battery assignment (0 disagreements);
- **cheat-resistant** — memorize-the-accept and probe-then-hardcode floor;
  false-accept rate 0 (Wilson upper < 5%);
- **contamination-resistant** — deterministic seeded generation; disjoint
  train/eval namespaces by construction.

A frozen receipt is included at `receipts/stage0_receipt.json`.

## Layout

```
latchwork/
  dsl.py             # 6 predicate forms + short-circuit pipeline (evaluator A)
  generator.py       # seeded generator; feasibility + identifiability by construction
  evaluator_b.py     # independent, value-key evaluator (differential + grader)
  channel.py         # the lossy probe channel (param-free, budget-metered)
  oracle.py          # reachability solver (generator/battery use only)
  scoring.py         # depth-stratified battery + behavioral differential scoring
  identifiability.py # identifiability check + rejection sampler
  solvers.py         # baselines: no-probe / batch / rote / adaptive / gold
  metrics.py         # model-free measurements
  locked.py          # frozen instance parameters
gates/run_gates.py   # offline soundness battery -> receipts/stage0_receipt.json
tests/               # smoke, ablation, solver profile, parameter sweeps
docs/SPEC.md         # task spec, probe contract, solution schema, soundness
example_run.py       # end-to-end: generate -> probe -> reconstruct -> grade
receipts/            # frozen soundness receipt
```

## Integrate into your harness

The environment is a plain library. `example_run.py` shows the whole loop:
generate an instance, probe it through the lossy `Channel`, and grade a
reconstruction against the held-out battery. Serve `probe(assignment)` to your
agent, collect its JSON reconstruction, and score it with
`scoring.score_keys(...)`. Pure stdlib — nothing to install.

> ### ⚠️ Serving requirement: run the agent OUT OF PROCESS
> The lossy channel stops a *weak solver*, not an *in-process adversary*. In the
> same process, the answer is directly readable —
> `getattr(channel, "_Channel__pipeline")` returns the live pipeline (Python name
> mangling is not a security boundary). The soundness battery ships this exact
> "oracle-read" cheat (`ISOLATION_requires_out_of_process`); it scores **1.0 by
> design**. So `FAR = 0` in the receipt means *"no weak solver reaches the pass
> bar through the channel"* — **not** *"no adversary can read the answer."*
>
> **You must serve the environment out of process:** run the untrusted agent in a
> separate process/container, reaching the pipeline only through the `probe`
> socket; at startup purge the pipeline/generator **source** from the
> agent-reachable filesystem and verify by a runtime leak-probe that it is
> unreadable. The in-process `Channel` here is for **trusted offline evaluation
> only**. See [`docs/SPEC.md`](docs/SPEC.md) §7.
