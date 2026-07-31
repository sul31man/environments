"""OOD proxy (model-free): does a FAMILIAR-typesetting solution score LOW while
gold scores 1.0?

The discovery phase (Phase 1) adds long-horizon but is NOT inherently OOD --
probing an oracle to infer config is in-distribution deduction. OOD must live in
the IMPLEMENTATION semantics: a solution that applies real-world (TeX/CSS/Word)
typesetting rules must produce WRONG pages, or the env is long-horizon-only, not
long-horizon-OOD.

Fair, conservative test (no strawman bugs): take the CORRECT engine A and run it
with the anti-prior FORM facets replaced by their familiar real-world defaults,
holding every STRUCTURAL parameter (W, H, folio position, foot_min, hyph_k,
head_blank_before) at the true value. This isolates exactly the anti-prior-ness of
the forms and gives the familiar prior the best possible chance:

  familiar substitution        gold (anti-prior, per-instance)
  --------------------------   -------------------------------
  just = LEFT (ragged/even)    RIGHT_HEAVY | PAGE_PARITY
  hyph_pos = TRAIL (std)       TRAIL | LEAD
  priority = KEEP,WIDOW,ORPHAN 5 non-canonical permutations
  folio_suppress = False       True (suppress folio on top-float page)
  head_blank_top_drop = True   True | False

If familiar scores LOW (<< gold 1.0, and not above the enumerator floor by much)
-> the semantics are genuinely anti-prior; the env is OOD.
If familiar scores HIGH -> priors do NOT misfire; the env is long-horizon but NOT OOD,
and the anti-prior semantics must be strengthened. Report honestly either way.

Run:  python3 -m private.ood_proxy    from the package root.
"""
from __future__ import annotations
import sys, os, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import replace

from generator import instance as I
from generator import grade as G
from generator import engine as A

FAMILIAR = dict(
    just="LEFT",
    hyph_pos="TRAIL",
    priority=("KEEP", "WIDOW", "ORPHAN"),
    folio_suppress_topfloat=False,
    head_blank_top_drop=True,
)


def familiar_fn(doc, cfg):
    """Correct engine, familiar FORMS, true structural params. No strawman."""
    fam = replace(cfg, **FAMILIAR)
    try:
        return A.layout(doc, fam)[0]
    except Exception:
        return []


def main():
    print("=" * 64)
    print("PageForge -- OOD proxy (familiar prior vs anti-prior gold)")
    print("=" * 64)
    gold, fam, enum = [], [], []
    n_diff_forms = 0
    for i in range(50):
        ins = I.generate(i, "eval")
        gold.append(G.score(G.gold_fn, ins.corpus, ins.cfg)[0])
        fam.append(G.score(familiar_fn, ins.corpus, ins.cfg)[0])
        enum.append(G.score(G.enumerator_fn, ins.corpus, ins.cfg)[0])
        # how many form facets actually differ from familiar for this instance
        c = ins.cfg
        d = sum([c.just != "LEFT", c.hyph_pos != "TRAIL",
                 tuple(c.priority) != ("KEEP", "WIDOW", "ORPHAN"),
                 c.folio_suppress_topfloat is not False,
                 c.head_blank_top_drop is not True])
        n_diff_forms += d
    print("\n  gold     : mean=%.4f min=%.4f  (expect 1.0)" % (statistics.mean(gold), min(gold)))
    print("  FAMILIAR : mean=%.4f min=%.4f max=%.4f" % (statistics.mean(fam), min(fam), max(fam)))
    print("  enumerator floor: mean=%.4f  (branch-per-family, CORRECT forms)" % statistics.mean(enum))
    print("  avg anti-prior form facets differing per instance: %.2f / 5" % (n_diff_forms / 50))
    fam_mean = statistics.mean(fam)
    print("\n  VERDICT:", end=" ")
    if fam_mean < 0.5 * min(gold):
        print("familiar prior scores LOW (%.3f << gold 1.0) -> semantics are\n"
              "  genuinely ANTI-PRIOR; the env clears the OOD bar (long-horizon AND OOD)." % fam_mean)
    else:
        print("familiar prior scores HIGH (%.3f) -> priors do NOT misfire; the env is\n"
              "  long-horizon but NOT OOD. Strengthen anti-prior semantics before the\n"
              "  OOD claim. (Honest negative result.)" % fam_mean)


if __name__ == "__main__":
    main()
