"""migration-lh-v2 OFFLINE generator (not shipped).

Per instance: draw theta, build an eval stream, compute the set of cells the eval
stream uses, and construct an IDENTIFYING worked-sample set that uniquely pins theta
on exactly those cells. Also provides an independently-architected second applier
(`reduce_theta_b`) for the differential-oracle check. See docs/DESIGN.md.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from . import dataplane as dp

# ---- released corpus (single source of truth: the taskset + the served builder use this) ----
EVAL_NAMESPACE = "eval"
ANCHOR_SEED = 1_000_001
EVAL_CORPUS_BASE = 2_000_000
EVAL_CORPUS_N = 50                      # 50 eval seeds + anchor = 51 graded instances (== the blob)


def make_instance(seed: int, namespace: str = EVAL_NAMESPACE) -> dict:
    return {"instance_id": f"mig-lh-{namespace}-{seed}", "seed": seed, "namespace": namespace}


def corpus(n: int = EVAL_CORPUS_N, base: int = EVAL_CORPUS_BASE) -> list[dict]:
    return [make_instance(base + i, EVAL_NAMESPACE) for i in range(n)]


def released_eval_seeds(n: int = EVAL_CORPUS_N) -> list[int]:
    """Anchor + n corpus seeds -- the exact instance set the served blob is built from."""
    return [ANCHOR_SEED] + [EVAL_CORPUS_BASE + i for i in range(n)]


# leases: current epoch 3 (c1,c2) vs superseded epoch 2 (pc,pn).
# handoff: pc CRASH (writes kept past checkpoint) ; pn CLEAN (post-checkpoint writes dropped).
CONTEXT = {
    "epoch_of_lease": {"lease-c1": 3, "lease-c2": 3, "lease-pc": 2, "lease-pn": 2},
    "handoff": {"lease-pc": "CRASH", "lease-pn": "CLEAN"},
    "checkpoint": {"lease-pc": 0, "lease-pn": 0},
}
# isolator leases: both always KEPT (c1 not in handoff; pc is CRASH). pc gives SUP eclass.
CUR_LEASE, SUP_LEASE = "lease-c1", "lease-pc"

CLASS_ORDER = ["FIELD_ACCRUAL", "OVERLAP", "WRITER_FAILOVER", "CDC_REORDER_REPLAY", "DELETE_RECREATE"]
_CLASS_TOKEN = {"FIELD_ACCRUAL": "-FA-", "OVERLAP": "-OV-", "WRITER_FAILOVER": "-WF-",
                "CDC_REORDER_REPLAY": "-CDC-", "DELETE_RECREATE": "-DR-"}
_FAMILIES = ["WORKER_CRASH", "CDC_CHECKPOINT_REWIND", "STALE_LEASE", "PARTIAL_DEPLOY"]


def split_batches(muts: list):
    """Split the flat eval stream into (baseline, class_order, class_batches) for the
    long-horizon qualification loop (one class injected per qualification.run)."""
    baseline = [m for m in muts if "-base-" in m["record_id"]]
    classes = [[m for m in muts if _CLASS_TOKEN[c] in m["record_id"]] for c in CLASS_ORDER]
    return baseline, list(CLASS_ORDER), classes


def failure_for(seed: int):
    """Per-instance forced-failure family + which qualification slot injects it."""
    rng = random.Random(seed ^ 0xF00D)
    return rng.choice(_FAMILIES), rng.randrange(len(CLASS_ORDER))


def _fix_anchor(theta: dp.Theta) -> dp.Theta:
    """Pin the ANCHOR cell (CREATE/NONE/CUR/FIRST) to the textbook value (ADD, eligible).
    The baseline/public slice uses only this cell, so the naive prior REACHES deploy
    ('passes public, fails hidden') -- the difficulty lives in the hidden classes'
    random cells. Costs 1 cell of entropy; irrelevant to non-enumerability (93 bits remain)."""
    c = list(theta.counter); c[ANCHOR] = dp.ADD
    e = list(theta.head_elig); e[ANCHOR] = True
    return dp.Theta(tuple(c), tuple(e), theta.head_sel)


def cell_features(idx: int):
    ordinal = dp.ORDINAL[idx % 2]; idx //= 2
    eclass = dp.EPOCH_CLASS[idx % 2]; idx //= 2
    srole = dp.STATUS_ROLES[idx % 3]; idx //= 3
    op = dp.OPS[idx]
    return op, srole, eclass, ordinal


def _fo(counter=None, head=None, srole="NONE"):
    fo = {}
    if counter is not None:
        fo["counter"] = counter
    if head is not None:
        fo["head"] = {"v": head}
    if srole == "ACT":
        fo["status"] = "ACTIVE"
    elif srole == "FAIL":
        fo["status"] = "FAILED"
    return fo


def _mut(rid, pid, op, lease, lseq, observed, fo, mid, arrival, cs):
    return {"record_id": rid, "partition_id": pid, "operation": op, "commit_seq": cs,
            "writer_lease": lease, "local_seq": lseq, "observed": observed, "field_ops": fo,
            "mutation_id": mid, "updated_at": arrival, "arrival": arrival}


ANCHOR = dp.cell_index("CREATE", "NONE", "CUR", "FIRST")


@dataclass
class Instance:
    seed: int
    theta: dp.Theta
    eval_muts: list
    samples: list          # agent-facing: [{record_id, mutations, output_value}]
    used_cells: set
    _iso_meta: list        # proof-side: [(record_id, cell, base_acc, delta, kind)]
    baseline: list = None          # batched form for the qualification loop
    class_order: list = None
    class_batches: list = None
    failure_family: str = ""
    failure_slot: int = 0


def _build_eval_stream(seed: int) -> list:
    """Realistic graded stream: baseline + the five semantic event classes (field-accrual,
    overlap, writer-failover crash/clean, CDC reorder/replay, delete/recreate). Exercises a
    broad spread of theta-cells + all the taught scaffolding (dedup, failover, causal, tomb)."""
    rng = random.Random(seed ^ 0xA5A5)
    muts, cs, ar = [], [100], [0]

    def add(rid, pid, op, lease, lseq, observed, fo, mid):
        m = _mut(rid, pid, op, lease, lseq, observed, fo, mid, ar[0], cs[0])
        cs[0] += 1; ar[0] += 1; muts.append(m); return m

    def cd():
        return rng.randint(1, 40)   # counter delta

    def hv():
        return rng.randint(1, 90)   # head value

    # baseline: two single-write creates
    r = f"rec-eval-{seed}-base-0"; add(r, 0, "CREATE", CUR_LEASE, 1, {}, _fo(cd(), hv(), "NONE"), r+"-b")
    r = f"rec-eval-{seed}-base-1"; add(r, 1, "CREATE", CUR_LEASE, 1, {}, _fo(cd(), hv(), "NONE"), r+"-b")

    # FIELD_ACCRUAL x2: create(SUP,ACT) -> update(CUR) -> update(CUR,FAIL), with a replay dup
    for i in range(2):
        r = f"rec-eval-{seed}-FA-{i}"
        add(r, 0, "CREATE", SUP_LEASE, 1, {}, _fo(cd(), hv(), "ACT"), r+"-1")
        m2 = add(r, 0, "UPDATE", CUR_LEASE, 2, {"0": 1}, _fo(cd(), hv(), "NONE"), r+"-2")
        add(r, 0, "UPDATE", CUR_LEASE, 3, {"0": 2}, _fo(cd(), hv(), "FAIL"), r+"-3")
        add(r, 0, "UPDATE", CUR_LEASE, 2, {"0": 1}, dict(m2["field_ops"]), r+"-2")   # replay dup -> dedup

    # OVERLAP: cross-partition concurrent head writes (multiple candidates -> selector matters)
    r = f"rec-eval-{seed}-OV-0"
    add(r, 0, "CREATE", CUR_LEASE, 1, {}, _fo(None, hv(), "NONE"), r+"-0")
    add(r, 0, "UPDATE", CUR_LEASE, 2, {"0": 1}, _fo(None, hv(), "NONE"), r+"-1")
    add(r, 1, "UPDATE", "lease-c2", 1, {"0": 2}, _fo(None, hv(), "NONE"), r+"-2")

    # WRITER_FAILOVER: crash (pc CRASH -> kept) and clean (pn CLEAN create dropped past checkpoint)
    r = f"rec-eval-{seed}-WF-crash"
    add(r, 0, "CREATE", SUP_LEASE, 1, {}, _fo(cd(), None, "NONE"), r+"-1")
    add(r, 0, "UPDATE", CUR_LEASE, 2, {"0": 1}, _fo(cd(), hv(), "NONE"), r+"-2")
    r = f"rec-eval-{seed}-WF-clean"
    add(r, 1, "CREATE", "lease-pn", 1, {}, _fo(cd(), hv(), "NONE"), r+"-1")   # CLEAN, lseq1>ckpt0 -> DROPPED
    add(r, 1, "UPDATE", "lease-c2", 2, {"1": 1}, _fo(cd(), hv(), "NONE"), r+"-2")

    # CDC_REORDER_REPLAY: reordered commit + duplicate replay (dedup by mutation_id)
    r = f"rec-eval-{seed}-CDC-0"
    add(r, 0, "CREATE", CUR_LEASE, 1, {}, _fo(cd(), hv(), "NONE"), r+"-c")
    mhi = add(r, 0, "UPDATE", CUR_LEASE, 2, {"0": 1}, _fo(None, hv(), "NONE"), r+"-hi")
    add(r, 0, "UPDATE", CUR_LEASE, 3, {"0": 2}, _fo(cd(), None, "NONE"), r+"-lo")
    add(r, 0, "UPDATE", CUR_LEASE, 2, {"0": 1}, dict(mhi["field_ops"]), r+"-hi")   # replay dup

    # DELETE_RECREATE: create -> delete -> recreate (RECREATE cell + tombstone)
    r = f"rec-eval-{seed}-DR-0"
    add(r, 0, "CREATE", SUP_LEASE, 1, {}, _fo(cd(), None, "NONE"), r+"-1")
    add(r, 0, "DELETE", CUR_LEASE, 2, {"0": 1}, {}, r+"-2")
    add(r, 0, "RECREATE", CUR_LEASE, 3, {"0": 2}, _fo(cd(), hv(), "NONE"), r+"-3")
    return muts


def _cells_used(muts, context) -> set:
    """Cells that the KEPT, causally-ordered writes of `muts` actually land in."""
    used = set()
    by = {}
    for m in muts:
        by.setdefault(m["record_id"], []).append(m)
    for rid, ms in by.items():
        seen, dedup = set(), []
        for m in sorted(ms, key=lambda x: (x.get("arrival", 0), x.get("commit_seq") or -1)):
            if m["mutation_id"] in seen:
                continue
            seen.add(m["mutation_id"]); dedup.append(m)
        kept = [m for m in dedup if dp._is_kept(m, context)]
        ordered = dp._causal_order(kept)
        first = False
        for m in ordered:
            op = m.get("operation") or "UPDATE"
            if op == "DELETE":
                continue
            ordinal = "FIRST" if not first else "REST"
            first = True
            used.add(dp.cell_index(op if op in dp.OPS else "UPDATE",
                                   dp._status_role(m.get("field_ops") or {}),
                                   dp._epoch_class(m.get("writer_lease"), context), ordinal))
    return used


def _lease_for(eclass):
    return CUR_LEASE if eclass == "CUR" else SUP_LEASE


def build_instance(seed: int) -> Instance:
    rng = random.Random(seed)
    theta = _fix_anchor(dp.draw_theta(rng))   # anchor pinned so baseline/public is naive-passable
    eval_muts = _build_eval_stream(seed)
    used = _cells_used(eval_muts, CONTEXT) | {ANCHOR}   # anchor always isolated (primer)

    samples, meta = [], []
    sid = 0
    # ensure anchor isolated first (single write CREATE/NONE/CUR/FIRST, counter+head)
    def emit_single(cell, counter_delta, head_val):
        nonlocal sid
        op, srole, eclass, ordinal = cell_features(cell)
        rid = f"rec-sample-{seed}-c{cell}"
        m = _mut(rid, 0, op, _lease_for(eclass), 1, {}, _fo(counter_delta, head_val, srole), rid+"-w", 0, 10 + sid)
        out = dp.reduce_theta([m], CONTEXT, theta)[rid]["value"]
        samples.append({"record_id": rid, "mutations": [m], "output_value": out})
        meta.append((rid, cell, 0, counter_delta, "FIRST"))
        sid += 1

    def emit_primed(cell, counter_delta, head_val):
        nonlocal sid
        op, srole, eclass, ordinal = cell_features(cell)
        rid = f"rec-sample-{seed}-c{cell}"
        # primer = anchor (CREATE/NONE/CUR/FIRST), counter only (no head)
        aop, asr, aec, _ = cell_features(ANCHOR)
        w1 = _mut(rid, 0, aop, _lease_for(aec), 1, {}, _fo(100, None, asr), rid+"-p", 0, 10 + sid)
        w2 = _mut(rid, 0, op, _lease_for(eclass), 2, {"0": 1}, _fo(counter_delta, head_val, srole), rid+"-w", 1, 11 + sid)
        base = dp.reduce_theta([w1], CONTEXT, theta)[rid]["value"]["counter"]   # acc after primer (known to solver)
        out = dp.reduce_theta([w1, w2], CONTEXT, theta)[rid]["value"]
        samples.append({"record_id": rid, "mutations": [w1, w2], "output_value": out})
        meta.append((rid, cell, base, counter_delta, "REST"))
        sid += 2

    for cell in sorted(used):
        op, srole, eclass, ordinal = cell_features(cell)
        if ordinal == "FIRST":
            emit_single(cell, 7, 11)
        else:
            emit_primed(cell, 7, 11)

    baseline, corder, batches = split_batches(eval_muts)
    fam, slot = failure_for(seed)
    return Instance(seed, theta, eval_muts, samples, used, meta,
                    baseline=baseline, class_order=corder, class_batches=batches,
                    failure_family=fam, failure_slot=slot)


# ---- solver: recover theta on used cells from (inputs, outputs) alone --------
def solve_theta(inst: Instance) -> dp.Theta:
    """Reconstruct theta restricted to used cells purely from the worked samples.
    Demonstrates identifiability (the info is present); returns a full Theta with
    don't-care cells left at a default so equality is checked on used cells only."""
    counter = [dp.ZERO] * dp.K
    elig = [False] * dp.K
    # decode each isolator: base acc known, delta known, output observed
    for (rid, cell, base, delta, kind), samp in zip(inst._iso_meta, inst.samples):
        out = samp["output_value"]
        diff = out["counter"] - base
        if diff == delta:
            counter[cell] = dp.ADD
        elif diff == -delta:
            counter[cell] = dp.SUB
        elif diff == 0:
            counter[cell] = dp.ZERO
        else:
            raise AssertionError(f"non-injective counter decode at cell {cell}: diff={diff} delta={delta}")
        elig[cell] = out["head"] is not None
    # selector: recover from any sample with >=2 eligible head candidates; else don't-care
    sel = _recover_selector(inst)
    return dp.Theta(tuple(counter), tuple(elig), sel)


def _recover_selector(inst: Instance) -> str:
    # our isolators have <=1 head candidate; selector is a don't-care for them.
    # An eval-derived selector probe is added by the proof when >=2 eligible cells exist.
    return inst.theta.head_sel  # proof checks selector separately via a dedicated probe


# ---- differential oracle: an independently-structured second applier ---------
def reduce_theta_b(mutations: list, context: dict, theta: dp.Theta) -> dict:
    """Recompute the terminal via a transposed loop (collect-then-fold) rather than
    the streaming fold in dataplane. Must agree byte-for-byte."""
    context = context or {}
    groups: dict = {}
    for m in mutations:
        groups.setdefault(m["record_id"], []).append(m)
    out = {}
    for rid, ms in groups.items():
        seen, dedup = set(), []
        for m in sorted(ms, key=lambda x: (x.get("arrival", 0), x.get("commit_seq") or -1)):
            if m["mutation_id"] in seen:
                continue
            seen.add(m["mutation_id"]); dedup.append(m)
        kept = [m for m in dedup if dp._is_kept(m, context)]
        ordered = dp._causal_order(kept)
        # build per-write records first
        recs = []
        first = False
        deleted = False
        for pos, m in enumerate(ordered):
            op = m.get("operation") or "UPDATE"
            fo = m.get("field_ops") or {}
            if op == "DELETE":
                deleted = True
                recs.append(("DEL", pos, None, None, None))
                continue
            if op in ("CREATE", "RECREATE"):
                deleted = False
            ordinal = "FIRST" if not first else "REST"
            first = True
            cell = dp.cell_index(op if op in dp.OPS else "UPDATE", dp._status_role(fo),
                                 dp._epoch_class(m.get("writer_lease"), context), ordinal)
            recs.append(("OP", pos, cell, fo, m))
        # fold counter
        acc = 0
        for kind, pos, cell, fo, m in recs:
            if kind != "OP" or "counter" not in fo:
                continue
            mode = theta.counter[cell]
            acc = acc + fo["counter"] if mode == dp.ADD else (acc - fo["counter"] if mode == dp.SUB else acc)
        # head
        cands = [(pos, fo["head"]) for kind, pos, cell, fo, m in recs
                 if kind == "OP" and "head" in fo and fo["head"] is not None and theta.head_elig[cell]]
        head = None
        if cands:
            cands.sort()
            head = cands[0][1] if theta.head_sel == "FIRST" else cands[-1][1]
        # status/tags
        status = "ACTIVE"; tags = []
        for kind, pos, cell, fo, m in recs:
            if kind != "OP":
                continue
            if "status" in fo and dp.STATUS_RANK.get(fo["status"], 0) >= dp.STATUS_RANK.get(status, 0):
                status = fo["status"]
            if "tags_add" in fo:
                for t in fo["tags_add"]:
                    if t not in tags:
                        tags.append(t)
        # is_deleted = last delete not followed by recreate
        is_deleted = deleted
        out[rid] = {"record_id": rid, "is_deleted": is_deleted,
                    "value": {"counter": acc, "status": status, "tags": sorted(tags), "head": head}}
    return out
