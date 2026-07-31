"""Channel-only baseline solvers + gold.

All solvers here (except `gold`) touch ONLY the Channel -- never params, witness,
or the oracle module.  Each returns a reconstructed pipeline as a list of
value-keys, scored by the differential in scoring.py.

Roster (condition 6):
  * gold            -- params-known reconstruction (feasibility). Score 1.0.
  * no_probe        -- guess without probing (Gate i FORCED). Floor.
  * batch           -- NON-ADAPTIVE: fixed sample chosen up front, then fit
                       (Gate ii). Walls: random samples never penetrate deep.
  * rote            -- adaptive but mechanical: interval-only, single field,
                       no form-hypothesis, no coupling reasoning (condition 1 =
                       the HARDNESS proof). Walls with margin.
  * adaptive        -- the real discoverer. effort='full' (unbounded reasoning:
                       relax coupling by re-solving the prefix per field-value ->
                       ~1.0, proves recoverability/identifiability) or
                       'bounded' (no relaxation -> band target, budget-insensitive
                       per condition 3).

Shared discovery primitives model exactly the adaptive chain: find an ACCEPT
anchor, then recover stages 1..L using the first-fail index as a lossy, masked,
restricted oracle for "does stage k hold?".
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from .channel import Channel
from .evaluator_b import _holds_from_key

ACCEPT = 0
_MODS = (3, 4, 5, 6, 7, 8)


def _key_fields(key) -> Tuple[int, ...]:
    kind = key[0]
    if kind in ("INTERVAL", "SET", "MODULAR"):
        return (key[1],)
    return (key[1], key[2])  # LINEAR/ORDER/DEPENDENCY: f0,f1


def _offline_satisfy(prefix_keys, n, M, fixed: Dict[int, int], rng,
                     restarts=24, steps=120):
    """Find an assignment satisfying ALL prefix_keys with `fixed` fields pinned,
    using min-conflicts over the solver's OWN recovered keys (no channel).
    Returns assignment or None (prefix + fixed jointly infeasible under my model).
    This is how the full solver frees a field from earlier-stage masking."""
    if not prefix_keys:
        a = [rng.randrange(M) for _ in range(n)]
        for f, v in fixed.items():
            a[f] = v
        return tuple(a)

    def cost(a):
        return sum(1 for key in prefix_keys if not _holds_from_key(key, a))

    for _r in range(restarts):
        a = [rng.randrange(M) for _ in range(n)]
        for f, v in fixed.items():
            a[f] = v
        if cost(a) == 0:
            return tuple(a)
        for _s in range(steps):
            viol = [key for key in prefix_keys if not _holds_from_key(key, a)]
            if not viol:
                return tuple(a)
            key = rng.choice(viol)
            cand = [f for f in _key_fields(key) if f not in fixed]
            if not cand:
                break  # this violated constraint is over pinned fields only
            f = rng.choice(cand)
            best_v, best_c = a[f], cost(a)
            order = list(range(M)); rng.shuffle(order)
            for v in order:
                a[f] = v
                c = cost(a)
                if c < best_c:
                    best_c, best_v = c, v
                    if c == 0:
                        break
            a[f] = best_v
            if best_c == 0:
                return tuple(a)
            if rng.random() < 0.2:
                free = [f for f in range(n) if f not in fixed]
                a[rng.choice(free)] = rng.randrange(M)
    return None


# --------------------------------------------------------------------------- #
# gold
# --------------------------------------------------------------------------- #
def gold(instance) -> List[tuple]:
    return list(instance.pipeline.key())


# --------------------------------------------------------------------------- #
# Shared channel-only primitives
# --------------------------------------------------------------------------- #
def _rank(obs) -> int:
    """Depth reached: ACCEPT is best (L+1-ish), failing at k means passed k-1."""
    idx = obs[0] if obs else -1
    return 10**6 if idx == ACCEPT else idx


def deepen(ch: Channel, rng: random.Random, start=None, restarts=6, passes=6,
           fix: Optional[Dict[int, int]] = None):
    """Coordinate-ascent on the first-fail index -> assignment passing as many
    stages as possible.  `fix` pins fields (used by the full solver to free a
    field from earlier-stage masking)."""
    n, M = ch.n_fields, ch.domain
    fix = fix or {}
    best_a, best_r = None, -1
    for _r in range(restarts):
        a = list(start) if (start is not None and _r == 0) else [rng.randrange(M) for _ in range(n)]
        for f, v in fix.items():
            a[f] = v
        cur = ch.probe(a)
        if cur is None:
            break
        cur_r = _rank(cur)
        for _p in range(passes):
            improved = False
            order = list(range(n))
            rng.shuffle(order)
            for f in order:
                if f in fix:
                    continue
                base_v, base_r = a[f], cur_r
                vals = list(range(M))
                rng.shuffle(vals)
                for v in vals:
                    a[f] = v
                    o = ch.probe(a)
                    if o is None:
                        a[f] = base_v
                        return best_a if best_r >= cur_r else tuple(a)
                    r = _rank(o)
                    if r > base_r:
                        base_r, base_v = r, v
                        if r >= 10**6:
                            break
                a[f] = base_v
                if base_r > cur_r:
                    cur_r, improved = base_r, True
            if cur_r >= 10**6 or not improved:
                break
        if cur_r > best_r:
            best_a, best_r = tuple(a), cur_r
        if best_r >= 10**6:
            break
    return best_a


# ---- form classification from a boolean oracle -------------------------------
def _classify_1field(f: int, passvals: Dict[int, bool], M: int) -> tuple:
    """Given passK over a subset of the domain of field f, return a stage key."""
    passset = sorted(v for v, ok in passvals.items() if ok)
    failset = [v for v, ok in passvals.items() if not ok]
    if not passset:
        return ("INTERVAL", f, 0, M - 1)  # degenerate
    lo, hi = min(passset), max(passset)
    # INTERVAL: contiguous pass-block, everything observed outside fails
    contiguous = all(passvals.get(v, True) for v in range(lo, hi + 1)) and \
        all((v < lo or v > hi) for v in failset)
    if contiguous and (lo > 0 or hi < M - 1):
        return ("INTERVAL", f, lo, hi)
    # MODULAR: single residue class mod m separates pass from fail
    for m in _MODS:
        residues = {v % m for v in passset}
        if len(residues) == 1:
            r = next(iter(residues))
            if all(v % m != r for v in failset):
                return ("MODULAR", f, m, r)
    # SET: arbitrary membership (exact iff we observed the full domain)
    return ("SET", f, tuple(passset))


def _classify_2field(f0: int, f1: int, query, M: int) -> Optional[tuple]:
    """query(v0, v1) -> True/False/None(invalid). Distinguish ORDER/LINEAR/DEP."""
    rng = random.Random(f0 * 131 + f1 * 17 + 7)
    samples = []
    tries = 0
    while len(samples) < 120 and tries < 1500:
        tries += 1
        v0, v1 = rng.randrange(M), rng.randrange(M)
        res = query(v0, v1)
        if res is not None:
            samples.append((v0, v1, res))
    # ORDER boundary: explicitly probe v0==v1 to separate '<' from '<=' etc.
    for v in rng.sample(range(M), min(M, 20)):
        res = query(v, v)
        if res is not None:
            samples.append((v, v, res))
    passes = [(v0, v1) for v0, v1, ok in samples if ok]
    if not passes:
        return None

    # DEPENDENCY: for a fixed v0, exactly one v1 passes -> functional y=(a v0+b)%M
    pts = []
    for v0 in {p[0] for p in passes}:
        ys = [v1 for v1 in range(M) if query(v0, v1) is True]
        if len(ys) == 1:
            pts.append((v0, ys[0]))
        if len(pts) >= 3:
            break
    if len(pts) >= 2:
        (x0, y0), (x1, y1) = pts[0], pts[1]
        for a in range(1, M):
            if (a * (x1 - x0)) % M == (y1 - y0) % M:
                b = (y0 - a * x0) % M
                if all((a * x + b) % M == y for x, y in pts):
                    return ("DEPENDENCY", f0, f1, a, b, M)

    # ORDER: pass region is a half-plane in sign(v0 - v1)
    def order_ok(rel):
        good = 0
        for v0, v1, ok in samples:
            d = v0 - v1
            pred = {"<": d < 0, "<=": d <= 0, ">": d > 0, ">=": d >= 0}[rel]
            good += (pred == ok)
        return good / len(samples)
    best_rel, best_acc = max(((rel, order_ok(rel)) for rel in ("<", "<=", ">", ">=")),
                             key=lambda t: t[1])
    if best_acc >= 0.97:
        return ("ORDER", f0, f1, best_rel)

    # LINEAR: (a v0 + b v1) % m == r
    for m in _MODS:
        # solve for (a,b,r) consistent with passes; search small coeff space
        found = None
        pass_pts = [(v0, v1) for v0, v1, ok in samples if ok]
        fail_pts = [(v0, v1) for v0, v1, ok in samples if not ok]
        if len(pass_pts) < 2:
            continue
        for a in range(0, m):
            for b in range(0, m):
                if a == 0 and b == 0:
                    continue
                rs = {(a * v0 + b * v1) % m for v0, v1 in pass_pts}
                if len(rs) == 1:
                    r = next(iter(rs))
                    if all((a * v0 + b * v1) % m != r for v0, v1 in fail_pts):
                        found = (a, b, r)
                        break
            if found:
                break
        if found:
            a, b, r = found
            # VERIFY the fit against all samples; accept only if it separates
            ok = all(((a * v0 + b * v1) % m == r) == res for v0, v1, res in samples)
            if ok:
                return ("LINEAR", f0, f1, a, b, m, r)
    return None


# --------------------------------------------------------------------------- #
# no_probe
# --------------------------------------------------------------------------- #
def no_probe(ch: Channel, rng: random.Random) -> List[tuple]:
    n, M, L = ch.n_fields, ch.domain, ch.L
    keys = []
    for _ in range(L):
        form = rng.choice(["INTERVAL", "SET", "MODULAR", "LINEAR", "ORDER", "DEPENDENCY"])
        f0 = rng.randrange(n)
        f1 = rng.choice([f for f in range(n) if f != f0])
        if form == "INTERVAL":
            lo = rng.randrange(M); hi = rng.randrange(lo, M); keys.append(("INTERVAL", f0, lo, hi))
        elif form == "SET":
            keys.append(("SET", f0, tuple(sorted(rng.sample(range(M), rng.randint(2, M // 4))))))
        elif form == "MODULAR":
            m = rng.choice(_MODS); keys.append(("MODULAR", f0, m, rng.randrange(m)))
        elif form == "LINEAR":
            m = rng.choice(_MODS); keys.append(("LINEAR", f0, f1, rng.randint(1, M - 1), rng.randint(1, M - 1), m, rng.randrange(m)))
        elif form == "ORDER":
            keys.append(("ORDER", f0, f1, rng.choice(["<", "<=", ">", ">="])))
        else:
            keys.append(("DEPENDENCY", f0, f1, rng.randint(1, M - 1), rng.randrange(M), M))
    return keys


# --------------------------------------------------------------------------- #
# Anchor + per-stage recovery (used by batch/rote/adaptive)
# --------------------------------------------------------------------------- #
def _find_fields_for_stage(ch, rng, anchor, k, tries_per_field=6):
    """Fields whose single-field perturbation from the anchor makes k the first
    failure -> fields used by stage k."""
    n, M = ch.n_fields, ch.domain
    flds = []
    for f in range(n):
        hit = False
        for _ in range(tries_per_field):
            a = list(anchor); a[f] = rng.randrange(M)
            o = ch.probe(a)
            if o and o[0] == k:
                hit = True; break
        if hit:
            flds.append(f)
    return flds


def _bounded_recover(ch, rng, anchor, k, M):
    """Anchor-masked recovery (bounded reasoning): probe perturbations of the
    ACCEPT anchor; only values that don't trip an earlier stage are observable.
    Coupling therefore masks part of each stage -> partial params -> band."""
    n = ch.n_fields
    flds = _find_fields_for_stage(ch, rng, anchor, k, tries_per_field=6)
    if not flds:
        return ("INTERVAL", 0, 0, M - 1)
    if len(flds) == 1:
        f = flds[0]
        passvals = {}
        for v in range(M):
            a = list(anchor); a[f] = v
            o = ch.probe(a)
            if o is None:
                break
            if o[0] == k:
                passvals[v] = False
            elif o[0] > k or o[0] == ACCEPT:
                passvals[v] = True
        return _classify_1field(f, passvals, M)
    f0, f1 = flds[0], flds[1]

    def q(v0, v1):
        a = list(anchor); a[f0] = v0; a[f1] = v1
        o = ch.probe(a)
        if o is None:
            return None
        if o[0] == k:
            return False
        if o[0] > k or o[0] == ACCEPT:
            return True
        return None
    res = _classify_2field(f0, f1, q, M)
    return res if res is not None else ("INTERVAL", f0, 0, M - 1)


def _repair_from(base, prefix_keys, n, M, fixed, rng, steps=200):
    """Min-conflicts starting FROM base (an ACCEPT anchor), pinning `fixed`,
    touching only fields inside violated prefix constraints.  Keeps every other
    field -- crucially stage k's fields -- at the anchor, so pinning frees a
    field from earlier stages without disturbing k.  Returns assignment or None
    (prefix + pins jointly infeasible under the recovered model)."""
    a = list(base)
    for f, v in fixed.items():
        a[f] = v
    for _ in range(steps):
        viol = [key for key in prefix_keys if not _holds_from_key(key, a)]
        if not viol:
            return tuple(a)
        key = rng.choice(viol)
        cand = [f for f in _key_fields(key) if f not in fixed]
        if not cand:
            return None  # violated constraint is over pinned fields only
        f = rng.choice(cand)
        best_v, best_c = a[f], len(viol)
        for v in rng.sample(range(M), M):
            a[f] = v
            c = sum(1 for kk in prefix_keys if not _holds_from_key(kk, a))
            if c < best_c:
                best_c, best_v = c, v
                if c == 0:
                    break
        a[f] = best_v
    return tuple(a) if all(_holds_from_key(kk, a) for kk in prefix_keys) else None


def _full_recover(ch, rng, prefix_keys, k, M, anchors):
    """Clean recovery: pin stage k's field(s) and repair the prefix from an
    ACCEPT anchor so k is observed UNMASKED on its reachable domain.  Multiple
    anchors improve coverage of hard-to-reach values.  Exact on the reachable
    region -> ~1.0 (recoverability).  Errors in prefix_keys propagate -> chain."""
    n = ch.n_fields

    def clean_obs(fixed):
        # try each anchor; repair from it holding k's pinned fields fixed
        for anc in anchors:
            a = _repair_from(anc, prefix_keys, n, M, fixed, rng)
            if a is None:
                continue
            o = ch.probe(a)
            if o is None:
                return None
            if o[0] == k:
                return False
            if o[0] > k or o[0] == ACCEPT:
                return True
            # o[0] < k: this anchor's repair violated prefix under recovered
            # model; try the next anchor
        return None

    # -- detection: vary ONE field from an anchor, others held; union over
    #    anchors so a field masked from one anchor is caught from another --
    flds = []
    for f in range(n):
        seen_fail = seen_pass = False
        for anc in anchors:
            for v in range(M):
                a = list(anc); a[f] = v
                o = ch.probe(a)
                if o is None:
                    break
                if o[0] == k:
                    seen_fail = True
                elif o[0] > k or o[0] == ACCEPT:
                    seen_pass = True
                if seen_fail and seen_pass:
                    break
            if seen_fail and seen_pass:
                break
        if seen_fail and seen_pass:
            flds.append(f)
    if not flds:
        # fallback: repair-based detection frees masked fields
        for f in range(n):
            vals = {clean_obs({f: v}) for v in rng.sample(range(M), min(M, 16))}
            if True in vals and False in vals:
                flds.append(f)
    if not flds:
        return ("INTERVAL", 0, 0, M - 1)

    if len(flds) == 1:
        f = flds[0]
        passvals = {}
        for v in range(M):
            r = clean_obs({f: v})
            if r in (True, False):
                passvals[v] = (r is True)
        return _classify_1field(f, passvals, M)

    # 2-field: recover with the pair that best explains the behavior
    f0, f1 = flds[0], flds[1]

    def q(v0, v1):
        return clean_obs({f0: v0, f1: v1})
    res = _classify_2field(f0, f1, q, M)
    return res if res is not None else ("INTERVAL", f0, 0, M - 1)


def adaptive(ch: Channel, rng: random.Random, effort: str = "bounded") -> List[tuple]:
    """The real discoverer. effort='full' (offline-prefix clean probes, ~1.0,
    recoverability proof) or 'bounded' (anchor-masked, band target)."""
    n, M, L = ch.n_fields, ch.domain, ch.L
    full = effort == "full"
    if full:
        # several ACCEPT anchors -> better reachable-value coverage for repair
        anchors = []
        for _ in range(4):
            a = deepen(ch, rng, restarts=6, passes=6)
            if a is not None and ch.probe(a)[0] == ACCEPT:
                anchors.append(a)
        if not anchors:
            a = deepen(ch, rng, restarts=10, passes=8)
            if a is None:
                return no_probe(ch, rng)
            anchors = [a]
        keys: List[tuple] = []
        for k in range(1, L + 1):
            keys.append(_full_recover(ch, rng, list(keys), k, M, anchors))
        return keys
    anchor = deepen(ch, rng, restarts=5, passes=5)
    if anchor is None:
        return no_probe(ch, rng)
    return [_bounded_recover(ch, rng, anchor, k, M) for k in range(1, L + 1)]


# --------------------------------------------------------------------------- #
# rote: mechanical, interval-only, single field, no coupling reasoning
# --------------------------------------------------------------------------- #
def rote(ch: Channel, rng: random.Random) -> List[tuple]:
    n, M, L = ch.n_fields, ch.domain, ch.L
    anchor = deepen(ch, rng, restarts=5, passes=5)
    if anchor is None:
        return no_probe(ch, rng)
    keys = []
    for k in range(1, L + 1):
        # pick the single most-responsive field (largest count of k-failures)
        best_f, best_hits = 0, -1
        for f in range(n):
            hits = 0
            for _ in range(6):
                a = list(anchor); a[f] = rng.randrange(M)
                o = ch.probe(a)
                if o and o[0] == k:
                    hits += 1
            if hits > best_hits:
                best_hits, best_f = hits, f
        # ALWAYS assume interval; binary-search a threshold on that one field,
        # holding others at the anchor (no coupling recheck, no other forms).
        f = best_f
        passv = []
        for v in range(M):
            a = list(anchor); a[f] = v
            o = ch.probe(a)
            passv.append(o is not None and o[0] != k)  # treats idx<k as 'pass' (blind)
        idxs = [v for v, ok in enumerate(passv) if ok]
        if idxs:
            keys.append(("INTERVAL", f, min(idxs), max(idxs)))
        else:
            keys.append(("INTERVAL", f, 0, M - 1))
    return keys


# --------------------------------------------------------------------------- #
# batch: NON-ADAPTIVE. Fixed random sample chosen up front, then fit.
# --------------------------------------------------------------------------- #
def batch(ch: Channel, rng: random.Random, n_samples: int) -> List[tuple]:
    n, M, L = ch.n_fields, ch.domain, ch.L
    data = []
    for _ in range(n_samples):
        a = tuple(rng.randrange(M) for _ in range(n))
        o = ch.probe(a)
        if o is None:
            break
        data.append((a, o))
    keys = []
    for k in range(1, L + 1):
        # restricted oracle from the FIXED sample only (no new queries)
        # find fields: those where among sampled points, value correlates with idx==k
        fails_k = [a for a, o in data if o[0] == k]
        passes_k = [a for a, o in data if o[0] > k or o[0] == ACCEPT]
        if not fails_k or not passes_k:
            keys.append(("INTERVAL", 0, 0, M - 1))  # no data on deep stage
            continue
        # crude single-field interval fit on the field with clearest separation
        best = None
        for f in range(n):
            pv = sorted({a[f] for a in passes_k})
            fv = {a[f] for a in fails_k}
            if pv and not (set(pv) & fv):
                best = ("INTERVAL", f, min(pv), max(pv)); break
        keys.append(best or ("INTERVAL", 0, 0, M - 1))
    return keys
