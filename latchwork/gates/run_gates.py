"""Latchwork Stage-0 offline gate battery + soundness receipt.

Runs every model-free gate against a LOCKED config and emits a receipt JSON +
human summary.  Fully offline.  Each gate maps to a soundness property.

Usage:  python gates/run_gates.py [n_seeds] [budget]
"""
import sys, os, json, time, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from latchwork.generator import GenConfig, generate
from latchwork.channel import Channel
from latchwork import solvers as S
from latchwork.evaluator_b import observe_from_keys
from latchwork.scoring import build_battery, score_keys
from latchwork.identifiability import check_instance
from latchwork.metrics import (solver_profile, summarize, shallow_pass_region,
                               class_form_mi, variant_indistinguishability)
from latchwork.locked import LOCKED_CONFIG, BAND, BUDGET, ACCEPT_THRESHOLD, ROTE_MARGIN

N_SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
BUDGET_ = int(sys.argv[2]) if len(sys.argv) > 2 else BUDGET
cfg = LOCKED_CONFIG
n, ng = cfg.n_fields, cfg.n_groups
SEEDS = list(range(N_SEEDS))


def wilson_upper(k, nobs, z=1.96):
    if nobs == 0:
        return 1.0
    p = k / nobs
    d = 1 + z * z / nobs
    center = p + z * z / (2 * nobs)
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * nobs)) / nobs)
    return (center + half) / d


results = {}
t0 = time.time()

# --- G0 determinism -----------------------------------------------------------
det_ok = all(generate("train", s, cfg).key() == generate("train", s, cfg).key()
             for s in SEEDS[:30])
results["G0_determinism"] = {"pass": det_ok}

# --- G10 differential A/B (no disagreements) ---------------------------------
dis = 0
for s in SEEDS[:20]:
    inst = generate("train", s, cfg)
    keys = list(inst.pipeline.key())
    rng = random.Random(7 + s)
    for _ in range(3000):
        a = tuple(rng.randrange(cfg.domain) for _ in range(n))
        if inst.pipeline.observe(a) != observe_from_keys(keys, a, n, ng):
            dis += 1
results["G10_differential_AB"] = {"pass": dis == 0, "disagreements": dis}

# --- G1 feasibility / gold=1.0 ; G2 identifiability ; G8 load-bearing ---------
gold_fail = 0
ident_fail = 0
worst_miss = 0.0
batteries = {}
for s in SEEDS:
    inst = generate("train", s, cfg)
    battery = build_battery(inst, n_per_stratum=24)
    batteries[s] = (inst, battery)
    g, _ = score_keys(list(inst.pipeline.key()), battery, n, ng)
    if abs(g - 1.0) > 1e-9:
        gold_fail += 1
    rep = check_instance(inst, battery=battery)
    if not rep["identifiable"]:
        ident_fail += 1
    worst_miss = max(worst_miss, max(ps["miss_score"] for ps in rep["per_stage"]))
results["G1_gold_1.0"] = {"pass": gold_fail == 0, "fails": gold_fail, "n": N_SEEDS}
results["G2_identifiability"] = {"pass": ident_fail == 0, "fails": ident_fail}
results["G8_load_bearing"] = {"pass": worst_miss < 0.95, "worst_single_stage_ablation": round(worst_miss, 3)}

# --- solver profile (shared by several gates); full solver on a subset -------
FULL_SUBSET = min(N_SEEDS, 20)
rows = solver_profile(cfg, SEEDS, BUDGET_, full_subset=FULL_SUBSET)
prof = summarize(rows)

# --- G3 FORCED (Gate i): no-probe walls < 0.95 on every instance -------------
results["G3_FORCED_no_probe_walls"] = {
    "pass": prof["no_probe"]["max"] < 0.95,
    "no_probe_max": round(prof["no_probe"]["max"], 3),
    "no_probe_mean": round(prof["no_probe"]["mean"], 3),
}

# --- G4 HARD + CHAINED (Gate ii) ---------------------------------------------
vind = variant_indistinguishability(cfg, SEEDS, BUDGET_)
results["G4a_variant_indistinguishable"] = {"pass": vind >= 0.50, "fraction": round(vind, 3)}
results["G4b_probe_and_fit_batch_below_band"] = {
    "pass": prof["batch"]["max"] < BAND[0],
    "batch_max": round(prof["batch"]["max"], 3), "batch_mean": round(prof["batch"]["mean"], 3),
}
results["G4c_rote_walls_with_margin"] = {
    "pass": prof["rote"]["max"] < BAND[0] - ROTE_MARGIN,
    "rote_max": round(prof["rote"]["max"], 3), "rote_mean": round(prof["rote"]["mean"], 3),
    "margin_below_band": round(BAND[0] - ROTE_MARGIN - prof["rote"]["max"], 3),
}

# --- G5 adaptive band (cond 6) + budget-insensitivity (cond 3) ---------------
results["G5_adaptive_band_and_budget_insensitive"] = {
    "pass": (BAND[0] <= prof["bounded_B"]["mean"] <= BAND[1]
             and abs(prof["bounded_B"]["mean"] - prof["bounded_2B"]["mean"]) < 0.08),
    "bounded_B_mean": round(prof["bounded_B"]["mean"], 3),
    "bounded_2B_mean": round(prof["bounded_2B"]["mean"], 3),
    "budget_delta": round(abs(prof["bounded_B"]["mean"] - prof["bounded_2B"]["mean"]), 3),
    "full_mean_recoverability": round(prof["full"]["mean"], 3),
}

# --- G6 class form-agnostic (cond 4) -----------------------------------------
mi = class_form_mi(cfg, range(200))
results["G6_class_form_agnostic"] = {"pass": mi["normalized_mi"] < 0.02,
                                     "normalized_MI": round(mi["normalized_mi"], 4)}

# --- G7 shallow-pass-region small (cond 5) -----------------------------------
spr = shallow_pass_region(cfg, SEEDS[:8])
results["G7_small_shallow_pass_region"] = {
    "pass": spr[2] < 0.05,
    "P_pass_ge_1": round(spr[1], 4), "P_pass_ge_2": round(spr[2], 4), "P_pass_ge_3": round(spr[3], 5),
}

# --- G9 probe-cheat floors ----------------------------------------------------
# probe-then-hardcode: output an all-accepting pipeline (memorize "accept").
hardcode_scores = []
for s in SEEDS:
    inst, battery = batteries[s]
    allpass = [("INTERVAL", 0, 0, cfg.domain - 1)] * cfg.n_stages
    hardcode_scores.append(score_keys(allpass, battery, n, ng)[0])
results["G9_probe_then_hardcode_floor"] = {
    "pass": max(hardcode_scores) < BAND[0],
    "hardcode_max": round(max(hardcode_scores), 3), "hardcode_mean": round(sum(hardcode_scores)/len(hardcode_scores), 3),
}

# --- G11 reconstruct-and-regrade (grade-by-value across the boundary) --------
regrade_ok = True
for s in SEEDS[:20]:
    inst, battery = batteries[s]
    keys = S.adaptive(Channel(inst, budget=BUDGET_), random.Random(s + 4), "bounded")
    in_proc = score_keys(keys, battery, n, ng)[0]
    blob = json.dumps(keys, default=list)                # serialize agent submission
    reloaded = json.loads(blob)
    reloaded = [tuple([k[0]] + [tuple(x) if isinstance(x, list) else x for x in k[1:]]) for k in reloaded]
    regraded = score_keys(reloaded, battery, n, ng)[0]
    if abs(in_proc - regraded) > 1e-9:
        regrade_ok = False
results["G11_reconstruct_and_regrade"] = {"pass": regrade_ok}

# --- G12 disjoint train/eval namespaces --------------------------------------
disjoint = all(generate("train", s, cfg).key() != generate("eval", s, cfg).key()
               for s in SEEDS[:30])
eval_gold_ok = True
for s in SEEDS[:20]:
    inst = generate("eval", s, cfg)
    battery = build_battery(inst, n_per_stratum=24)
    if abs(score_keys(list(inst.pipeline.key()), battery, n, ng)[0] - 1.0) > 1e-9:
        eval_gold_ok = False
results["G12_disjoint_namespaces"] = {"pass": disjoint and eval_gold_ok}

# --- FAR with Wilson upper (cheats scored as pass at ACCEPT_THRESHOLD) --------
cheat_scores = ([r["no_probe"] for r in rows] + [r["batch"] for r in rows]
                + [r["rote"] for r in rows] + hardcode_scores)
fa = sum(1 for v in cheat_scores if v >= ACCEPT_THRESHOLD)
results["FAR_cheats"] = {
    "pass": wilson_upper(fa, len(cheat_scores)) < 0.05,
    "false_accepts": fa, "n": len(cheat_scores),
    "wilson_upper": round(wilson_upper(fa, len(cheat_scores)), 4),
    "scope": "WEAK SOLVERS over the lossy channel only (no in-process access to "
             "the pipeline); see ISOLATION_requires_out_of_process for the "
             "in-process adversary and the required mitigation.",
}

# --- ISOLATION: in-process, the answer is READABLE (requires out-of-process) --
# The lossy channel stops a WEAK SOLVER (FAR above).  It does NOT stop an
# adversary that shares the PROCESS with the environment: the Channel holds the
# live pipeline in a name-mangled slot, and Python name mangling is not a
# security boundary -- an in-process attacker reads it and reconstructs perfectly
# (score 1.0).  This is EXPECTED, and is exactly why the environment MUST be
# served OUT OF PROCESS: at serve time the deployment purges the pipeline/
# generator source from the agent-reachable filesystem and exposes ONLY the probe
# socket, verified unreadable by a runtime leak-probe.  The in-process Channel is
# for TRUSTED offline evaluation only.  This item is NOT a channel-FAR weakness
# (it bypasses the channel); it records and demonstrates the serving requirement.
inproc = []
for s in SEEDS[:20]:
    inst, battery = batteries[s]
    ch = Channel(inst, budget=0)
    leaked = list(getattr(ch, "_Channel__pipeline").key())   # in-process read; no probe
    inproc.append(score_keys(leaked, battery, n, ng)[0])
results["ISOLATION_requires_out_of_process"] = {
    "pass": min(inproc) > 0.99,   # demonstration valid iff in-process read == 1.0
    "in_process_oracle_read_score": round(sum(inproc) / len(inproc), 3),
    "requirement": "Serve OUT OF PROCESS: purge the pipeline/generator source from "
                   "the agent-reachable filesystem, expose ONLY the probe socket, and "
                   "verify unreadable by a runtime leak-probe. The in-process Channel "
                   "is for trusted offline evaluation only. See README / docs/SPEC.md.",
}

# --- overall -----------------------------------------------------------------
all_pass = all(v.get("pass", False) for v in results.values())
receipt = {
    "env": "Latchwork",
    "regime": "dense-gradient",
    "target_frontier_mean_reward": BAND,   # graded partial-credit target, not a pass/fail band
    "runtime_requirement": "out-of-process serving: purge the pipeline/generator "
                           "source from the agent-reachable filesystem and expose only "
                           "the lossy probe socket; the in-process Channel is for "
                           "trusted offline evaluation only (see ISOLATION gate).",
    "budget": BUDGET_,
    "n_seeds": N_SEEDS,
    "accept_threshold": ACCEPT_THRESHOLD,
    "locked_config": {
        "n_fields": cfg.n_fields, "domain": cfg.domain, "n_stages": cfg.n_stages,
        "coupling": cfg.coupling, "form_weights": cfg.form_weights,
        "config_digest": cfg.digest(),
    },
    "elapsed_s": round(time.time() - t0, 1),
    "ALL_GATES_PASS": all_pass,
    "gates": results,
}

os.makedirs(os.path.join(os.path.dirname(__file__), "..", "receipts"), exist_ok=True)
outp = os.path.join(os.path.dirname(__file__), "..", "receipts", "stage0_receipt.json")
with open(outp, "w") as fh:
    json.dump(receipt, fh, indent=2)

print(json.dumps(receipt, indent=2))
print("\n" + ("=" * 60))
for gate, v in results.items():
    print(f"  [{'PASS' if v.get('pass') else 'FAIL'}] {gate}")
print(f"\nALL_GATES_PASS = {all_pass}   ({time.time()-t0:.0f}s)  -> {outp}")
