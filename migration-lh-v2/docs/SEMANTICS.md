# migration-lh-v2 — semantics

The normative contract of the reduction. The reference implementation is
`mig_lh/dataplane.py`; this document is the human-readable specification of what a
correct `reduce(mutations, context)` must compute.

## I/O

```
reduce(mutations: list[dict], context: dict) -> {record_id: snapshot}
```

Each **mutation** is one delivered write:

| field | meaning |
|---|---|
| `record_id` | the record it targets |
| `partition_id`, `local_seq` | source partition and per-partition sequence |
| `operation` | `CREATE` \| `UPDATE` \| `DELETE` \| `RECREATE` |
| `writer_lease` | opaque lease id of the writer that produced it |
| `observed` | `{partition_id: local_seq}` cross-partition happens-before watermark this write had seen |
| `field_ops` | the field deltas: `counter` (int), `status` (str), `tags_add` (list), `head` (`{"v": int}`) |
| `commit_seq` | commit order, or `null` if never acknowledged |
| `arrival`, `updated_at` | delivery time; wall-clock (unreliable — a decoy) |
| `mutation_id` | dedup key |

**context** (delivered at deploy): `{epoch_of_lease: {lease: epoch}, handoff: {lease:
"CRASH"|"CLEAN"}, checkpoint: {lease: local_seq}}`.

Each **snapshot** is the durable record: `{is_deleted: bool, value: {counter: int,
status: str, tags: list, head: {"v": int}}}`.

## The taught scaffolding (fixed across instances, carries no secret)

A correct reducer folds each record's writes with these standard rules — all recoverable
from the worked samples, and all *identical* across instances:

1. **Dedup.** Collapse repeated `mutation_id`s.
2. **Kept-set / causal order.** Order the record's writes by the `observed` happens-before
   watermark, breaking ties by `commit_seq`; unacknowledged writes (`commit_seq = null`)
   and writes torn by failover are dropped from the kept set. `updated_at` is **not** an
   ordering key — it is an unreliable wall-clock decoy that a last-write-wins reducer
   follows into the wrong answer.
3. **Crash / checkpoint failover.** Using `context.handoff` and `context.checkpoint`: on a
   **`CLEAN`** handoff, a write whose `local_seq` is above the lease's checkpoint is **torn**
   (not durable); **`CRASH`**-handoff writes survive (when acknowledged). This is the reverse
   of the naive assumption — a reducer that keeps CLEAN and tears CRASH gets it backwards.
   Superseded-epoch writes are handled per the lease's `epoch_of_lease`. *Note:* in the
   current released corpus every CLEAN-handoff write already sits above its checkpoint, so the
   `checkpoint` **threshold is non-discriminating** — a decoy, like `updated_at` — and the
   effective rule reduces to "CLEAN-handoff writes are torn." (The field is retained in the
   contract; a future corpus may exercise the threshold.)
4. **Delete / recreate.** `DELETE` tombstones the record (`is_deleted = true`);
   `RECREATE` starts a fresh durable value.
5. **Status priority-join.** The durable `status` is the highest-priority status among
   kept writes (`ACTIVE < PENDING < SUSPENDED < FAILED < ARCHIVED`).
6. **Tags union.** The durable `tags` is the sorted union of kept `tags_add`.

## The withheld field-combination table (per-instance)

Only two fields depart from the standard prior, and how they combine is governed by a
**per-instance table** drawn from the seed. Across the kept writes of a record:

- **`counter`** — each kept write's `counter` delta accrues under a per-situation mode:
  it may **add**, **subtract**, or be **ignored**, depending on the write's observable
  attributes (its operation, whether its `status` role is normal or failed, whether its
  lease is at the current or a superseded epoch, and whether it is the record's first
  kept write or a later one).
- **`head`** — only some writes are **eligible** to set `head` (again keyed on those
  observable attributes), and among the eligible ones a single global **selector**
  decides whether the **first** or the **last** wins.

This table is a per-instance, high-entropy secret (`> 2^90` configurations,
non-enumerable through the rate-limited feedback channel). It is **not** disclosed in the
prompt. It is recovered from evidence:

- The **reduction table** (which attributes add/subtract/ignore the counter, and which
  are head-eligible) is **deductively pinned by the worked `sample.records`** — the
  samples exercise every situation the graded stream depends on, with full inputs and
  outputs.
- The **head selector** (first vs last) is confirmed **operationally**: deploying the
  wrong selector qualifies `dirty`, so it is discovered by acting on the qualification
  channel and corrected.

The exact feature schema `phi` (the mapping from a write's attributes to a table cell)
and the reference fold are in `mig_lh/dataplane.py`. A correct reducer that recovers the
table reproduces the environment-owned terminal for every scored record; see
[`SOUNDNESS.md`](SOUNDNESS.md) for the identifiability and difficulty guarantees.
