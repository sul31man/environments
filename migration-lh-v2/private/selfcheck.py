"""migration-lh-v2 OFFLINE soundness proof (no Docker, no billing).

Proves, over N instances, the load-bearing soundness claims:
  1. IDENTIFIABILITY  -- the worked samples uniquely pin theta on every used cell
     (solver recovers theta|U exactly; local injectivity: perturbing any used cell
     changes a sample output).
  2. NON-ENUMERABILITY -- |Theta| entropy >= 64 bits (offline brute-force infeasible),
     so a leaked (salt, streams, final_hash) confers no shortcut.
  3. TWO-CONDITION      -- textbook prior (sum / LWW-all-eligible) MISSES (hash mismatch,
     reward 0) while theta recovered-from-samples HITS (hash match, reward 1.0). Same
     harness, opposite outcomes -> a real positive+negative control.
  4. DIFFERENTIAL ORACLE -- (a) a transposed applier (reduce_theta_b, collect-then-fold),
     and (b) a BLIND independent oracle (oracle_blind, authored from the spec alone by a
     separate model, sharing NO code with the reducer) both agree with the reference
     byte-for-byte. (a) catches loop/transcription errors; (b) validates the shared
     keep-filter / causal-order / feature-schema core, not just the loop structure.

Run:  python3 private/selfcheck.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from mig_lh import dataplane as dp
from mig_lh import generator as gen
from mig_lh.dataplane_core import term_hash

sys.path.insert(0, HERE)
import oracle_blind   # BLIND independent oracle: NO shared code with dp/gen (authored from spec)

N = 64
SALT = b"\x11" * 32   # fixed for the proof; in serve the salt is per-deploy (and kept out of the blob)


def used_key(theta, cells):
    return {c: (theta.counter[c], theta.head_elig[c]) for c in sorted(cells)}


def _decode_sel(out):
    if out["head"] == {"v": 111}:
        return True, "FIRST"
    if out["head"] == {"v": 222}:
        return True, "LAST"
    return False, None


def selector_probe(inst):
    """Pin FIRST/LAST with a dedicated 2-eligible-head record. Selector matters iff a
    single record can hold >=2 eligible head candidates, which requires >=1 eligible
    REST cell (a FIRST cell can appear at most once per record). Construction: a
    head-less FIRST primer + two writes in the SAME eligible REST cell, heads 111 & 222.
    Returns (False, None) only when NO eligible REST cell exists -> selector is a genuine
    don't-care (records never have >=2 candidates)."""
    th = inst.theta
    rests = [c for c in inst.used_cells if gen.cell_features(c)[3] == "REST" and th.head_elig[c]]
    if not rests:
        return False, None
    rid = f"rec-sel-{inst.seed}"
    ap, asr, aec, _ = gen.cell_features(gen.ANCHOR)
    o, s, e, _ = gen.cell_features(rests[0])
    w0 = gen._mut(rid, 0, ap, gen._lease_for(aec), 1, {}, gen._fo(1, None, asr), rid+"-0", 0, 902)   # headless primer
    w1 = gen._mut(rid, 0, o, gen._lease_for(e), 2, {"0": 1}, gen._fo(None, 111, s), rid+"-1", 1, 903)
    w2 = gen._mut(rid, 0, o, gen._lease_for(e), 3, {"0": 2}, gen._fo(None, 222, s), rid+"-2", 2, 904)
    return _decode_sel(dp.reduce_theta([w0, w1, w2], gen.CONTEXT, th)[rid]["value"])


def local_injective(inst) -> bool:
    """For each used cell, perturbing its counter mode (or head eligibility) must change
    at least one sample output -> the samples locally determine theta on U."""
    th = inst.theta
    base_outputs = [s["output_value"] for s in inst.samples]
    for (rid, cell, base, delta, kind), samp in zip(inst._iso_meta, inst.samples):
        # perturb counter mode
        for alt in dp.COUNTER_MODES:
            if alt == th.counter[cell]:
                continue
            c2 = list(th.counter); c2[cell] = alt
            th2 = dp.Theta(tuple(c2), th.head_elig, th.head_sel)
            out2 = dp.reduce_theta(samp["mutations"], gen.CONTEXT, th2)[rid]["value"]
            if out2["counter"] == samp["output_value"]["counter"]:
                return False  # ambiguous: alt mode reproduces the same output
        # perturb head eligibility
        e2 = list(th.head_elig); e2[cell] = not e2[cell]
        th3 = dp.Theta(th.counter, tuple(e2), th.head_sel)
        out3 = dp.reduce_theta(samp["mutations"], gen.CONTEXT, th3)[rid]["value"]
        if out3["head"] == samp["output_value"]["head"]:
            return False
    return True


def main():
    ent = dp.theta_entropy_bits()
    print(f"=== migration-lh-v2 soundness proof (N={N}) ===")
    print(f"cells K={dp.K}  |Theta| entropy = {ent:.1f} bits  (non-enumerable: {ent >= 64})\n")

    ident_ok = inj_ok = diff_ok = blind_ok = pos_ok = neg_ok = sel_pinned = sel_dontcare = 0
    used_hist = []

    for seed in range(1000, 1000 + N):
        inst = gen.build_instance(seed)
        used = inst.used_cells
        used_hist.append(len(used))

        # 1. identifiability: recovered theta|U == true theta|U
        rec = gen.solve_theta(inst)
        if used_key(rec, used) == used_key(inst.theta, used):
            ident_ok += 1
        if local_injective(inst):
            inj_ok += 1

        # selector
        pinned, sel = selector_probe(inst)
        if pinned:
            sel_pinned += 1
            rec_sel = sel
        else:
            sel_dontcare += 1
            rec_sel = "FIRST"   # don't-care for this instance's eval terminal

        # 3. two-condition on the EVAL terminal, graded by hash
        true_term = dp.graded_terminal(dp.reduce_theta(inst.eval_muts, gen.CONTEXT, inst.theta))
        final_hash = term_hash(SALT, true_term)

        # recovered theta (correct on U, don't-care elsewhere; selector as pinned)
        rec_full = dp.Theta(rec.counter, rec.head_elig, rec_sel)
        rec_term = dp.graded_terminal(dp.reduce_theta(inst.eval_muts, gen.CONTEXT, rec_full))
        if term_hash(SALT, rec_term) == final_hash:
            pos_ok += 1

        # textbook prior: counter = sum (all ADD), head = all-eligible LWW (LAST)
        textbook = dp.Theta(tuple([dp.ADD] * dp.K), tuple([True] * dp.K), "LAST")
        tb_term = dp.graded_terminal(dp.reduce_theta(inst.eval_muts, gen.CONTEXT, textbook))
        if term_hash(SALT, tb_term) != final_hash:
            neg_ok += 1

        # 4. differential oracle: fold == transposed applier, byte for byte
        a = dp.graded_terminal(dp.reduce_theta(inst.eval_muts, gen.CONTEXT, inst.theta))
        b = dp.graded_terminal(gen.reduce_theta_b(inst.eval_muts, gen.CONTEXT, inst.theta))
        if term_hash(SALT, a) == term_hash(SALT, b):
            diff_ok += 1

        # 4b. BLIND independent oracle: NO shared code with dp/gen (from spec alone) --
        # validates the shared keep/order/schema core, not just the loop structure.
        td = {"counter": list(inst.theta.counter),
              "head_elig": [int(x) for x in inst.theta.head_elig],
              "head_sel": inst.theta.head_sel}
        c = dp.graded_terminal(oracle_blind.reduce(inst.eval_muts, gen.CONTEXT, td))
        if term_hash(SALT, a) == term_hash(SALT, c):
            blind_ok += 1

    print(f"1. identifiability  (recovered theta|U == true)        : {ident_ok}/{N}")
    print(f"   local injectivity (samples pin each used cell)      : {inj_ok}/{N}")
    print(f"2. non-enumerability (entropy >= 64 bits)              : {ent:.1f} bits")
    print(f"3. two-condition  positive (recovered theta HITS)      : {pos_ok}/{N}")
    print(f"   two-condition  negative (textbook prior MISSES)     : {neg_ok}/{N}")
    print(f"4. differential oracle (fold == transposed)            : {diff_ok}/{N}")
    print(f"   blind independent oracle (NO shared code)           : {blind_ok}/{N}")
    print(f"   selector pinned / don't-care                        : {sel_pinned} / {sel_dontcare}")
    print(f"   used cells per instance: min={min(used_hist)} max={max(used_hist)} avg={sum(used_hist)/N:.1f}")

    green = (ident_ok == N and inj_ok == N and pos_ok == N and neg_ok == N
             and diff_ok == N and blind_ok == N and ent >= 64)
    print("\n" + ("V2 SOUNDNESS CORE: ALL GREEN" if green else "V2 SOUNDNESS CORE: SEE NON-GREEN ABOVE"))
    sys.exit(0 if green else 1)


if __name__ == "__main__":
    main()
