"""Phase-1 discovery oracle.

The agent submits its OWN probe documents and gets back the rendered pages
(engine A) for those probes only. This is the sole channel through which the
hidden cfg/semantics are observable -- it forces the discovery chain.

Soundness invariants (both enforced here, verified in private/phase_demo.py):
  * REJECTS any probe that matches a graded-corpus document (by canonical hash),
    so the oracle can never be used to read the answers for the graded set.
  * Bounded call budget (a probe is an ACTION; unbounded probing would let the
    agent brute-force). Budget exhaustion ends Phase 1.

The oracle exists ONLY in Phase 1. In Phase 2 the generator/ package (this module
and engine A) is purged from the container, so an agent engine that tries to reach
it at grade time fails -- see the isolation cheat in private/phase_demo.py.

# PAGEFORGE_ORACLE_SENTINEL_7b1e9f4a
"""
from __future__ import annotations
import hashlib

from . import pfcore as C
from . import engine as A


def canon_hash(doc) -> str:
    """Stable content hash of a document (via the plain-data form)."""
    return hashlib.blake2b(repr(C.to_plain(doc)).encode("utf-8"),
                           digest_size=16).hexdigest()


class ProbeError(Exception):
    pass


class ProbeOracle:
    def __init__(self, cfg, corpus_docs, budget=64):
        self._cfg = cfg
        self._forbidden = {canon_hash(d) for d in corpus_docs}
        self._budget = budget
        self.calls = 0

    def remaining(self) -> int:
        return self._budget - self.calls

    def probe(self, doc) -> list:
        """Return engine A's rendered pages for an agent-chosen probe doc."""
        if self.calls >= self._budget:
            raise ProbeError("probe budget exhausted (%d)" % self._budget)
        if canon_hash(doc) in self._forbidden:
            raise ProbeError("refused: probe matches a graded-corpus document")
        self.calls += 1
        return A.layout(doc, self._cfg)[0]
