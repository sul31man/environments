"""PageForge -- consolidated soundness receipt (offline).

Covers the two-phase verifier soundness on top of the composition core, adding the
two-phase isolation checks:
  * FAR/FRR with Wilson 95% intervals, >=4 cheat classes (unchanged core).
  * NEW oracle-reader-at-grade-time cheat: an engine that imports the oracle in
    Phase 2 fails closed (ModuleNotFoundError) -> reward 0.
  * Phase-1 probe oracle is unreachable in Phase 2; it refuses graded-corpus docs
    and enforces the probe budget.

Run:  python3 -m private.phase_soundness   from the package root.
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import instance as I
from generator import grade as G
from generator import engine as A
from private import phase_demo as PD

STRICT = G.STRICT
SAMPLE = list(range(25))


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def main():
    print("=" * 64)
    print("PageForge -- soundness receipt  (sample = %d)" % len(SAMPLE))
    print("=" * 64)
    insts = [I.generate(i, "eval") for i in SAMPLE]

    # FRR
    gold = [G.score(G.gold_fn, ins.corpus, ins.cfg)[0] for ins in insts]
    frr = sum(1 for s in gold if s < STRICT)
    lo, hi = wilson(frr, len(gold))
    print("\n[FRR] gold min=%.4f  FRR=%d/%d  Wilson95=[%.3f, %.3f]"
          % (min(gold), frr, len(gold), lo, hi))

    # FAR (4 cheat classes, offline)
    cheats = [("constant", lambda ins: G.cheat_constant),
              ("shape", lambda ins: G.cheat_shape),
              ("enumerator", lambda ins: G.enumerator_fn),
              ("hardcoded", lambda ins: G.cheat_hardcoded(
                  [(d, A.layout(d, ins.cfg)[0]) for d, _ in ins.corpus[:2]]))]
    accepts = trials = 0
    print("\n[FAR] (each cheat class must score < %.2f)" % STRICT)
    for name, mk in cheats:
        mx = 0.0
        for ins in insts:
            r, _ = G.score(mk(ins), ins.corpus, ins.cfg)
            trials += 1
            accepts += (r >= STRICT)
            mx = max(mx, r)
        print("  %-11s worst = %.4f" % (name, mx))
    lo, hi = wilson(accepts, trials)
    print("  FAR = %d/%d  Wilson95=[%.3f, %.3f]  (upper < 0.05: %s)"
          % (accepts, trials, lo, hi, hi < 0.05))

    # NEW isolation cheat + phase-1 properties (reuse the proven phase_demo logic)
    print("\n[isolation -- Phase 1/2]")
    p1 = all(PD.phase1(I.generate(i, "eval")) for i in range(1))
    p2 = all(PD.phase2(I.generate(i, "eval")) for i in range(3))
    print("  phase-1 (probe works, corpus refused, budget) : %s" % p1)
    print("  phase-2 (faithful=1.0, oracle-reader cheat purged->0) : %s" % p2)

    ok = (frr == 0 and accepts == 0 and hi < 0.05 and p1 and p2)
    print("\n" + "=" * 64)
    print("TWO-PHASE SOUNDNESS: %s" % ("ALL CLEAR" if ok else "FAILURES PRESENT"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
