"""Oracle-side reachability solver (KNOWS params -- generator/gate use only).

Used by the battery builder and the identifiability gate to decide, for each
stage k, whether there exists an assignment that PASSES stages 1..k-1 and FAILS
stage k (i.e. whose true first-failure is exactly k -- a non-empty "reachable
stratum" for k).  A stage with no reachable stratum is behaviorally invisible on
the reachable input space -> non-identifiable/not-load-bearing -> the seed is
rejected.

NB: this is oracle-side (it reads params).  The channel-only baseline solvers in
latchwork/solvers/ never import this.
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

from .dsl import Pipeline

_BIG = 1000  # weight on prefix violations vs the "must fail k" objective


def _cost(pipe: Pipeline, a: Tuple[int, ...], k: int) -> int:
    """0 iff a passes stages 1..k-1 and fails stage k."""
    c = 0
    for j in range(k - 1):
        if not pipe.stages[j].holds(a):
            c += _BIG
    if pipe.stages[k - 1].holds(a):  # we WANT stage k to fail
        c += 1
    return c


def _involved_fields(pipe: Pipeline, a, k) -> List[int]:
    """Fields of the currently-'problematic' constraints (min-conflicts focus)."""
    viol_prefix = [j for j in range(k - 1) if not pipe.stages[j].holds(a)]
    if viol_prefix:
        flds = set()
        for j in viol_prefix:
            flds.update(pipe.stages[j].fields())
        return list(flds)
    # prefix ok but k currently satisfied -> perturb k's fields
    return list(pipe.stages[k - 1].fields())


def pass_prefix_fail_k(pipe: Pipeline, k: int, rng: random.Random,
                       witness: Optional[Tuple[int, ...]] = None,
                       restarts: int = 40, steps: int = 300) -> Optional[Tuple[int, ...]]:
    """Min-conflicts search for an assignment with true first-failure == k.
    Returns the assignment, or None if not found within budget."""
    n, M = pipe.n_fields, pipe.domain
    starts = []
    if witness is not None:
        starts.append(list(witness))  # well-initialized: prefix already satisfied
    for _ in range(restarts):
        if witness is not None and rng.random() < 0.5:
            a = list(witness)
            for f in rng.sample(range(n), rng.randint(1, max(1, n // 2))):
                a[f] = rng.randrange(M)
            starts.append(a)
        else:
            starts.append([rng.randrange(M) for _ in range(n)])

    for start in starts:
        a = list(start)
        if _cost(pipe, tuple(a), k) == 0:
            return tuple(a)
        for _ in range(steps):
            flds = _involved_fields(pipe, tuple(a), k)
            f = rng.choice(flds)
            best_v, best_c = a[f], _cost(pipe, tuple(a), k)
            order = list(range(M))
            rng.shuffle(order)
            for v in order:
                a[f] = v
                c = _cost(pipe, tuple(a), k)
                if c < best_c:
                    best_c, best_v = c, v
                    if c == 0:
                        break
            a[f] = best_v
            if best_c == 0:
                return tuple(a)
            if rng.random() < 0.15:  # random kick to escape plateaus
                a[rng.randrange(n)] = rng.randrange(M)
    return None


def reachable_strata(pipe: Pipeline, witness, rng: random.Random,
                     restarts: int = 40, steps: int = 300):
    """Dict k -> assignment (or None) for every stage k in 1..L."""
    return {
        k: pass_prefix_fail_k(pipe, k, rng, witness, restarts, steps)
        for k in range(1, pipe.L + 1)
    }
