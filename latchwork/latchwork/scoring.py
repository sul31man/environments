"""Stratified differential battery and the scored deliverable.

The deliverable is a RECONSTRUCTED pipeline (a list of value-keys).  It is graded
by behavioral agreement with the true pipeline over a depth-stratified battery of
held-out assignments -- NOT by "does the channel accept" (which is why
probe-then-hardcode-an-acceptor earns nothing).

Stratification: an assignment's stratum is its TRUE first-failing index (1..L) or
ACCEPT.  Deep strata are unreachable by random sampling (the pass-region is tiny
-- the masking that makes discovery forced), so we build them CONSTRUCTIVELY by
local perturbation of the hidden witness.  Strata are equal-weighted, so every
stage carries >~1/(L+1) of the score and a single wrong stage cannot stay >=0.95
(load-bearing; verified empirically by the ablation gate).

Grading consumes only value-keys (Evaluator B), never agent objects.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, List, Tuple

from .dsl import ACCEPT, Pipeline
from .evaluator_b import observe_from_keys


def build_battery(instance, n_per_stratum: int = 24, max_tries: int = 200000):
    """List of (assignment, true_obs, stratum).

    Fills each depth bucket to n_per_stratum by perturbing the witness (few
    fields at a time -> reaches deep strata) plus uniform random (fills shallow).
    Deterministic in the instance.
    """
    pipe: Pipeline = instance.pipeline
    n, M = pipe.n_fields, pipe.domain
    w = instance.witness
    rng = random.Random(
        int.from_bytes(
            __import__("hashlib").sha256(
                f"battery|{instance.namespace}|{instance.seed}".encode()
            ).digest()[:8],
            "big",
        )
    )

    target_strata = list(range(1, pipe.L + 1)) + [ACCEPT]
    buckets: Dict[int, List] = defaultdict(list)

    def obs_stratum(a):
        idx, cls = pipe.observe(a)
        return (idx, cls), idx

    # --- guided fill: construct "fails-first-at-k" assignments (oracle-side) ---
    # The battery builder KNOWS the pipeline, so for each stage k we perturb the
    # witness over k's own fields (1- and 2-field changes) searching for
    # assignments whose true first-failure is exactly k.  This reaches deep
    # strata that random sampling cannot (the pass-region is tiny -- the masking).
    for k in range(1, pipe.L + 1):
        stage = pipe.stages[k - 1]
        flds = list(stage.fields())
        # single-field sweeps over each field of stage k
        for f in flds:
            for v in range(M):
                if len(buckets[k]) >= n_per_stratum:
                    break
                a = list(w)
                a[f] = v
                a = tuple(a)
                _, idx = obs_stratum(a)
                if idx == k:
                    buckets[k].append((a, pipe.observe(a), k))
        # a few random 2-field perturbations over k's fields if still short
        attempts = 0
        while len(buckets[k]) < n_per_stratum and attempts < 4000 and len(flds) >= 2:
            attempts += 1
            a = list(w)
            for f in flds:
                a[f] = rng.randrange(M)
            a = tuple(a)
            _, idx = obs_stratum(a)
            if idx == k:
                buckets[k].append((a, pipe.observe(a), k))

    # --- oracle fill: deep strata unreachable by local perturbation ---
    # For any stage still short, use the oracle prefix solver (knows params) to
    # construct assignments that pass 1..k-1 and fail k, then jitter their free
    # fields to diversify.  This guarantees every stage has a populated stratum
    # (=> load-bearing), matching the generation-time reachability guarantee.
    from .oracle import pass_prefix_fail_k
    for k in range(1, pipe.L + 1):
        guard = 0
        while len(buckets[k]) < n_per_stratum and guard < n_per_stratum * 6:
            guard += 1
            base = pass_prefix_fail_k(pipe, k, rng, witness=w, restarts=20, steps=200)
            if base is None:
                break
            buckets[k].append((base, pipe.observe(base), k))
            # jitter fields NOT in stage k to find more members of stratum k
            free = [f for f in range(n) if f not in set(pipe.stages[k - 1].fields())]
            for _ in range(6):
                if len(buckets[k]) >= n_per_stratum:
                    break
                a = list(base)
                for f in rng.sample(free, max(1, len(free) // 3)):
                    a[f] = rng.randrange(M)
                a = tuple(a)
                if pipe.observe(a)[0] == k:
                    buckets[k].append((a, pipe.observe(a), k))

    # --- random fill: shallow strata + ACCEPT ---
    tries = 0
    while tries < max_tries and any(
        len(buckets[s]) < n_per_stratum for s in target_strata
    ):
        tries += 1
        if rng.random() < 0.7:
            # perturbation of witness: flip a few fields (reaches deep/ACCEPT)
            a = list(w)
            k = rng.randint(1, max(1, n // 3))
            for f in rng.sample(range(n), k):
                a[f] = rng.randrange(M)
            a = tuple(a)
        else:
            a = tuple(rng.randrange(M) for _ in range(n))  # uniform: shallow
        obs, idx = obs_stratum(a)
        if len(buckets[idx]) < n_per_stratum:
            buckets[idx].append((a, obs, idx))

    battery = []
    for s in target_strata:
        battery.extend(buckets[s])
    return battery


def stratum_weights(battery) -> Dict[int, float]:
    """Equal weight per OCCUPIED stratum (so depth is not swamped by shallow)."""
    strata = sorted({s for _, _, s in battery})
    w = 1.0 / len(strata)
    return {s: w for s in strata}


def score_keys(keys, battery, n_fields: int, n_groups: int = 4):
    """Weighted behavioral agreement in [0,1] + per-stratum breakdown."""
    weights = stratum_weights(battery)
    by_stratum_hit: Dict[int, int] = defaultdict(int)
    by_stratum_tot: Dict[int, int] = defaultdict(int)
    for a, true_obs, s in battery:
        got = observe_from_keys(keys, a, n_fields, n_groups)
        by_stratum_tot[s] += 1
        if got == true_obs:
            by_stratum_hit[s] += 1
    total = 0.0
    breakdown = {}
    for s in by_stratum_tot:
        frac = by_stratum_hit[s] / by_stratum_tot[s]
        breakdown[s] = frac
        total += weights[s] * frac
    return total, breakdown
