# migration-lh-v2 — design

## Components

```
migration_lh_v2_env.py   framework-agnostic adapter (the only integration surface)
mig_lh/
  contract.py            the frozen contract: states, transitions, tools, gates, scores
  control_plane.py       the live state machine: version guard, event injection, feedback
  dataplane.py           the reference reduction (the theta table) + the naive prior
  dataplane_core.py      serve-safe hashing + record shapes (NO reducer logic)
  candidate.py           out-of-process runtime for the agent's migrate.py
  verifier.py            strict_pass grading vs the frozen served terminal
  generator.py           per-seed instances, feasibility, and a 2nd independent derivation
  served_data.py         loader for the data-only served payload
  receipts.py            hash-chained, HMAC-signed, append-only receipt log
served/served_data.json  the frozen, hash-pinned served payload (data only)
```

## The operational spine (state machine)

Each episode is a fixed, ordered workflow. The control plane enforces legal transitions
with an optimistic-concurrency `state_version` token (a stale token is rejected):

```
DEGRADED_CANARY
  → incident.replay          → INCIDENT_CONFIRMED         (G1)
  → routing.pause_target     → SAFE_LEGACY_PENDING        (G2)
  → generation.resolve       → SAFE_LEGACY                (G3)
  → tests.run_public         → PATCH_READY                (public suite vs workspace migrate.py)
  → candidate.deploy         → CANDIDATE_CANARY           (G4: bind workspace reducer)
  → qualification.run × N    → (each injected event class under canary)   (G5)
       ↳ on injected failure → RECOVERY_REQUIRED
            → diagnostics.read; recovery.apply(matching family)  (G6: guessing rejected)
  → audit.forward            → CANARY_QUALIFIED           (G7)
  → repair.run               → RECONCILED                 (G8)
  → barrier.verify           → (per-partition barriers)   (G9)
  → regression.run           → CUTOVER_READY              (G9)
  → routing.promote_target   → COMPLETED                  (G10)
  → submit.final             → TERMINAL                   (freeze + grade)
```

The five injected event classes — field-accrual, overlap, writer-failover, CDC
reorder/replay, delete/recreate — must all execute. Exactly one instance-specific class
trips a **forced recovery** (one of `WORKER_CRASH`, `CDC_CHECKPOINT_REWIND`, `STALE_LEASE`,
`PARTIAL_DEPLOY`); the agent must read the diagnostic symptom and apply the matching
family before qualification can continue.

## The tool surface

20 typed tools, split into **observation** (free, no state change: `repo.read`,
`schema.describe`, `migration.status`, `lineage.inspect`, `sample.records`,
`diagnostics.read`) and **state-changing** (advance the workflow; require the current
`state_version`). The key observation channels for recovering the semantics:

- **`sample.records`** — worked examples (records *not* in the graded set) with the full
  mutation stream, field values, the durable output each produced, and the deploy
  context. These deductively determine the instance's reduction table.
- **`lineage.inspect`** — per-write provenance for the graded records with values
  redacted: partition, local_seq, opaque `writer_lease`, operation, and the `observed[]`
  cross-partition happens-before watermark (the ordering signal).
- **`migration.status`** — after deploy, one **global** `clean`/`dirty` bit vs legacy,
  rate-limited per phase.

## The generator

`generator.py` builds each instance deterministically from a seed: it draws the
per-instance reduction table (`theta`), constructs an event stream that exercises the
five classes, chooses the forced-recovery class, and emits the worked samples. Two
guarantees are enforced at build time:

- **Feasibility** — a correct reducer using the drawn table strict-passes (the instance
  is solvable).
- **Identifiability** — the worked samples exercise every cell the graded terminal
  depends on, so the table is recoverable from what the agent sees (see
  [`SOUNDNESS.md`](SOUNDNESS.md)).

The generator also carries a second, independently structured derivation of the
reduction (`reduce_theta_b`) used as a differential oracle.

## Grading

Grading is **by value on data**, never by running agent code inside the grader:

- At `submit.final`, the control plane has the environment-owned terminal durable state
  (produced by running the agent's deployed reducer *out-of-process* over the injected
  stream). The verifier compares it against the frozen, hash-pinned served terminal for
  every scored record.
- `strict_pass` (`S1..S5`) requires: **S1** every scored record matches; **S2** the gate
  receipts are signed and correctly ordered; **S3** all event classes executed; **S4**
  the forced recovery was survived; **S5** integrity, regression, and cutover completed.
- Partial reward (`< 1.0`) credits the operational spine (S2–S5) even when the reduction
  table (S1) was not fully recovered.

See [`ISOLATION.md`](ISOLATION.md) for why the serving process holds no reducer logic and
no plaintext answer, and how out-of-process grading keeps the oracle off the
agent-reachable surface.
