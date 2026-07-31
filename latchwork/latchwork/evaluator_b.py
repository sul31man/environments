"""Evaluator B -- an INDEPENDENT re-implementation of pipeline semantics.

Evaluator A is `dsl.Pipeline.observe` (the canonical form-object dispatch).
Evaluator B below re-derives the same observation from the canonical VALUE-KEYS
(`stage.key()` tuples) via a wholly separate interpreter -- it never calls
`stage.holds` or `Pipeline.observe`.  Agreement between A and B over the battery
is the differential that guards against a self-consistent-but-wrong evaluator.

Because it consumes only value-keys, Evaluator B is ALSO the boundary-safe
grader: the agent submits a reconstructed pipeline as a list of value-keys, and
we interpret them here -- never trusting agent code, never isinstance-ing an
agent object (grade-by-value, condition/soundness requirement).
"""

from __future__ import annotations

from typing import List, Tuple

ACCEPT = 0


def _group(field: int, n_fields: int, n_groups: int) -> int:
    return (field * n_groups) // n_fields


def _holds_from_key(key, a: Tuple[int, ...]) -> bool:
    """Independently evaluate one stage from its canonical value-key."""
    kind = key[0]
    if kind == "INTERVAL":
        _, f, lo, hi = key
        v = a[f]
        return not (v < lo or v > hi)          # independent phrasing
    if kind == "SET":
        _, f, members = key
        return a[f] in set(members)
    if kind == "MODULAR":
        _, f, m, r = key
        return (a[f] - r) % m == 0             # independent phrasing
    if kind == "LINEAR":
        _, f0, f1, c0, c1, m, r = key
        return (c0 * a[f0] + c1 * a[f1] - r) % m == 0
    if kind == "ORDER":
        _, f0, f1, rel = key
        d = a[f0] - a[f1]
        if rel == "<":
            return d < 0
        if rel == "<=":
            return d <= 0
        if rel == ">":
            return d > 0
        if rel == ">=":
            return d >= 0
        raise ValueError(f"bad rel {rel!r}")
    if kind == "DEPENDENCY":
        _, f0, f1, c0, c1, M = key
        return (a[f1] - (c0 * a[f0] + c1)) % M == 0
    raise ValueError(f"unknown form {kind!r}")


def _primary_field(key) -> int:
    # field position in each key layout (independent of dsl.py accessors)
    kind = key[0]
    if kind in ("INTERVAL", "SET", "MODULAR"):
        return key[1]
    return key[1]  # LINEAR/ORDER/DEPENDENCY: f0 at index 1


def observe_from_keys(keys: List[tuple], assignment: Tuple[int, ...],
                      n_fields: int, n_groups: int = 4):
    """(first_failing_index_1based, coarse_class) or (ACCEPT, None)."""
    for i, key in enumerate(keys):
        if not _holds_from_key(key, assignment):
            g = _group(_primary_field(key), n_fields, n_groups)
            return (i + 1, f"G{g}")
    return (ACCEPT, None)
