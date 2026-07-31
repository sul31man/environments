"""PageForge -- full-scale proofs across all 50 eval instances (offline).

Confirms the prototype properties HOLD PER INSTANCE at full scale:
  1. composition core: A==B (0 mismatches), enumerator in band, gold 1.0.
  2. discovery chain deep/chained on EVERY instance (masking holds + batched fails).
  3. OOD: the fair-familiar solution passes ZERO of 50.
  4. difficulty-consistency gate per instance (reroll any that fall out).

Run:  python3 -m private.full_check   from the package root.
"""
from __future__ import annotations
import sys, os, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import replace

from generator import instance as I
from generator import grade as G
from generator import engine as A
from generator import interp_b as B
from generator import pfcore as C
from generator.semconfig import SemConfig
from private.ood_proxy import familiar_fn

CANON = ("KEEP", "WIDOW", "ORPHAN")
PERMS = [("KEEP", "WIDOW", "ORPHAN"), ("WIDOW", "KEEP", "ORPHAN"),
         ("ORPHAN", "KEEP", "WIDOW"), ("WIDOW", "ORPHAN", "KEEP"),
         ("ORPHAN", "WIDOW", "KEEP"), ("KEEP", "ORPHAN", "WIDOW")]
STRICT = 0.95


def _pages(doc, cfg):
    try:
        return tuple(A.layout(doc, cfg)[0])
    except Exception:
        return None


# ---- per-instance discovery-chain evidence ---------------------------------
def masked_priority(cfg):
    """No-pressure probe -> identical pages across ALL permutations (priority
    unobservable without a capacity-pressure probe)."""
    d = C.doc(C.para("a", C.words("aa bb")), C.para("b", C.words("cc dd")))
    return len({_pages(d, replace(cfg, priority=p)) for p in PERMS}) == 1


def priority_observable(inst):
    """Is the permutation observable on this instance -- i.e., does SOME doc's
    sanctioned violation depend on the rule ordering? (If not, the permutation is a
    DON'T-CARE: unobservable AND irrelevant to gold, so nothing to discover.)"""
    cfg = inst.cfg
    for d, _ in inst.corpus:
        if A.waived_sites(d, cfg):
            if len({_pages(d, replace(cfg, priority=p)) for p in PERMS}) > 1:
                return True
    return False


def masked_hyphpos(cfg):
    """A doc whose words never hyphenate -> TRAIL==LEAD (hyph_pos unobservable
    until hyphenation is triggered, which needs hyph_k)."""
    d = C.doc(C.para("p", C.words("aa bb cc dd")))
    return _pages(d, replace(cfg, hyph_pos="TRAIL")) == _pages(d, replace(cfg, hyph_pos="LEAD"))


def revealed_hyphpos(cfg):
    """A long word hyphenates -> TRAIL != LEAD once triggered."""
    d = C.doc(C.para("p", [C.W("x" * (cfg.W + 6))]))
    return _pages(d, replace(cfg, hyph_pos="TRAIL")) != _pages(d, replace(cfg, hyph_pos="LEAD"))


def batched_misidentifies(cfg):
    """The no-pressure (round-1) probe reads priority as canonical; eval configs are
    non-canonical, so a batched strategy MISIDENTIFIES priority on this instance."""
    return tuple(cfg.priority) != CANON  # and masked_priority holds -> unrecoverable


def chain_deep(inst):
    """Robust per-instance chain evidence: two independent gated facets.
      - priority is MASKED without a capacity-pressure probe (batched can't get it);
      - hyph_pos is MASKED until hyph_k is pinned, and REVEALED once it is.
    (Priority's revealed side is an observability nuance handled separately; where
    it is a don't-care it neither can be nor needs to be discovered.)"""
    cfg = inst.cfg
    return (masked_priority(cfg) and masked_hyphpos(cfg) and revealed_hyphpos(cfg))


def main():
    print("=" * 68)
    print("PageForge -- full-scale proofs over 50 eval instances")
    print("=" * 68)
    insts = [I.generate(i, "eval") for i in range(50)]

    # 1. composition core
    ab_bad = 0
    enums, golds = [], []
    for ins in insts:
        for d, _ in ins.corpus:
            if A.layout(d, ins.cfg)[0] != B.layout(d, ins.cfg)[0]:
                ab_bad += 1
        enums.append(G.score(G.enumerator_fn, ins.corpus, ins.cfg)[0])
        golds.append(G.score(G.gold_fn, ins.corpus, ins.cfg)[0])
    print("\n[1 composition core]")
    print("  A==B mismatches over 50 corpora : %d  (want 0)" % ab_bad)
    print("  enumerator mean/min/max         : %.4f / %.4f / %.4f"
          % (statistics.mean(enums), min(enums), max(enums)))
    print("  gold min                        : %.4f  (want 1.0)" % min(golds))

    # 2. discovery chain deep + batched fails, per instance
    deep = [chain_deep(ins) for ins in insts]
    batched = [batched_misidentifies(ins.cfg) for ins in insts]
    observable = [priority_observable(ins) for ins in insts]
    print("\n[2 discovery chain -- per instance]")
    print("  masking holds (chain deep) on   : %d/50 instances" % sum(deep))
    print("  batched strategy MISIDENTIFIES priority on : %d/50 instances" % sum(batched))
    print("  priority observable / don't-care : %d observable, %d don't-care "
          "(unobservable AND irrelevant to gold)" % (sum(observable), 50 - sum(observable)))

    # 3. OOD: familiar passes zero
    fam = [G.score(familiar_fn, ins.corpus, ins.cfg)[0] for ins in insts]
    fam_pass = sum(1 for r in fam if r >= STRICT)
    print("\n[3 OOD -- fair-familiar proxy]")
    print("  familiar mean/min/max           : %.4f / %.4f / %.4f"
          % (statistics.mean(fam), min(fam), max(fam)))
    print("  familiar instances PASSING (>=0.95) : %d/50  (want 0)" % fam_pass)

    # 4. difficulty-consistency gate (reroll any that fall out)
    fell_out = []
    for ins, e, g, dp, fr in zip(insts, enums, golds, deep, fam):
        ok = (abs(g - 1.0) < 1e-9 and 0.15 <= e < STRICT and dp and fr < STRICT)
        if not ok:
            fell_out.append(ins.index)
    print("\n[4 difficulty-consistency gate over 50]")
    print("  instances passing gate (gold=1, enum in band, chain deep, OOD holds): %d/50"
          % (50 - len(fell_out)))
    print("  instances to REROLL             : %s" % (fell_out or "none"))

    ok = (ab_bad == 0 and min(golds) == 1.0 and all(deep) and all(batched)
          and fam_pass == 0 and not fell_out
          and abs(statistics.mean(enums) - 0.4095) < 1e-3)
    print("\n" + "=" * 68)
    print("FULL-SCALE: %s" % ("ALL PROPERTIES HOLD ACROSS 50" if ok else "CHECK FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
