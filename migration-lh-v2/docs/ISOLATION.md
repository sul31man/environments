# migration-lh-v2 — isolation

The grade must not be reachable by the agent it grades. This environment achieves that by
**grading by value on data**, out of process, from a serving surface that holds no reducer
logic and no plaintext answer.

```
python3 -m private.served_selfcheck     # boot -> grade by value; serving closure holds no reducer
python3 migration_lh_v2_env.py          # isolation_report(): on-disk / importable dimensions
```

## Grade by value, never by running agent code in the grader

At `submit.final`, the environment already holds its **own** terminal durable state — the
state produced by running the agent's deployed reducer **out of process** (an isolated
`-I -S` subprocess, `mig_lh/candidate.py`) over the injected event stream. The verifier
compares that terminal against a frozen, hash-pinned reference for every scored record.

The grader therefore **never imports or executes agent code in its own interpreter**, and
never re-derives the answer at grade time — it compares data. There is no in-process path
from the agent's code to the oracle, because the oracle is not a function the grader calls
on the agent's behalf; it is a precomputed value the grade is checked against.

## The serving surface is data only

What the serving process loads (`served/served_data.json`, via `mig_lh/served_data.py`) is
**precomputed data**: the input event streams, the worked `sample.records`, the deploy
context, and salted **global** hashes used for the `clean`/`dirty` divergence check and the
final grade. It loads:

- **no reducer logic** — `mig_lh/dataplane.py` (the reference reduction) and
  `mig_lh/generator.py` (answer derivation) are not imported by any serving module; the
  serving path imports only `dataplane_core` (hashing and record shapes, no rules);
- **no plaintext answer** — divergence and the grade are salted hash compares, never a
  live legacy fold and never a stored per-record expected value.

`served_selfcheck` confirms the serving closure at runtime: the set of resident reducer
modules is empty (`[]`).

## Two fail-closed boundaries

`assert_isolated()` refuses to serve while the reducer is reachable on **either**
dimension — and stats reality rather than trusting a flag, so a purge that failed silently
(read-only mount, permission error) is still caught:

- **disk** — `oracle_on_disk()` checks the filesystem for the reducer source
  (`dataplane.py`, `generator.py`) and the frozen grade material; the reference serve image
  ships these **absent by construction** (build-time exclusion), and the check fails closed
  if they reappear.
- **import** — `oracle_importable()` uses `importlib.machinery.PathFinder` (not
  `importlib.util.find_spec`, which consults `sys.modules` and would fire on every clean
  boot) to catch a copy that survives a disk purge — for example one dragged into
  site-packages by a non-editable `pip install .`. The packaging is deliberately
  install-free (`packages = []`) so this cannot happen by default.

For a host that ships the full tree (as this review package does, so the design and the
reference reduction can be inspected), `purge_oracle()` performs the serve-time hardening:
load the grade surface into memory, then delete the reducer source and the served payload
from the agent-reachable disk, and assert both boundaries closed.

## What this does and does not claim

- It **does** guarantee the grade is computed by value, out of process, from a serving
  surface with no reducer logic and no plaintext answer, with both disk and import
  boundaries fail-closed.
- It does **not** substitute for host-level process isolation between a co-located agent
  and the serving process. Where the deployment platform provides that isolation, it
  composes with the properties above; where it does not, the disk/import/out-of-process
  guarantees here still hold. Sandbox-level isolation between agent and grader is a
  platform property, layered on top of this environment rather than replacing it.
