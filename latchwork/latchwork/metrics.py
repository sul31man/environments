"""Model-free measurements shared by knob-tuning and the Stage-0 receipt."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Dict, List

from .channel import Channel
from .dsl import ACCEPT
from .generator import GenConfig, generate
from . import solvers as S
from .scoring import build_battery, score_keys


# --------------------------------------------------------------------------- #
# Solver profile
# --------------------------------------------------------------------------- #
def solver_profile(cfg: GenConfig, seeds, budget: int, namespace="train",
                   full_subset=0, n_per_stratum=24):
    """Fast profile (no_probe/batch/rote/bounded at B and 2B) over all seeds.
    The unbounded `full` recoverability solver is expensive, so it is run only on
    the first `full_subset` seeds (it is an indicator, not a 100-seed gate)."""
    rows = []
    for i, seed in enumerate(seeds):
        inst = generate(namespace, seed, cfg)
        n, ng = cfg.n_fields, cfg.n_groups
        battery = build_battery(inst, n_per_stratum=n_per_stratum)
        sc = lambda keys: score_keys(keys, battery, n, ng)[0]
        R = lambda s: random.Random(s)
        row = {
            "gold": sc(S.gold(inst)),
            "no_probe": sc(S.no_probe(Channel(inst, budget=0), R(seed + 1))),
            "batch": sc(S.batch(Channel(inst, budget=budget), R(seed + 2), budget)),
            "rote": sc(S.rote(Channel(inst, budget=budget), R(seed + 3))),
            "bounded_B": sc(S.adaptive(Channel(inst, budget=budget), R(seed + 4), "bounded")),
            "bounded_2B": sc(S.adaptive(Channel(inst, budget=2 * budget), R(seed + 5), "bounded")),
        }
        if i < full_subset:
            row["full"] = sc(S.adaptive(Channel(inst, budget=None), R(seed + 6), "full"))
        rows.append(row)
    return rows


def summarize(rows) -> Dict[str, Dict[str, float]]:
    keys = set()
    for r in rows:
        keys |= set(r.keys())
    out = {}
    for k in keys:
        vals = [r[k] for r in rows if k in r]
        vals_sorted = sorted(vals)
        out[k] = {
            "mean": sum(vals) / len(vals),
            "min": min(vals),
            "max": max(vals),
            "p50": vals_sorted[len(vals) // 2],
        }
    return out


# --------------------------------------------------------------------------- #
# Condition 5: shallow pass-region (masking).  P(a random assignment passes the
# first k stages) must be tiny -> a non-adaptive batch cannot penetrate deep.
# --------------------------------------------------------------------------- #
def shallow_pass_region(cfg: GenConfig, seeds, depths=(1, 2, 3), samples=20000,
                        namespace="train"):
    frac = {d: [] for d in depths}
    for seed in seeds:
        inst = generate(namespace, seed, cfg)
        rng = random.Random(10_000 + seed)
        n, M = cfg.n_fields, cfg.domain
        cnt = {d: 0 for d in depths}
        for _ in range(samples):
            a = tuple(rng.randrange(M) for _ in range(n))
            idx = inst.pipeline.observe(a)[0]
            reached = 10**9 if idx == ACCEPT else idx  # depth passed = idx-1
            for d in depths:
                if (idx == ACCEPT) or (idx > d):  # passed the first d stages
                    cnt[d] += 1
        for d in depths:
            frac[d].append(cnt[d] / samples)
    return {d: sum(v) / len(v) for d, v in frac.items()}


# --------------------------------------------------------------------------- #
# Condition 4: coarse_class must be FORM-AGNOSTIC.  Estimate MI(class; form)
# over generated stages; should be ~0 (class is a function of field only, and
# form is sampled independently of field).
# --------------------------------------------------------------------------- #
def class_form_mi(cfg: GenConfig, seeds, namespace="train"):
    from .dsl import field_group
    pairs = []
    for seed in seeds:
        inst = generate(namespace, seed, cfg)
        for st in inst.pipeline.stages:
            g = field_group(st.primary_field, cfg.n_fields, cfg.n_groups)
            pairs.append((f"G{g}", st.kind))
    N = len(pairs)
    pc = Counter(c for c, _ in pairs)
    pf = Counter(f for _, f in pairs)
    pcf = Counter(pairs)
    mi = 0.0
    for (c, f), n_cf in pcf.items():
        pxy = n_cf / N
        px = pc[c] / N
        py = pf[f] / N
        mi += pxy * math.log2(pxy / (px * py))
    # normalize by min(H(class),H(form)) for an interpretable [0,1] scale
    hc = -sum((v / N) * math.log2(v / N) for v in pc.values())
    hf = -sum((v / N) * math.log2(v / N) for v in pf.values())
    denom = min(hc, hf) or 1.0
    return {"mi_bits": mi, "normalized_mi": mi / denom, "n_stages": N}


# --------------------------------------------------------------------------- #
# Gate ii-a: a NON-ADAPTIVE batch cannot distinguish >=2 variants differing only
# in a deep stage.  Returns fraction of instances where a fixed random batch of
# `batch_size` probes fails to distinguish the base from a deep-stage variant.
# --------------------------------------------------------------------------- #
def _fresh_reachable_stage(prefix_stages, cfg, rng):
    """A freshly-fit stage, reachable given prefix and DIFFERENT from none in
    particular -- used to build a variant of a deep stage."""
    from .generator import _FITTERS, _weighted_form, _stage_reachable
    n, M = cfg.n_fields, cfg.domain
    w = tuple(rng.randrange(M) for _ in range(n))
    used = []
    for st in prefix_stages:
        for f in st.fields():
            if f not in used:
                used.append(f)
    for _ in range(80):
        form = _weighted_form(rng, cfg.form_weights)
        stage, _flds = _FITTERS[form](rng, w, n, M, used, cfg.coupling)
        if _stage_reachable(prefix_stages, stage, n, M, cfg.n_groups, rng):
            return stage
    return None


def variant_indistinguishability(cfg: GenConfig, seeds, batch_size,
                                 namespace="train"):
    n, M = cfg.n_fields, cfg.domain
    indistinct = 0
    total = 0
    for seed in seeds:
        inst = generate(namespace, seed, cfg)
        L = inst.pipeline.L
        rng = random.Random(50_000 + seed)
        # variant differs only in the LAST (deepest) stage
        j = L
        prefix = list(inst.pipeline.stages[:j - 1])
        new_last = _fresh_reachable_stage(prefix, cfg, rng)
        if new_last is None:
            continue
        base_stages = list(inst.pipeline.stages)
        var_stages = base_stages[:j - 1] + [new_last]
        from .dsl import Pipeline
        base_pipe = inst.pipeline
        var_pipe = Pipeline(var_stages, n, M, cfg.n_groups)
        # fixed non-adaptive batch of random assignments
        distinguished = False
        for _ in range(batch_size):
            a = tuple(rng.randrange(M) for _ in range(n))
            if base_pipe.observe(a) != var_pipe.observe(a):
                distinguished = True
                break
        total += 1
        if not distinguished:
            indistinct += 1
    return indistinct / total if total else float("nan")
