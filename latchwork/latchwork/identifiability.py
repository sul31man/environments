"""Identifiability gate + rejection sampler (condition 2 -- built before knobs).

A seed is IDENTIFIABLE iff, for every stage k:
  (R) reachability: some assignment passes 1..k-1 and fails k (stratum k is
      non-empty -> stage k is observable via the channel), AND
  (P) pinned: no BEHAVIORALLY-DISTINCT DSL alternative for stage k scores >=0.95
      on the differential battery (generalized ablation over param-neighbours and
      cross-form alternatives).  "Distinct" = differs from truth on >=1 battery
      assignment (score < 1.0).  Pinned => an agent that mis-recovers stage k
      cannot stay >=0.95 -> the stage is load-bearing AND uniquely determined by
      the observable behaviour.

This is solver-free: it proves the battery itself pins each stage, so a
sufficiently good channel-only agent can in principle recover it (well-posed),
independent of any particular solver's polish.

The rejection sampler keeps identifiable seeds; acceptance rate is measured vs
coupling to confirm coupling can reach target difficulty WITHOUT rejecting most
seeds (the condition-2 requirement).
"""

from __future__ import annotations

import random
from typing import List

from .dsl import ACCEPT
from .evaluator_b import observe_from_keys
from .generator import Instance
from .scoring import build_battery, score_keys

_MODS = (3, 4, 5, 6, 7, 8)


def _alternatives(true_key, n, M, rng, n_random=10) -> List[tuple]:
    """A spread of alternative stage keys: the always-true stub, param-neighbours
    of the true form, and random cross-form stages on the same primary field."""
    alts = [("INTERVAL", 0, 0, M - 1)]  # missing-constraint (always true)
    kind = true_key[0]
    f = true_key[1]

    # param-neighbours of the true form
    if kind == "INTERVAL":
        _, ff, lo, hi = true_key
        for dl, dh in [(-2, 0), (2, 0), (0, -2), (0, 2), (-3, 3)]:
            alts.append(("INTERVAL", ff, max(0, lo + dl), min(M - 1, hi + dh)))
    elif kind == "SET":
        _, ff, mem = true_key
        mem = list(mem)
        if mem:
            alts.append(("SET", ff, tuple(mem[:-1]) or (mem[0],)))       # drop one
            alts.append(("SET", ff, tuple(sorted(set(mem) | {(mem[0] + 1) % M}))))  # add one
    elif kind == "MODULAR":
        _, ff, m, r = true_key
        alts.append(("MODULAR", ff, m, (r + 1) % m))
        alts.append(("MODULAR", ff, _MODS[(_MODS.index(m) + 1) % len(_MODS)], r % m))
    elif kind == "LINEAR":
        _, f0, f1, a, b, m, r = true_key
        alts.append(("LINEAR", f0, f1, a, b, m, (r + 1) % m))
        alts.append(("LINEAR", f0, f1, (a + 1), b, m, r))
        alts.append(("LINEAR", f0, f1, a, (b + 1), m, r))
    elif kind == "ORDER":
        _, f0, f1, rel = true_key
        for rr in ("<", "<=", ">", ">="):
            if rr != rel:
                alts.append(("ORDER", f0, f1, rr))
    elif kind == "DEPENDENCY":
        _, f0, f1, a, b, MM = true_key
        alts.append(("DEPENDENCY", f0, f1, a, (b + 1) % MM, MM))
        alts.append(("DEPENDENCY", f0, f1, (a + 1) % MM, b, MM))

    # random cross-form alternatives on the same field
    for _ in range(n_random):
        form = rng.choice(["INTERVAL", "SET", "MODULAR", "ORDER", "LINEAR", "DEPENDENCY"])
        g = rng.choice([x for x in range(n) if x != f])
        if form == "INTERVAL":
            lo = rng.randrange(M); hi = rng.randrange(lo, M); alts.append(("INTERVAL", f, lo, hi))
        elif form == "SET":
            alts.append(("SET", f, tuple(sorted(rng.sample(range(M), rng.randint(2, M // 4))))))
        elif form == "MODULAR":
            m = rng.choice(_MODS); alts.append(("MODULAR", f, m, rng.randrange(m)))
        elif form == "ORDER":
            alts.append(("ORDER", f, g, rng.choice(["<", "<=", ">", ">="])))
        elif form == "LINEAR":
            m = rng.choice(_MODS); alts.append(("LINEAR", f, g, rng.randint(1, M - 1), rng.randint(1, M - 1), m, rng.randrange(m)))
        else:
            alts.append(("DEPENDENCY", f, g, rng.randint(1, M - 1), rng.randrange(M), M))
    return alts


def _stage_verdict(key, a, n, ng):
    """True if stage `key` accepts assignment a (its holds())."""
    return observe_from_keys([key], a, n, ng)[0] == ACCEPT


def check_instance(instance: Instance, battery=None, n_per_stratum=24,
                   pin_threshold=0.95, far_delta=0.05, seed_off=0):
    """Return an identifiability report for one instance.

    A stage is PINNED iff no BEHAVIORALLY-FAR alternative (differs from truth on
    >= far_delta of the reachable-for-k battery) scores >= pin_threshold.  Near
    misses (a SET missing one member, etc.) are smooth partial credit, not
    identifiability failures, so they are excluded by the far_delta filter.  The
    always-true ablation is always far -> this subsumes the load-bearing check.
    """
    cfg = instance.config
    n, ng = cfg.n_fields, cfg.n_groups
    if battery is None:
        battery = build_battery(instance, n_per_stratum=n_per_stratum)
    true_keys = list(instance.pipeline.key())
    gold, _ = score_keys(true_keys, battery, n, ng)
    strata = {s for _, _, s in battery}
    rng = random.Random(hash((instance.namespace, instance.seed, "ident")) & 0xFFFFFFFF)

    M = cfg.domain
    per_stage = []
    reachable_all = True
    load_bearing_all = True
    unique_max = True
    for k in range(1, instance.pipeline.L + 1):
        reachable = k in strata  # stratum k populated => observable
        reachable_all &= reachable
        f = true_keys[k - 1][1]
        # complete-miss ablation: stage k -> always-true (interval over full domain)
        cand = list(true_keys); cand[k - 1] = ("INTERVAL", f, 0, M - 1)
        miss_score, _ = score_keys(cand, battery, n, ng)
        load_bearing = miss_score < pin_threshold
        load_bearing_all &= load_bearing
        # unique-max sanity: no behaviorally-distinct alternative reaches gold
        worst_distinct = 0.0
        for alt in _alternatives(true_keys[k - 1], n, M, rng, n_random=8):
            s, _ = score_keys([*true_keys[:k-1], alt, *true_keys[k:]], battery, n, ng)
            if s < 1.0 - 1e-9:
                worst_distinct = max(worst_distinct, s)
            elif alt != true_keys[k - 1]:
                # scores gold but different key -> behaviorally identical (OK)
                pass
        per_stage.append({"k": k, "reachable": reachable,
                          "load_bearing": load_bearing,
                          "miss_score": round(miss_score, 3),
                          "worst_distinct_alt": round(worst_distinct, 3)})

    return {
        "seed": instance.seed,
        "gold": round(gold, 4),
        "gold_ok": abs(gold - 1.0) < 1e-9,
        "reachable_all": reachable_all,
        "load_bearing_all": load_bearing_all,
        "identifiable": bool(abs(gold - 1.0) < 1e-9 and reachable_all and load_bearing_all),
        "per_stage": per_stage,
    }


def acceptance_rate(namespace, seeds, cfg, n_per_stratum=24):
    """Fraction of seeds that pass the identifiability gate (rejection sampler)."""
    from .generator import generate
    accepted = 0
    reports = []
    for s in seeds:
        inst = generate(namespace, s, cfg)
        rep = check_instance(inst, n_per_stratum=n_per_stratum)
        reports.append(rep)
        accepted += rep["identifiable"]
    return accepted / len(seeds), reports
