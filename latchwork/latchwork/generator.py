"""Seeded deterministic generator for Latchwork instances.

FEASIBILITY BY CONSTRUCTION
---------------------------
We first draw a hidden WITNESS assignment ``w`` uniformly, then fit EVERY stage's
params so that ``w`` satisfies it.  Because all L stages are fit to the SAME w,
``w`` satisfies the whole pipeline simultaneously -- a satisfying assignment
always exists, for ANY coupling level.  Coupling therefore never threatens
feasibility; it only stresses IDENTIFIABILITY (can a channel-only solver recover
each stage?), which is exactly the condition-2 risk we gate separately.

FORM is sampled INDEPENDENTLY of which fields a stage uses, so coarse_class
(a function of the primary field only) carries no information about form
(condition 4).

Train/eval namespaces are disjoint by construction: the namespace string is
folded into the RNG seed, so no eval instance can collide with a train instance.
Generation is deterministic: same (namespace, seed, config) -> byte-identical
pipeline.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Tuple

from .dsl import (
    Dependency,
    Interval,
    Linear,
    Modular,
    Order,
    Pipeline,
    SetMember,
)


@dataclass(frozen=True)
class GenConfig:
    n_fields: int = 10
    domain: int = 64
    n_stages: int = 8
    # relative form weights (sampled independently of fields)
    form_weights: Dict[str, float] = dc_field(
        default_factory=lambda: {
            "INTERVAL": 1.0,
            "SET": 1.0,
            "MODULAR": 1.0,
            "LINEAR": 1.0,
            "ORDER": 1.0,
            "DEPENDENCY": 1.0,
        }
    )
    # coupling: probability a stage reuses an already-used field (0=independent,
    # 1=maximally shared).  This is the primary difficulty knob for the adaptive
    # discovery chain.
    coupling: float = 0.5
    # form_quota: optional EXACT composition {form: count} summing to n_stages.
    # Fixes the multiset of forms per instance (low variance -> mechanical
    # solvers walled on EVERY instance), while form-to-position and fields stay
    # random (class stays form-agnostic).  If None, forms are i.i.d. by weight.
    form_quota: Optional[Dict[str, int]] = None
    # per-stage acceptance band on random assignments (keeps every stage
    # discriminating -- not near-always-true, not near-always-false).
    min_pass_rate: float = 0.02
    max_pass_rate: float = 0.80
    n_groups: int = 4

    def digest(self) -> str:
        quota = sorted(self.form_quota.items()) if self.form_quota else None
        payload = (
            f"{self.n_fields}|{self.domain}|{self.n_stages}|"
            f"{sorted(self.form_weights.items())}|{self.coupling}|"
            f"{self.min_pass_rate}|{self.max_pass_rate}|{self.n_groups}|{quota}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class Instance:
    pipeline: Pipeline
    witness: Tuple[int, ...]        # hidden; PURGED by the channel at serve time
    namespace: str
    seed: int
    config: GenConfig

    def key(self):
        return self.pipeline.key()


def _seed_rng(namespace: str, seed: int, cfg: GenConfig) -> random.Random:
    h = hashlib.sha256(f"latchwork|{namespace}|{seed}|{cfg.digest()}".encode())
    return random.Random(int.from_bytes(h.digest()[:8], "big"))


def _weighted_form(rng: random.Random, weights: Dict[str, float]) -> str:
    forms = list(weights.keys())
    ws = [weights[f] for f in forms]
    return rng.choices(forms, weights=ws, k=1)[0]


def _pick_field(rng: random.Random, n: int, used: List[int], coupling: float,
                exclude: Optional[set] = None, avoid: Optional[set] = None) -> int:
    """Pick a field. `exclude` forbids specific fields (e.g. the other field of
    a 2-field form). `avoid` (used for fresh-field forcing) is a soft ban:
    honored when it still leaves a pool, else ignored."""
    exclude = set(exclude or set())
    avoid = set(avoid or set())
    reuse = used and rng.random() < coupling
    base = list(used if reuse else range(n))
    pool = [f for f in base if f not in exclude and f not in avoid]
    if not pool:
        pool = [f for f in range(n) if f not in exclude and f not in avoid]
    if not pool:  # avoid was too strong; drop it
        pool = [f for f in range(n) if f not in exclude] or list(range(n))
    return rng.choice(pool)


def _pass_rate(stage, n: int, M: int, rng: random.Random, samples: int = 400) -> float:
    hit = 0
    for _ in range(samples):
        a = tuple(rng.randrange(M) for _ in range(n))
        if stage.holds(a):
            hit += 1
    return hit / samples


# --------------------------------------------------------------------------- #
# Per-form param fitting: fit to witness w, keep non-trivial + discriminating.
# Each returns a stage whose .holds(w) is True.
# --------------------------------------------------------------------------- #
def _fit_interval(rng, w, n, M, used, coupling, avoid=None):
    f = _pick_field(rng, n, used, coupling, avoid=avoid)
    wf = w[f]
    # width a modest fraction of the domain -> discriminating, not full-range
    half = rng.randint(max(1, M // 16), max(2, M // 5))
    lo = max(0, wf - rng.randint(0, half))
    hi = min(M - 1, wf + rng.randint(0, half))
    if lo == 0 and hi == M - 1:  # avoid full-range (trivial)
        hi = min(M - 1, wf + half)
    return Interval(f, lo, hi), [f]


def _fit_set(rng, w, n, M, used, coupling, avoid=None):
    f = _pick_field(rng, n, used, coupling, avoid=avoid)
    size = rng.randint(2, max(3, M // 4))
    members = {w[f]}
    while len(members) < size:
        members.add(rng.randrange(M))
    return SetMember(f, frozenset(members)), [f]


def _fit_modular(rng, w, n, M, used, coupling, avoid=None):
    f = _pick_field(rng, n, used, coupling, avoid=avoid)
    m = rng.choice([3, 4, 5, 6, 7, 8])
    return Modular(f, m, w[f] % m), [f]


def _fit_linear(rng, w, n, M, used, coupling, avoid=None):
    f0 = _pick_field(rng, n, used, coupling, avoid=avoid)
    f1 = _pick_field(rng, n, used, coupling, exclude={f0}, avoid=avoid)
    a = rng.randint(1, M - 1)
    b = rng.randint(1, M - 1)
    m = rng.choice([3, 4, 5, 6, 7, 8])
    r = (a * w[f0] + b * w[f1]) % m
    return Linear(f0, f1, a, b, m, r), [f0, f1]


def _fit_order(rng, w, n, M, used, coupling, avoid=None):
    f0 = _pick_field(rng, n, used, coupling, avoid=avoid)
    f1 = _pick_field(rng, n, used, coupling, exclude={f0}, avoid=avoid)
    if w[f0] < w[f1]:
        rel = rng.choice(["<", "<="])
    elif w[f0] > w[f1]:
        rel = rng.choice([">", ">="])
    else:
        rel = rng.choice(["<=", ">="])
    return Order(f0, f1, rel), [f0, f1]


def _fit_dependency(rng, w, n, M, used, coupling, avoid=None):
    f0 = _pick_field(rng, n, used, coupling, avoid=avoid)
    f1 = _pick_field(rng, n, used, coupling, exclude={f0}, avoid=avoid)
    a = rng.randint(1, M - 1)
    b = (w[f1] - a * w[f0]) % M
    return Dependency(f0, f1, a, b, M), [f0, f1]


_FITTERS = {
    "INTERVAL": _fit_interval,
    "SET": _fit_set,
    "MODULAR": _fit_modular,
    "LINEAR": _fit_linear,
    "ORDER": _fit_order,
    "DEPENDENCY": _fit_dependency,
}


def _fit_with_optional_fresh(form, rng, w, n, M, used, coupling, force_fresh):
    avoid = set(used) if force_fresh else None
    return _FITTERS[form](rng, w, n, M, used, coupling, avoid=avoid)


def _stage_reachable(prefix_stages, candidate, n, M, n_groups, rng) -> bool:
    """True iff some assignment passes all prefix stages and fails `candidate`.
    Uses a light oracle prefix-search; the identifiability gate re-verifies at
    full strength."""
    from .oracle import pass_prefix_fail_k  # local import avoids cycle at load

    temp = Pipeline(list(prefix_stages) + [candidate], n, M, n_groups)
    k = len(temp.stages)
    got = pass_prefix_fail_k(temp, k, rng, witness=None, restarts=14, steps=140)
    return got is not None


def generate(namespace: str, seed: int, cfg: Optional[GenConfig] = None) -> Instance:
    cfg = cfg or GenConfig()
    rng = _seed_rng(namespace, seed, cfg)
    n, M = cfg.n_fields, cfg.domain

    w = tuple(rng.randrange(M) for _ in range(n))
    stages = []
    used: List[int] = []

    # optional fixed form composition, shuffled into positions (form stays
    # independent of fields -> class remains form-agnostic)
    forced_forms = None
    if cfg.form_quota:
        assert sum(cfg.form_quota.values()) == cfg.n_stages, "quota must sum to n_stages"
        forced_forms = []
        for form, cnt in cfg.form_quota.items():
            forced_forms += [form] * cnt
        rng.shuffle(forced_forms)

    for stage_i in range(cfg.n_stages):
        # Resample the stage until it is BOTH discriminating (pass-rate in band)
        # AND reachable given the already-fixed prefix (there exists an
        # assignment passing 1..k-1 and failing this stage).  Reachability =>
        # the stage is observable/identifiable and load-bearing.  A stage using
        # a fresh (unused) field is always reachable, so this converges.
        # Graded fallback so generation never fails: prefer a stage that is BOTH
        # discriminating (pass-rate in band) AND reachable; then reachable; then
        # discriminating; then anything.  Reachability => observable/load-bearing.
        best = fb_reach = fb_disc = fb_any = None
        for attempt in range(60):
            form = forced_forms[stage_i] if forced_forms else _weighted_form(rng, cfg.form_weights)
            # after several failures, bias toward a fresh field to guarantee
            # reachability without abandoning coupling earlier.
            force_fresh = attempt >= 30
            stage, fields = _fit_with_optional_fresh(
                form, rng, w, n, M, used, cfg.coupling, force_fresh
            )
            pr = _pass_rate(stage, n, M, rng)
            disc = cfg.min_pass_rate <= pr <= cfg.max_pass_rate
            reach = _stage_reachable(stages, stage, n, M, cfg.n_groups, rng)
            fb_any = (stage, fields)
            if reach and fb_reach is None:
                fb_reach = (stage, fields)
            if disc and fb_disc is None:
                fb_disc = (stage, fields)
            if disc and reach:
                best = (stage, fields)
                break
        stage, fields = best or fb_reach or fb_disc or fb_any
        stages.append(stage)
        for f in fields:
            if f not in used:
                used.append(f)

    pipe = Pipeline(stages, n, M, cfg.n_groups)
    inst = Instance(pipe, w, namespace, seed, cfg)
    # feasibility invariant: the witness must be accepted (by construction).
    assert pipe.accepts(w), "witness-fit invariant violated"
    return inst
