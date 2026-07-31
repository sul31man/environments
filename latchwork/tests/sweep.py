"""Knob sweep: find a config where rote walls with margin, bounded lands in band,
budget-insensitive, small shallow-pass-region, class form-agnostic, 100% ident."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from latchwork.generator import GenConfig
from latchwork.metrics import (solver_profile, summarize, shallow_pass_region,
                               class_form_mi, variant_indistinguishability)
from latchwork.identifiability import acceptance_rate

BAND = (0.35, 0.65)
SEEDS = range(int(os.environ.get("NS", "12")))
BUDGET = int(os.environ.get("BUDGET", "3000"))

def w(interval, order, dep, lin, mod, setw):
    return {"INTERVAL": interval, "ORDER": order, "DEPENDENCY": dep,
            "LINEAR": lin, "MODULAR": mod, "SET": setw}

CONFIGS = {
    "A_baseline_L8": GenConfig(n_stages=8, coupling=0.5),
    "B_lowInterval_L8": GenConfig(n_stages=8, coupling=0.55,
        form_weights=w(0.4, 1.0, 1.0, 1.2, 1.0, 1.1)),
    "C_lowInterval_L10": GenConfig(n_stages=10, coupling=0.6,
        form_weights=w(0.4, 0.9, 1.1, 1.2, 1.0, 1.1)),
}

for name, cfg in CONFIGS.items():
    t0 = time.time()
    rows = solver_profile(cfg, SEEDS, BUDGET)
    s = summarize(rows)
    spr = shallow_pass_region(cfg, list(SEEDS)[:6])
    mi = class_form_mi(cfg, range(60))
    vind = variant_indistinguishability(cfg, SEEDS, BUDGET)
    acc, _ = acceptance_rate("train", SEEDS, cfg)
    rote_max = s["rote"]["max"]; band_lo = BAND[0]
    print(f"\n=== {name}  (L={cfg.n_stages} coup={cfg.coupling} budget={BUDGET}) "
          f"[{time.time()-t0:.0f}s] ===")
    for k in ["gold","no_probe","batch","rote","bounded_B","bounded_2B","full"]:
        if k in s:
            print(f"  {k:11s} mean={s[k]['mean']:.3f} min={s[k]['min']:.3f} max={s[k]['max']:.3f}")
    print(f"  rote_margin_below_band = {band_lo - rote_max:+.3f} (want >0)")
    print(f"  bounded budget-insensitivity |B-2B| mean-delta = "
          f"{abs(s['bounded_B']['mean']-s['bounded_2B']['mean']):.3f}")
    print(f"  shallow_pass_region P(pass>=k): {{'1':{spr[1]:.4f},'2':{spr[2]:.4f},'3':{spr[3]:.4f}}}")
    print(f"  class_form_normalized_MI = {mi['normalized_mi']:.4f} (want ~0)")
    print(f"  variant_indistinguishability = {vind:.3f} (want >=0.50)")
    print(f"  identifiability_acceptance = {acc:.3f} (want ~1.0)")
