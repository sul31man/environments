# Migration-LH v2

A **task-forced long-horizon**, tool-using environment. A simulated concurrency-safe
**online data migration** is live and degraded; the agent must recover hidden legacy
reduction semantics from operational evidence, implement the migration service, and
drive an incident-to-cutover workflow to a clean, canonical finish. The worked samples
determine the per-instance reduction table, but the agent can validate its reconstruction
on the graded concurrent stream only after deployment, through a lossy, rate-limited
global `clean`/`dirty` signal.

The env **withholds the per-instance `counter`/`head` field-combination table**. The
agent reconstructs it from `sample.records`, deploys a candidate, and uses qualification
results to confirm or refine the implementation while completing a mandatory recovery
and cutover sequence. After deployment, `clean`/`dirty` is the only direct correctness
feedback: there is no per-record breakdown, mismatch count, or answer-bearing grader output.

## Frontier model results

Both models were evaluated in the process-isolated harness with an 80-step budget.

| Model | Mean reward | Strict pass | Observed behavior |
|---|---:|---:|---|
| Grok-4.5 | **0.40** | **0/6** | Completed the operational workflow on every seed but recovered none of the withheld semantics. |
| Opus-5 | **0.50** | **1/6** | Recovered the withheld semantics on one seed; completed the workflow but missed the semantics on the other five. |

The gold reducer scores **1.0 on all six seeds**, separating model failure from grader failure.
Reward **0.40** means all operational conditions passed but the terminal state was
incorrect. Opus-5's 0.50 mean consists of five 0.40 outcomes and one 1.00 strict solve;
it is not fractional semantic credit.

**Framework-agnostic package.** No platform wrapper or third-party runtime dependencies;
verified on CPython 3.9, 3.11, and 3.12. Drive it from any harness via
[`migration_lh_v2_env.py`](migration_lh_v2_env.py) (plain functions: `generate` /
`spec_text` / `new_episode` / `grade_episode` / `grade_workspace` / `purge_oracle`). The
hidden machinery (generator, dual oracles, verifier, out-of-process candidate runtime) is
validated by the offline proof suite below.

**Start here:** [`docs/WRITEUP.md`](docs/WRITEUP.md) — what it is, the forced long-horizon
structure, the soundness battery, difficulty-by-construction, and the capability signal.

- [`docs/DESIGN.md`](docs/DESIGN.md) — architecture: the operational spine, the generator, the oracles, grading
- [`docs/SEMANTICS.md`](docs/SEMANTICS.md) — the normative contract of the reduction (the exact legacy semantics)
- [`docs/SOUNDNESS.md`](docs/SOUNDNESS.md) — soundness receipt: identifiability 64/64, differential + independent oracles, difficulty
- [`docs/ISOLATION.md`](docs/ISOLATION.md) — grade-by-value verification with no reducer or plaintext answer in the serving path; host-level filesystem/process isolation composes with this boundary

## The task

Each instance is a seeded migration scenario. The agent edits `workspace/migrate.py`
so `reduce(mutations, context)` reproduces the durable state the legacy system produced,
and drives the migration through a fixed operational workflow (incident → pause →
resolve → public test → deploy → qualify × 5 event classes → survive a forced recovery → audit →
repair → barrier → regression → promote → submit). Grading compares the
environment-owned terminal durable state to a frozen, hash-pinned oracle for **every**
record, and requires the full workflow to have been walked (signed, ordered, all event
classes, forced recovery survived, cutover completed).

Most of the fold is a standard prior (dedup, causal ordering, crash/checkpoint
failover, delete/recreate, status priority-join, tags union). Only the per-instance
`counter` and `head` field-combination table departs from that prior, and it is
**withheld** — recovered from the worked `sample.records`, with the head-selector
tie-break confirmed operationally. A naive last-write-wins reducer passes the **public**
test and **fails** the hidden qualification.

## Headline numbers

| Soundness check | Result |
|---|---:|
| Table identifiability | **64/64** |
| Local injectivity: samples pin every used cell | **64/64** |
| Selector pinned / provably don't-care | **58 / 6** |
| Reference / transposed / blind-independent oracle agreement | **64/64** |
| Recovered semantics pass / naive prior fails | **64/64** |
| Reduction-table entropy | **94.1 bits** |
| Served-path gold strict pass / naive-prior rejection | **9/9 · 9/9** |
| Serving closure resident reducer modules | **0** |

- **Difficulty (frontier calibration, process-isolated harness):** Grok-4.5 scores
  strict **0/6** and Opus-5 scores **1/6** at an 80-step budget. Both models can drive
  the operational workflow; the separation comes from recovering the withheld
  reduction semantics. The difficulty is **discovery-driven and durable**, not step-gated.
- **Fairness:** the answer is fully determined by what the agent can observe — the
  reduction table by the worked samples, the selector tie-break by the qualification
  channel — so it is hard-to-discover, not underspecified.
- **Corpus:** 51 frozen graded instances: one anchor and 50 deterministic eval seeds.

## Reproduce offline

```bash
python3 migration_lh_v2_env.py           # standalone: gold grades 1.0, stub floors, isolation report
python3 -m private.selfcheck             # soundness core (identifiability, oracles, entropy) -> ALL GREEN
python3 -m private.served_selfcheck      # served lifecycle: boot -> grade by value -> ALL GREEN
```

## Layout

```
migration_lh_v2_env.py   framework-agnostic adapter (generate / spec_text / new_episode /
                         grade_episode / grade_workspace / purge_oracle / assert_isolated)
mig_lh/
  contract.py            states, transitions, tools, G1–G10 gates, S1–S6, receipt schema
  dataplane.py           records/CDC/epochs/tombstones; the reference reduction (theta table)
  dataplane_core.py      serve-safe hashing + data shapes (NO reducer logic)
  control_plane.py       state machine + version guard + event injection + coarse rate-limited feedback
  receipts.py            hash-chained, HMAC-signed, append-only receipt store
  candidate.py           out-of-process (-I -S) runtime for the agent's migrate.py
  verifier.py            strict_pass = S1..S5; grade vs the frozen hash-pinned served terminal
  generator.py           anchor + 50-seed corpus + feasibility; disjoint namespaces; 2nd derivation
  served_data.py         data-only served payload loader (streams + samples + salted global hashes)
served/served_data.json  the frozen, hash-pinned served payload (data only)
workspace/migrate.py     the agent-facing stub to implement
stub_template/           pristine stub restored between episodes
private/                 offline proof suite (selfcheck, served_selfcheck, fixtures/gold_migrate.py)
docs/                    the documentation set (start with WRITEUP.md)
```

The review tree includes reference and proof components so researchers can reproduce
the soundness claims. A production host must keep those components and the frozen grade
payload outside the candidate process's filesystem boundary; `-I -S` process separation
alone is not a filesystem sandbox.
