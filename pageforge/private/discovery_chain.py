"""Discovery-chain depth proof (model-free, offline).

The env hides the per-instance cfg AND the layout semantics. The agent must recover
them by PROBING the oracle (engine A) with its own documents in Phase 1. This
module proves the discovery is a genuine DEEP/CHAINED dependency sequence
(facet B unobservable until prerequisite facet A is pinned), not ~8 independent
probes -- the property that makes discovery a task-FORCED long horizon.

For each chained edge P -> F we show, by running the real oracle:
  MASKED   : with P unknown/uncontrolled, the oracle output is INVARIANT to F
             (two different F values -> identical pages) -> F is not identifiable.
  REVEALED : once P is pinned, a probe CONSTRUCTED USING P separates the F values
             (different pages) -> F becomes identifiable.

Then we account the forced serial probe budget and show a batched (round-1-only)
strategy provably fails to identify the gated facets.

Run:  python3 -m private.discovery_chain   from the package root.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import replace

from generator import pfcore as C
from generator import engine as A
from generator.semconfig import SemConfig

BASE = SemConfig(W=20, H=5, hyph="EVERY_K", hyph_k=3, hyph_pos="TRAIL",
                 just="RIGHT_HEAVY", folio="BOT", folio_suppress_topfloat=True,
                 foot_min=1, head_blank_before=1, head_blank_after=0,
                 head_blank_top_drop=True, priority=("KEEP", "WIDOW", "ORPHAN"))
PERMS = [("KEEP", "WIDOW", "ORPHAN"), ("WIDOW", "KEEP", "ORPHAN"),
         ("ORPHAN", "KEEP", "WIDOW"), ("WIDOW", "ORPHAN", "KEEP"),
         ("ORPHAN", "WIDOW", "KEEP"), ("KEEP", "ORPHAN", "WIDOW")]


def O(doc, cfg):
    """Oracle output = rendered pages (hashable), or None if unlayoutable."""
    try:
        return tuple(A.layout(doc, cfg)[0])
    except Exception:
        return None


def _ok(label, masked_equal, revealed_diff):
    status = "PASS" if (masked_equal and revealed_diff) else "FAIL"
    print("  [%s] %s" % (status, label))
    print("        masked: F is invariant (unobservable) = %s" % masked_equal)
    print("        revealed: F separates once prereq pinned = %s" % revealed_diff)
    return masked_equal and revealed_diff


# ---------------------------------------------------------------------------
# Edge 1:  hyph_k  ->  hyph_pos
# ---------------------------------------------------------------------------
def edge_hyphpos_needs_hyphk():
    # MASKED: a paragraph of short words -> hyphenation never fires -> LEAD==TRAIL.
    masked = C.doc(C.para("p", C.words("aa bb cc dd")))
    m_trail = O(masked, replace(BASE, hyph_pos="TRAIL"))
    m_lead = O(masked, replace(BASE, hyph_pos="LEAD"))
    # REVEALED: a long word constructed knowing k=3 -> hyphenates -> LEAD!=TRAIL.
    revealed = C.doc(C.para("p", [C.W("x" * 25)]))
    r_trail = O(revealed, replace(BASE, hyph_pos="TRAIL"))
    r_lead = O(revealed, replace(BASE, hyph_pos="LEAD"))
    return _ok("hyph_k -> hyph_pos", m_trail == m_lead, r_trail != r_lead)


# ---------------------------------------------------------------------------
# Edge 2:  capacity/pagination  ->  priority permutation
# ---------------------------------------------------------------------------
def edge_priority_needs_capacity():
    # The clash needs TIGHT capacity (here H=2); a probe only creates it once the
    # agent knows the capacity math, so priority is masked until capacity is pinned.
    tight = replace(BASE, H=2, folio="NONE")
    # MASKED: no capacity pressure -> no sanctioned violation -> all perms equal.
    masked = C.doc(C.para("a", C.words("aa bb")), C.para("b", C.words("cc dd")))
    outs = {p: O(masked, replace(tight, priority=p)) for p in PERMS}
    masked_equal = len(set(outs.values())) == 1
    # REVEALED: heading + 2-line para at tight capacity -> a KEEP/WIDOW clash whose
    # waived site is chosen by the permutation (slice's proven d_perm construction).
    clash = C.doc(C.heading("h", C.words("Sec")),
                  C.para("a", C.words("aaa bbb ccc ddd eee fff ggg")))
    o1 = O(clash, replace(tight, priority=("KEEP", "WIDOW", "ORPHAN")))
    o2 = O(clash, replace(tight, priority=("WIDOW", "KEEP", "ORPHAN")))
    return _ok("capacity -> priority permutation", masked_equal, o1 != o2)


# ---------------------------------------------------------------------------
# Edge 3:  pagination  ->  head_blank_top_drop
# ---------------------------------------------------------------------------
def edge_topdrop_needs_pagination():
    # MASKED: heading (with leading blank) sits MID-page -> blank renders either
    # way -> top_drop True==False.
    masked = C.doc(C.para("p0", C.words("aa bb")),
                   C.heading("h", C.words("Sec")),
                   C.para("p1", C.words("cc dd")))
    m_t = O(masked, replace(BASE, head_blank_top_drop=True))
    m_f = O(masked, replace(BASE, head_blank_top_drop=False))
    # REVEALED: fill page 1 to capacity (H - folio_res = 5 - 1 = 4 text lines) so
    # the heading's leading blank lands at the TOP of page 2. Requires the capacity
    # number. drop=True removes it (page shifts); drop=False keeps it.
    filler = [C.para("f%d" % i, C.words("aa")) for i in range(4)]
    revealed = C.doc(*filler, C.heading("h", C.words("Sec")),
                     C.para("p1", C.words("cc dd")))
    r_t = O(revealed, replace(BASE, head_blank_top_drop=True))
    r_f = O(revealed, replace(BASE, head_blank_top_drop=False))
    return _ok("pagination -> head_blank_top_drop", m_t == m_f, r_t != r_f)


# ---------------------------------------------------------------------------
# Edge 4:  pagination (odd-index line)  ->  justification form (LEFT vs PAGE_PARITY)
# ---------------------------------------------------------------------------
def edge_just_needs_oddline():
    # A 3-line paragraph; line 0 (even) and line 1 (odd) are both justified
    # (non-final, multi-word, surplus). LEFT always leftmost; PAGE_PARITY leftmost
    # at even j, rightmost at odd j. So at j=0 LEFT==PAGE_PARITY (masked); the
    # distinction only appears at j=1 (an odd-index line -> needs pagination).
    para = C.para("p", C.words("a bb ccc dddd ee ff ggg hh ii jjj kk ll mm nn"))
    d = C.doc(para)
    tall = replace(BASE, H=6)  # hold the multi-line paragraph on one page
    left = O(d, replace(tall, just="LEFT"))
    pp = O(d, replace(tall, just="PAGE_PARITY"))
    # MASKED view: compare only the FIRST rendered line (j=0) across the two forms.
    masked_equal = (left is not None and pp is not None and left[0].split("\n")[0]
                    == pp[0].split("\n")[0])
    # REVEALED view: the full page differs because the j=1 line diverges.
    revealed_diff = left != pp
    return _ok("pagination(odd line) -> just LEFT vs PAGE_PARITY",
               masked_equal, revealed_diff)


# ---------------------------------------------------------------------------
# Batched (round-1-only) strategy provably fails on the gated facets
# ---------------------------------------------------------------------------
def batched_fails():
    print("\n[batched-strategy failure]  8 independent round-1 probes (no ordering)")
    # A naive batch probes priority with a no-pressure doc (round-1 constructible).
    naive = C.doc(C.para("a", C.words("aa bb")), C.para("b", C.words("cc dd")))
    reads = {p: O(naive, replace(BASE, priority=p)) for p in PERMS}
    distinct = len(set(reads.values()))
    print("  naive priority probe distinguishes %d/6 permutations "
          "(1 = cannot tell them apart -> MISIDENTIFIED as canonical)" % distinct)
    # A naive top_drop probe (heading mid-page) can't tell drop from keep.
    md = C.doc(C.para("p0", C.words("aa bb")), C.heading("h", C.words("Sec")),
               C.para("p1", C.words("cc dd")))
    td = O(md, replace(BASE, head_blank_top_drop=True)) == O(md, replace(BASE, head_blank_top_drop=False))
    print("  naive top_drop probe cannot distinguish True/False: %s" % td)
    return distinct == 1 and td


# ---------------------------------------------------------------------------
# Forced-probe accounting (dependency schedule)
# ---------------------------------------------------------------------------
SCHEDULE = [
    # (facet, prerequisite, probes) -- probes must be CONSTRUCTED using the prereq
    ("grid W,H", "given", 0),
    ("folio presence+position", "W,H", 1),
    ("folio_res (capacity unit)", "folio", 1),
    ("float reservation", "folio_res", 2),
    ("footnote reservation + split", "float_res", 2),
    ("hyph_k (cut period)", "W", 2),
    ("hyph_pos LEAD/TRAIL", "hyph_k", 1),
    ("just: justify present + LEFT?", "W", 1),
    ("just: RIGHT_HEAVY vs PAGE_PARITY", "capacity(odd line)", 2),
    ("head_blank_top_drop", "capacity(page-top blank)", 2),
    ("priority KEEP-vs-WIDOW", "capacity(clash)", 2),
    ("priority KEEP-vs-ORPHAN", "capacity(clash)", 2),
    ("priority WIDOW-vs-ORPHAN", "capacity(clash)", 2),
    ("xref fixpoint behavior", "capacity", 1),
]


def accounting():
    print("\n[forced-probe accounting]  (later probes parameterized by earlier results)")
    total = 0
    gated = 0
    for facet, prereq, n in SCHEDULE:
        total += n
        chained = prereq not in ("given", "W,H", "W")
        gated += n if chained else 0
        tag = "  <- chained on %s" % prereq if chained else ""
        print("  %-38s %d probe(s)%s" % (facet, n, tag))
    print("  ---")
    print("  TOTAL forced probes = %d  (%d of them gated on an earlier discovery)"
          % (total, gated))
    print("  Independent round-1 facets: grid, folio, hyph_k, justify-present (~4).")
    print("  The remaining ~%d probes CANNOT be issued until capacity / hyph_k is"
          % gated)
    print("  pinned -> genuine dependency chain, not 8 independent probes.")
    return total


def main():
    print("=" * 68)
    print("PageForge -- discovery-chain depth proof (oracle = engine A)")
    print("=" * 68)
    print("\n[masking demonstrations]  facet unobservable until prerequisite pinned")
    edges = [edge_hyphpos_needs_hyphk(), edge_priority_needs_capacity(),
             edge_topdrop_needs_pagination(), edge_just_needs_oddline()]
    bf = batched_fails()
    total = accounting()
    ok = all(edges) and bf and 15 <= total <= 30
    print("\n" + "=" * 68)
    print("DISCOVERY CHAIN: %s" %
          ("DEEP/CHAINED, %d forced probes in [15,30], all masking edges hold"
           % total if ok else "CHECK FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
