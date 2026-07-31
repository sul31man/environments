"""PageForge offline soundness proof (no model or API key).

  - gold FRR: every gold submission scores 1.0 (>= strict) -> FRR = 0.
  - cheat FAR: a battery of cheats must all score < strict; FAR Wilson-95 upper
    bound < 5%.
  - reconstructed-agent regrade: reconstruct a real agent submission (an
    independent engine) and regrade through the grade-by-value path.
  - enumerator difficulty: reproduce the enumerator-hard number across a sample.

Run:  python3 -m private.soundness   from the package root.
"""
from __future__ import annotations
import sys, os, math, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import instance as I
from generator import grade as G
from generator import engine as A
from generator import interp_b as B

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
    print("PageForge soundness proof  (sample = %d eval instances)" % len(SAMPLE))
    print("=" * 64)
    insts = [I.generate(i, "eval") for i in SAMPLE]

    # 1. gold FRR
    gold_scores = [G.score(G.gold_fn, ins.corpus, ins.cfg)[0] for ins in insts]
    frr_reject = sum(1 for s in gold_scores if s < STRICT)
    print("\n[gold / FRR]")
    print("  gold reward min=%.4f max=%.4f  (exact 1.0 expected)"
          % (min(gold_scores), max(gold_scores)))
    lo, hi = wilson(frr_reject, len(gold_scores))
    print("  FRR = %d/%d  Wilson95=[%.3f, %.3f]" % (frr_reject, len(gold_scores), lo, hi))

    # 2. cheat FAR
    print("\n[cheats / FAR]  (each must score < %.2f)" % STRICT)
    cheat_defs = [
        ("constant", lambda ins: G.cheat_constant),
        ("shape", lambda ins: G.cheat_shape),
        ("enumerator", lambda ins: G.enumerator_fn),
        ("hardcoded", lambda ins: G.cheat_hardcoded(
            [(d, A.layout(d, ins.cfg)[0]) for d, _c in ins.corpus[:2]])),
    ]
    accepts = 0
    trials = 0
    worst = {}
    for name, mk in cheat_defs:
        mx = 0.0
        for ins in insts:
            r, _ = G.score(mk(ins), ins.corpus, ins.cfg)
            trials += 1
            if r >= STRICT:
                accepts += 1
            mx = max(mx, r)
        worst[name] = mx
        print("  %-11s worst reward over sample = %.4f" % (name, mx))
    lo, hi = wilson(accepts, trials)
    print("  FAR = %d/%d accepts  Wilson95=[%.3f, %.3f]  (upper must be < 0.05)"
          % (accepts, trials, lo, hi))

    # 3. reconstructed-agent regrade (grade-by-value path)
    print("\n[reconstructed-agent regrade]")
    # engine B is an independent faithful implementation = a 'correct agent'.
    reb = [G.score(lambda d, c: B.layout(d, c)[0], ins.corpus, ins.cfg)[0] for ins in insts]
    print("  independent correct agent (engine B) reward min=%.4f  (expect 1.0)"
          % min(reb))
    # an independent WRONG agent (enumerator) regrades below strict
    rew = [G.score(G.enumerator_fn, ins.corpus, ins.cfg)[0] for ins in insts]
    print("  independent wrong agent (enumerator) reward mean=%.4f max=%.4f"
          % (statistics.mean(rew), max(rew)))

    # 4. difficulty (enumerator-hard) evidence
    print("\n[difficulty / enumerator-hard]")
    enums = [ins.report["enum"] for ins in insts]
    print("  enumerator reward: min=%.3f mean=%.3f max=%.3f  (all < %.2f: %s)"
          % (min(enums), statistics.mean(enums), max(enums), STRICT, all(e < STRICT for e in enums)))
    sanct = [ins.report["sanctioned"] for ins in insts]
    print("  sanctioned violations/instance: min=%d mean=%.1f" % (min(sanct), statistics.mean(sanct)))

    print("\n" + "=" * 64)
    ok = (frr_reject == 0 and accepts == 0 and min(reb) >= STRICT
          and all(e < STRICT for e in enums))
    print("SOUNDNESS: %s" % ("ALL CLEAR" if ok else "FAILURES PRESENT"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
