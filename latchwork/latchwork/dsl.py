"""Latchwork DSL: predicate forms and the short-circuit pipeline.

An instance is an ordered pipeline of L predicate STAGES over an assignment
(a vector of N integer fields in [0, M)).  The pipeline is evaluated with
SHORT-CIRCUIT semantics: stages are checked in order and the FIRST failing
stage's (1-based index, coarse_class) is the only thing observable.  This file
is pure semantics -- no generation, no channel, no scoring.

Design invariants that other modules rely on:
  * `coarse_class` is a function of the stage's PRIMARY FIELD only (its field
    group), never of the stage's FORM.  The generator samples fields
    independently of form, so class carries zero mutual information about form
    (condition 4).  Proven empirically in gates/run_gates.py.
  * Every form exposes `.fields()`, `.primary_field`, `.holds(a)`, `.kind`, and
    a canonical `.key()` for value-based equality across the agent boundary
    (grade-by-value, never isinstance on agent objects).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

ACCEPT = 0  # sentinel index meaning "all stages passed"

# The disclosed hypothesis space.  A frontier agent is TOLD these are the only
# forms; it must discover which one each hidden stage uses, plus its params.
FORMS = ("INTERVAL", "SET", "MODULAR", "LINEAR", "ORDER", "DEPENDENCY")


def field_group(field: int, n_fields: int, n_groups: int = 4) -> int:
    """Coarse class bucket of a field. Deterministic; form-independent."""
    return (field * n_groups) // n_fields


# --------------------------------------------------------------------------- #
# Predicate forms.  Each is an immutable value object.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Interval:
    """x[field] in [lo, hi]  (single field, contiguous)."""
    kind = "INTERVAL"
    field: int
    lo: int
    hi: int

    def holds(self, a: Tuple[int, ...]) -> bool:
        return self.lo <= a[self.field] <= self.hi

    @property
    def primary_field(self) -> int:
        return self.field

    def fields(self):
        return (self.field,)

    def key(self):
        return ("INTERVAL", self.field, self.lo, self.hi)


@dataclass(frozen=True)
class SetMember:
    """x[field] in S  (single field, arbitrary subset -- NOT contiguous)."""
    kind = "SET"
    field: int
    members: frozenset

    def holds(self, a: Tuple[int, ...]) -> bool:
        return a[self.field] in self.members

    @property
    def primary_field(self) -> int:
        return self.field

    def fields(self):
        return (self.field,)

    def key(self):
        return ("SET", self.field, tuple(sorted(self.members)))


@dataclass(frozen=True)
class Modular:
    """x[field] % m == r  (single field, periodic)."""
    kind = "MODULAR"
    field: int
    m: int
    r: int

    def holds(self, a: Tuple[int, ...]) -> bool:
        return a[self.field] % self.m == self.r

    @property
    def primary_field(self) -> int:
        return self.field

    def fields(self):
        return (self.field,)

    def key(self):
        return ("MODULAR", self.field, self.m, self.r)


@dataclass(frozen=True)
class Linear:
    """(a*x[f0] + b*x[f1]) % m == r  (two fields, modular linear relation)."""
    kind = "LINEAR"
    f0: int
    f1: int
    a: int
    b: int
    m: int
    r: int

    def holds(self, a: Tuple[int, ...]) -> bool:
        return (self.a * a[self.f0] + self.b * a[self.f1]) % self.m == self.r

    @property
    def primary_field(self) -> int:
        return self.f0

    def fields(self):
        return (self.f0, self.f1)

    def key(self):
        return ("LINEAR", self.f0, self.f1, self.a, self.b, self.m, self.r)


@dataclass(frozen=True)
class Order:
    """x[f0] REL x[f1]  with REL in {<, <=, >, >=}  (two fields)."""
    kind = "ORDER"
    f0: int
    f1: int
    rel: str  # one of "<", "<=", ">", ">="

    def holds(self, a: Tuple[int, ...]) -> bool:
        x, y = a[self.f0], a[self.f1]
        if self.rel == "<":
            return x < y
        if self.rel == "<=":
            return x <= y
        if self.rel == ">":
            return x > y
        return x >= y

    @property
    def primary_field(self) -> int:
        return self.f0

    def fields(self):
        return (self.f0, self.f1)

    def key(self):
        return ("ORDER", self.f0, self.f1, self.rel)


@dataclass(frozen=True)
class Dependency:
    """x[f1] == (a*x[f0] + b) % M  (two fields, functional dependency)."""
    kind = "DEPENDENCY"
    f0: int
    f1: int
    a: int
    b: int
    M: int

    def holds(self, a: Tuple[int, ...]) -> bool:
        return a[self.f1] == (self.a * a[self.f0] + self.b) % self.M

    @property
    def primary_field(self) -> int:
        return self.f0

    def fields(self):
        return (self.f0, self.f1)

    def key(self):
        return ("DEPENDENCY", self.f0, self.f1, self.a, self.b, self.M)


# --------------------------------------------------------------------------- #
# Pipeline: an ordered list of stages, evaluated short-circuit.
# --------------------------------------------------------------------------- #
class Pipeline:
    """Ordered predicate stages with short-circuit evaluation.

    NOTE: a Pipeline never carries a "witness"/solution or any generation
    metadata -- it is pure semantics.  The channel wraps this and purges any
    param access at serve time.
    """

    def __init__(self, stages, n_fields: int, domain: int, n_groups: int = 4):
        self.stages = tuple(stages)
        self.n_fields = n_fields
        self.domain = domain
        self.n_groups = n_groups

    @property
    def L(self) -> int:
        return len(self.stages)

    def observe(self, assignment: Tuple[int, ...]):
        """Return (first_failing_index_1based, coarse_class) or (ACCEPT, None).

        This is the ONLY function through which the channel reveals anything.
        It is lossy: it discloses the first failing stage's index and its field
        group, and NOTHING about params, form, later stages, or 'how to fix'.
        """
        for i, stage in enumerate(self.stages):
            if not stage.holds(assignment):
                g = field_group(stage.primary_field, self.n_fields, self.n_groups)
                return (i + 1, f"G{g}")
        return (ACCEPT, None)

    def accepts(self, assignment: Tuple[int, ...]) -> bool:
        return self.observe(assignment)[0] == ACCEPT

    def key(self):
        """Value-based canonical key of the whole pipeline (order matters)."""
        return tuple(s.key() for s in self.stages)
