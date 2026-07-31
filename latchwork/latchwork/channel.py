"""The lossy observation channel the agent probes.

The channel is the ONLY interface between a solver and a hidden instance.  It:
  * exposes the disclosed structure (n_fields, domain, L, n_groups);
  * answers probes with (first_failing_index, coarse_class) only -- never
    params, form, witness, later stages, or a correctness bit on a
    reconstruction;
  * meters the probe budget.

It holds the pipeline in a name-mangled private slot and exposes no accessor to
params or witness -- the offline analogue of the serve-time oracle purge.  A
solver that only touches `Channel` cannot read the answer; it must infer it.

PROOF-OBLIGATION NOTE (why this is not a verification oracle): `probe` takes an
ASSIGNMENT and returns where THAT assignment first trips.  There is no method
that takes a reconstructed pipeline and returns whether it is correct.  The
scored deliverable (a reconstructed pipeline, graded on a held-out battery) is
disjoint from anything `probe` returns.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .generator import Instance


class BudgetExceeded(Exception):
    pass


class Channel:
    def __init__(self, instance: Instance, budget: Optional[int] = None,
                 hard_fail: bool = False):
        self.__pipeline = instance.pipeline          # name-mangled, private
        self.n_fields = instance.pipeline.n_fields
        self.domain = instance.pipeline.domain
        self.n_groups = instance.pipeline.n_groups
        self.L = instance.pipeline.L                 # disclosed: how many stages
        self.budget = budget
        self.hard_fail = hard_fail
        self.count = 0

    def probe(self, assignment: Tuple[int, ...]):
        if self.budget is not None and self.count >= self.budget:
            if self.hard_fail:
                raise BudgetExceeded(f"probe budget {self.budget} exhausted")
            return None
        self.count += 1
        return self.__pipeline.observe(tuple(assignment))

    @property
    def remaining(self) -> Optional[int]:
        return None if self.budget is None else max(0, self.budget - self.count)
