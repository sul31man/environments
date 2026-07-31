# migration-lh-v2 — writeup

## What it is

A single-episode, **task-forced long-horizon** environment built around one coherent
job: recover the hidden semantics of a concurrency-safe **online data migration** and
drive it to a clean cutover. The agent is dropped into a live, degraded migration and
must do two coupled things inside one trajectory:

1. **Implement the migration service.** Edit `workspace/migrate.py` so
   `reduce(mutations, context) -> {record_id: snapshot}` folds the injected event
   stream into the exact durable state the legacy system produced. The correct
   semantics are **not** written down anywhere the agent can read; they are recovered
   from simulated operational evidence surfaced by the tools.

2. **Operate the migration.** Drive the typed tool spine in a legal order: reproduce
   the incident, pause the target cohort back to legacy, resolve the failed generation,
   deploy the reducer, qualify each injected event class under canary, survive a
   **forced** recovery (diagnose the symptom, then apply the matching family — guessing
   is rejected), then audit forward, repair history, verify per-partition barriers, run
   regression, promote, and submit.

Grading compares the **environment-owned** terminal durable state against a frozen,
hash-pinned oracle for every scored record, and requires the whole workflow to have been
walked — signed, ordered, all event classes executed, the forced recovery survived, and
cutover completed. Agent-authored prose is never graded.

## Why it is genuinely long-horizon (forced, not elective)

An environment is task-forced only if it **withholds information obtainable solely by
acting** and **feeds each result back to redirect the next action**. Both hold here by
construction:

- **The reduction table is withheld but recoverable from evidence.** Most of the fold is a
  standard prior (dedup, causal ordering, crash/checkpoint failover, delete/recreate,
  status priority-join, tags union). The per-instance `counter`/`head` field-combination
  table departs from that prior and is withheld. The agent reconstructs it from the
  worked `sample.records`, then can **confirm it against the graded stream only after
  deployment** — because a reducer that looks right on the samples can still diverge
  under the concurrent event classes.

- **The only direct correctness feedback after deployment is a lossy, rate-limited bit.** Each
  `qualification.run` (and `migration.status`) returns one **global** `clean`/`dirty`
  status vs legacy — clean iff *every* scored record matches, with no per-record or
  per-partition breakdown and no counts. The check budget is rate-limited per phase, so
  the channel cannot be brute-forced: it confirms a *reasoned* fix, it does not hand back
  the answer.

- **The forced recovery cannot fire until after deploy.** A mid-qualification failure
  drops the episode into `RECOVERY_REQUIRED`; the agent must read the diagnostic and
  apply the matching recovery family before qualification can continue. This is a
  dependency that a single-turn or elective-depth episode cannot collapse.

The result is a genuine chain: **observe → hypothesize → deploy → read the global bit →
localize the error → refine → re-qualify → recover → cut over.** Depth is required, not
optional.

## Difficulty is by construction, and it is fair

Two properties are proven offline (see [`SOUNDNESS.md`](SOUNDNESS.md)):

- **The answer is fully determined by what the agent can observe** — so the task is
  *hard to discover*, not *underspecified*. The reduction table is deductively pinned by
  the worked samples (every used cell is exercised by a covering sample). The one global
  parameter that the samples do not always exercise — the head-selector tie-break — is
  pinned by the **operational** channel instead: deploying the wrong selector qualifies
  `dirty`, so it is discovered by acting and then corrected. Nothing is left to a guess.

- **The naive prior is not enough.** A last-write-wins / whole-record reducer passes the
  public test and fails the hidden qualification on every instance (two-condition control
  64/64). The reduction table is a per-instance, high-entropy secret (94.1 bits,
  non-enumerable), so it cannot be guessed or brute-forced through the rate-limited
  channel.

## The capability signal

Grading is graded, ordered, and all-or-nothing on the substance, with partial credit for
operational competence:

- `strict_pass = 1.0` requires the terminal to match the oracle for **every** record
  **and** the full workflow to have been walked correctly.
- Partial reward credits the operational spine (gates signed and ordered, all event
  classes executed, forced recovery survived, integrity/regression/cutover) even when the
  reduction table was not fully recovered.

Frontier models run through a process-isolated evaluation harness (leak-free, 80-step
budget) illustrate the separation cleanly. **Grok-4.5 scores strict 0/6**, receiving 0.40
on every seed after completing the workflow but recovering none of the reduction table.
**Opus-5 scores strict 1/6**, recovering the withheld semantics once while reproducing
the same workflow-only 0.40 outcome on the other five seeds. A **gold reducer scores 1.0
on every seed**, separating the observed discovery failure from grader failure. The
environment therefore isolates a specific capability: recovering hidden concurrency
semantics from evidence under an irreducible operational horizon.

## Reproduce

```
python3 migration_lh_v2_env.py          # gold grades 1.0, stub floors, isolation report
python3 -m private.selfcheck            # soundness core -> ALL GREEN
python3 -m private.served_selfcheck     # served lifecycle -> ALL GREEN
```
