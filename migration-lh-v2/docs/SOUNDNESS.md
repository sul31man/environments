# migration-lh-v2 — soundness

Every claim here is checked by the offline proof suite:

```
python3 -m private.selfcheck            # soundness core (N=64)
python3 -m private.served_selfcheck     # served-path lifecycle (N=9)
python3 migration_lh_v2_env.py          # standalone: gold 1.0, stub floors
```

## 1. Feasibility and identifiability (the task is solvable *and* fair)

For every released instance, a correct reducer using the drawn table strict-passes, and
the table is recoverable from what the agent can observe. Measured over N=64:

| property | result |
|---|---|
| identifiability — recovered table `== ` truth on the used cells | **64/64** |
| local injectivity — the worked samples pin **every** used cell | **64/64** |
| head-selector — pinned by evidence, or don't-care | **58 / 6** (never underdetermined) |
| used cells per instance | 7 (min 7, max 7) |

This is the fairness guarantee: the answer is **determined by what the agent can see**,
so the task is *hard to discover*, not *underspecified*. The reduction table is pinned by
the worked samples; the one global parameter the samples do not always exercise — the
head selector — is pinned by the operational qualification channel instead (a wrong
selector qualifies `dirty`), so it is discovered by acting. An independent check
(enumerate every table consistent with the shipped samples, confirm the graded terminal
is invariant) reproduces this result: no sample-consistent table yields a different
answer that the operational channel does not also expose.

## 2. Non-triviality (the naive prior is not enough)

| property | result |
|---|---|
| two-condition **positive** — the recovered table reproduces the terminal | **64/64** |
| two-condition **negative** — the naive last-write-wins / whole-record prior misses | **64/64** |
| reduction-table entropy (non-enumerable through the rate-limited channel) | **94.1 bits** |

A last-write-wins reducer passes the **public** test and fails the **hidden**
qualification on every instance. The table cannot be guessed or brute-forced through the
single, rate-limited, global `clean`/`dirty` bit.

## 3. Grade correctness (independent oracles agree)

| property | result |
|---|---|
| transposed derivation (`reduce_theta_b`, collect-then-fold) agrees with the reference | **64/64** |
| **blind independent oracle** (no shared code, authored from the spec alone) agrees | **64/64** |
| served-path gold (positive control) — a correct reducer strict-passes | **9/9** |
| served-path negative — the naive prior deploys, passes public, fails the hidden grade | **9/9** |

The grade is anchored to a frozen, hash-pinned served terminal. Two checks confirm it:
a **transposed** derivation (`generator.reduce_theta_b`) that varies the loop shape but
reuses the reference primitives — this catches loop/transcription errors; and a **blind
independent oracle** (`private/oracle_blind.py`) that shares *no* code with the reference
(a from-scratch reimplementation of the keep-filter, causal order, feature-schema cell
mapping and fold, written from the specification alone) — this validates the shared core
itself, not just the loop. Both agree with the reference byte-for-byte on every instance.

## 4. Difficulty (frontier calibration)

Two frontier models were run through a process-isolated evaluation harness (leak-free
grading, an 80-step budget) on six eval seeds:

| metric | Grok-4.5 | Opus-5 |
|---|---:|---:|
| strict `pass@1` | **0/6** | **1/6** |
| reward pattern | 0.40 on 6/6 | 1.0 on 1/6; 0.40 on 5/6 |
| operational gates (S2–S5) driven | all green, 6/6 | all green, 6/6 |
| data-correctness (S1) | 0.0 on 6/6 | 1.0 on 1/6; 0.0 on 5/6 |
| gold reducer on the same seeds | 1.0 on 6/6 | 1.0 on 6/6 |

Both models drive the *entire* operational workflow — pause, resolve, deploy, execute all
event classes, correctly diagnose and apply the forced recovery, reconcile, regress, and
cut over. Opus-5 is the first model in this calibration to recover the withheld semantics,
doing so on one seed. The other 11 model-seed runs fail at semantic recovery rather than
workflow execution. Gold scoring 1.0 throughout separates that capability gap from grader
failure.

## 5. Corpus

51 frozen graded instances (one anchor + 50 deterministic eval seeds) are included in
the released corpus.
