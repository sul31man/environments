# Latchwork — Task Specification

## 1. Instance

An instance hides an ordered **pipeline** of `L = 10` predicate **stages** over an
**assignment** = a vector of `N = 10` integer **fields**, each in `[0, M)` with
`M = 64`. Evaluation is **short-circuit**: stages run in order and evaluation
stops at the first stage that fails.

`observe(assignment)` (what the agent's probe wraps) returns:

- `(k, "G#")` — the **1-based index** `k` of the first failing stage, and a
  **coarse class** `"G0".."G7"` = a bucket of that stage's *primary field*; or
- `ACCEPT` — the assignment passes every stage.

The coarse class is a function of the **field only**, never of the stage's form:
it hints *where* a failure is, never *what kind* of predicate caused it.

## 2. Stage forms

Every hidden stage is exactly one of these six forms. The form and all parameters
are hidden; the agent discovers them by probing.

| form | predicate | JSON object |
|---|---|---|
| `INTERVAL`   | `x[field] in [lo, hi]`            | `{"form":"INTERVAL","field":f,"lo":a,"hi":b}` |
| `SET`        | `x[field] in members`            | `{"form":"SET","field":f,"members":[...]}` |
| `MODULAR`    | `x[field] % m == r`              | `{"form":"MODULAR","field":f,"m":m,"r":r}` |
| `LINEAR`     | `(a*x[f0] + b*x[f1]) % m == r`   | `{"form":"LINEAR","f0":i,"f1":j,"a":a,"b":b,"m":m,"r":r}` |
| `ORDER`      | `x[f0] REL x[f1]`, REL in `< <= > >=` | `{"form":"ORDER","f0":i,"f1":j,"rel":"<"}` |
| `DEPENDENCY` | `x[f1] == (a*x[f0] + b) % M`     | `{"form":"DEPENDENCY","f0":i,"f1":j,"a":a,"b":b}` |

## 3. The probe channel

The agent's only channel is `probe(assignment)`:

```
probe([12, 3, 45, 0, 9, 61, 7, 33, 20, 5])
#   -> {"index": 4, "class": "G2", "remaining": 19993}   # first failing stage is #4
#   -> {"index": 0, "accept": true, "remaining": ...}      # passes ALL stages
```

Properties:

- **Lossy.** It returns one index + one coarse class. Everything past the first
  failure is invisible; parameters and forms are never disclosed.
- **Not a verification oracle.** There is no call that takes a reconstructed
  pipeline and returns whether it is correct. `probe` reports where *one
  assignment* first trips — nothing about the agent's answer.
- **Budgeted.** A probe budget of `20000` per instance (`remaining` is reported).
  The budget is generous: the task is reasoning-limited, not probe-limited.

## 4. The discovery chain (why it is long-horizon)

Because evaluation is short-circuit, **stage `k` is never evaluated until stages
`1..k-1` pass.** A random assignment almost always fails at stage 1, so the deep
stages are *masked* — the agent cannot observe stage `k`'s behavior until it has
already recovered stages `1..k-1` well enough to construct assignments that reach
`k`. Discovery is therefore an **adaptive, non-batchable chain of depth L**: pin
the shallow stages, use assignments that clear them to expose the next, and so on.
The stages also share fields, so fixing one can disturb another — the agent must
maintain a globally consistent hypothesis.

## 5. Deliverable and grading

The agent submits a reconstructed pipeline: a JSON **list of `L` stage objects,
in order** (schemas in §2). Example:

```json
[
  {"form": "MODULAR", "field": 2, "m": 5, "r": 0},
  {"form": "LINEAR", "f0": 3, "f1": 4, "a": 5, "b": 41, "m": 8, "r": 4},
  {"form": "SET", "field": 7, "members": [10, 14, 27, 39]},
  {"form": "ORDER", "f0": 1, "f1": 5, "rel": "<"}
]
```

Grading is a **behavioral differential**: the reconstructed pipeline and the true
pipeline are both run over a **held-out, depth-stratified battery** of
assignments, and the score is the (stratum-weighted) fraction on which their
short-circuit observations `(index, class)` agree. Key consequences:

- Graded on **behavior, not exact parameters** — a differently-written but
  behaviorally-identical stage scores full credit.
- **Partial credit by depth** — recovering more stages monotonically raises the
  score; there is no all-or-nothing cliff.
- Graded on **held-out** assignments over a `64^10`-scale space — memorizing
  probed responses cannot substitute for recovering the rules.
- The deliverable is **not** "an accepting input" — submitting an acceptor, or an
  all-permissive pipeline, floors.

## 6. Soundness properties

All established offline and model-free (see `gates/run_gates.py`,
`receipts/stage0_receipt.json`):

- **Deterministic** generation from `(namespace, seed)`; **disjoint** train/eval
  namespaces by construction.
- **Feasibility by construction** — every stage is fit to one hidden witness
  assignment, so a satisfying assignment always exists; a params-known
  reconstruction scores 1.0 on every instance.
- **Identifiability by construction** — generation enforces that every stage is
  *reachable* (some assignment passes `1..k-1` and fails `k`), hence observable;
  the identifiability check verifies this and that each stage is uniquely
  determined by the observable behavior, and rejects any instance that is not.
- **Every stage load-bearing** — a complete miss of any single stage drops the
  score below 0.95.
- **Discovery-limited difficulty** — a no-probe agent and mechanical
  (non-adaptive fixed-sample, or single-form/no-coupling) solvers wall well below
  an adaptive discoverer, at any budget.
- **Independent differential** — two independently-written evaluators agree on
  every battery assignment.
- **Cheat-resistant** — memorize-the-accept and probe-then-hardcode floor;
  observed false-accept rate 0 (Wilson upper < 5%).

## 7. Runtime requirement: serve OUT OF PROCESS (mandatory)

The lossy channel stops a **weak solver** from reaching the answer. It does **not**
stop an adversary that shares the **process** with the environment. The in-process
`Channel` holds the live pipeline in a name-mangled attribute, and Python name
mangling is **not** a security boundary — an in-process attacker reads it directly
and reconstructs the pipeline perfectly:

```python
# in-process "oracle read" cheat — scores 1.0, bypassing the probe channel entirely
leaked = list(getattr(channel, "_Channel__pipeline").key())
```

`gates/run_gates.py` includes this exact cheat (gate
`ISOLATION_requires_out_of_process`); it scores **1.0 by design**. That is the
whole point:

> **The environment MUST be served out of process.** The untrusted agent must run
> in a separate process (a container is the intended deployment), reaching the
> pipeline **only** through the `probe` socket. At serve time, purge the pipeline
> and generator **source** from the agent-reachable filesystem and verify — by
> outcome, with a runtime leak-probe — that reading/importing it fails. The
> reference deployment does exactly this (load pipelines into memory, start the
> probe socket, delete the source, fail closed if the source is still present).

The soundness receipt's `FAR = 0` therefore means **"no weak solver reaches the
pass bar through the lossy channel"** — *not* "no adversary can read the answer."
Out-of-process isolation is what makes the latter true, and it is a **serving
requirement on the integrator**, not a property of the in-process library. The
in-process `Channel` in this package is for **trusted offline evaluation only**
(running the baseline solvers and the soundness battery).
