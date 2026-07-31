"""migration-lh reference reducer: per-instance high-entropy field-combination (the hidden legacy semantics).

This module is NOT shipped in the served image and NOT imported by any serve module
It holds the secret rule family:

  * a PUBLIC feature schema phi(w) -> one of K=36 cells, from observable attributes,
  * a PER-INSTANCE secret table theta over those cells (>= 2^90 entropy),
  * the reducer that applies theta to fold the event stream into the durable terminal.

The taught scaffolding (dedup, failover/checkpoint, causal order, delete/recreate,
status priority-join, tags union) is fixed across instances and carries NO secret; only
`counter` and `head` are governed by theta. See docs/SEMANTICS.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from .dataplane_core import canonical_json, digest, term_hash, default_value  # serve-safe helpers

# ---- public feature schema (documented; the agent knows this) ---------------
OPS = ("CREATE", "UPDATE", "RECREATE")          # DELETE is a tombstone, not a theta-cell
STATUS_ROLES = ("NONE", "ACT", "FAIL")          # field_ops.status: absent / non-FAILED / FAILED
EPOCH_CLASS = ("CUR", "SUP")                     # writer lease at current epoch vs superseded
ORDINAL = ("FIRST", "REST")                      # first kept write of the record vs the rest
K = len(OPS) * len(STATUS_ROLES) * len(EPOCH_CLASS) * len(ORDINAL)   # 36

# counter fold modes (per cell)
ADD, SUB, ZERO = 0, 1, 2
COUNTER_MODES = (ADD, SUB, ZERO)


def cell_index(op: str, srole: str, eclass: str, ordinal: str) -> int:
    return ((OPS.index(op) * len(STATUS_ROLES) + STATUS_ROLES.index(srole)) * len(EPOCH_CLASS)
            + EPOCH_CLASS.index(eclass)) * len(ORDINAL) + ORDINAL.index(ordinal)


@dataclass(frozen=True)
class Theta:
    """Per-instance secret. counter[cell] in {ADD,SUB,ZERO}; head_elig[cell] bool;
    head_sel in {'FIRST','LAST'}."""
    counter: tuple           # length K, ints in COUNTER_MODES
    head_elig: tuple         # length K, bools
    head_sel: str            # 'FIRST' | 'LAST'

    def to_json(self) -> dict:
        return {"counter": list(self.counter),
                "head_elig": [int(b) for b in self.head_elig],
                "head_sel": self.head_sel}

    @staticmethod
    def from_json(d: dict) -> "Theta":
        return Theta(tuple(int(x) for x in d["counter"]),
                     tuple(bool(x) for x in d["head_elig"]),
                     str(d["head_sel"]))


def draw_theta(rng) -> Theta:
    """Draw a secret table from a seeded random.Random. |Theta| = 3^36 * 2^36 * 2 ~ 2^94."""
    counter = tuple(rng.choice(COUNTER_MODES) for _ in range(K))
    head_elig = tuple(bool(rng.getrandbits(1)) for _ in range(K))
    head_sel = "FIRST" if rng.getrandbits(1) else "LAST"
    return Theta(counter, head_elig, head_sel)


def theta_entropy_bits() -> float:
    import math
    return K * math.log2(len(COUNTER_MODES)) + K * 1.0 + 1.0


# ---- taught scaffolding (fixed semantics across instances; no secret) -------
STATUS_RANK = {"ACTIVE": 1, "PENDING": 2, "SUSPENDED": 3, "FAILED": 4, "ARCHIVED": 5}


def _obs_get(observed: dict, pid: int) -> int:
    if not observed:
        return 0
    if pid in observed:
        return int(observed[pid])
    if str(pid) in observed:
        return int(observed[str(pid)])
    return 0


def _happens_before(a: dict, b: dict) -> bool:
    if _obs_get(b.get("observed") or {}, a["partition_id"]) >= a["local_seq"]:
        return True
    return a["partition_id"] == b["partition_id"] and a["local_seq"] < b["local_seq"]


def _is_kept(m: dict, context: dict) -> bool:
    if m.get("commit_seq") is None:
        return False
    lease = m.get("writer_lease")
    handoff = (context or {}).get("handoff") or {}
    checkpoint = (context or {}).get("checkpoint") or {}
    if lease in handoff and handoff[lease] == "CLEAN":
        if m["local_seq"] > checkpoint.get(lease, 0):
            return False
    return True


def _causal_order(muts: list) -> list:
    def key(m):
        cs = m.get("commit_seq")
        return (cs is None, cs if cs is not None else 1 << 60,
                m.get("partition_id", 0), m.get("local_seq", 0),
                m.get("arrival", 0), m.get("mutation_id", ""))
    remaining = list(muts)
    ordered = []
    while remaining:
        ready = [m for m in remaining if not any(o is not m and _happens_before(o, m) for o in remaining)]
        if not ready:
            ready = list(remaining)
        ready.sort(key=key)
        ordered.append(ready[0])
        remaining.remove(ready[0])
    return ordered


def _epoch_class(lease: str, context: dict) -> str:
    eol = (context or {}).get("epoch_of_lease") or {}
    if not eol:
        return "CUR"
    cur = max(eol.values())
    return "CUR" if eol.get(lease, -1) == cur else "SUP"


def _status_role(fo: dict) -> str:
    s = fo.get("status")
    if s is None:
        return "NONE"
    return "FAIL" if s == "FAILED" else "ACT"


# ---- the reducer: applies theta ---------------------------------------------
def reduce_theta(mutations: list, context: dict, theta: Theta) -> dict:
    context = context or {}
    by_rec: dict = {}
    for m in mutations:
        by_rec.setdefault(m["record_id"], []).append(m)

    out = {}
    for rid, muts in by_rec.items():
        # dedup by mutation_id (first arrival), then failover filter
        seen, deduped = set(), []
        for m in sorted(muts, key=lambda x: (x.get("arrival", 0), x.get("commit_seq") or -1)):
            mid = m.get("mutation_id")
            if mid in seen:
                continue
            seen.add(mid)
            deduped.append(m)
        kept = [m for m in deduped if _is_kept(m, context)]
        if not kept:
            continue
        ordered = _causal_order(kept)

        counter = 0
        status = "ACTIVE"
        tags: list = []
        is_deleted = False
        first_seen = False
        head_candidates = []  # (position, head_value)

        for pos, m in enumerate(ordered):
            op = m.get("operation") or "UPDATE"
            fo = m.get("field_ops") or {}
            if op == "DELETE":
                is_deleted = True
                continue
            if op in ("CREATE", "RECREATE"):
                is_deleted = False

            ordinal = "FIRST" if not first_seen else "REST"
            first_seen = True
            cell = cell_index(op if op in OPS else "UPDATE",
                              _status_role(fo), _epoch_class(m.get("writer_lease"), context), ordinal)

            # taught: status priority-join + tags union
            if "status" in fo:
                if STATUS_RANK.get(fo["status"], 0) >= STATUS_RANK.get(status, 0):
                    status = fo["status"]
            if "tags_add" in fo:
                for t in fo["tags_add"]:
                    if t not in tags:
                        tags.append(t)

            # secret: counter fold governed by theta
            if "counter" in fo:
                mode = theta.counter[cell]
                d = int(fo["counter"])
                if mode == ADD:
                    counter += d
                elif mode == SUB:
                    counter -= d
                # ZERO: no contribution

            # secret: head eligibility governed by theta
            if "head" in fo and fo["head"] is not None and theta.head_elig[cell]:
                head_candidates.append((pos, fo["head"]))

        head = None
        if head_candidates:
            head_candidates.sort(key=lambda x: x[0])
            head = head_candidates[0][1] if theta.head_sel == "FIRST" else head_candidates[-1][1]

        out[rid] = {"record_id": rid, "is_deleted": is_deleted,
                    "value": {"counter": counter, "status": status,
                              "tags": sorted(tags), "head": head}}
    return out


def graded_terminal(reduced: dict) -> dict:
    """Normalise to the graded snapshot shape (adds value_digest; env owns bookkeeping)."""
    out = {}
    for rid, snap in reduced.items():
        v = snap["value"]
        dele = bool(snap.get("is_deleted"))
        out[str(rid)] = {"record_id": snap.get("record_id", rid), "is_deleted": dele,
                         "value": v, "value_digest": None if dele or v is None else digest(v)}
    return out
