"""Load-bearing probe: ablate each stage (-> always-true) and measure score drop.
A stage is load-bearing iff removing it drops the differential score below 0.95.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from latchwork.generator import generate, GenConfig
from latchwork.scoring import build_battery, score_keys

# an "always-true" INTERVAL over the full domain, on the stage's primary field,
# preserves the class but never fails -> models the agent missing the stage.
def ablate_key(key, M):
    kind = key[0]
    f = key[1]
    return ("INTERVAL", f, 0, M - 1)

cfg = GenConfig()
worst_by_seed = []
for seed in range(20):
    inst = generate("train", seed, cfg)
    n, M = cfg.n_fields, cfg.domain
    keys = list(inst.pipeline.key())
    battery = build_battery(inst, n_per_stratum=24)
    base, _ = score_keys(keys, battery, n, cfg.n_groups)
    drops = []
    for k in range(len(keys)):
        ab = list(keys)
        ab[k] = ablate_key(keys[k], M)
        s, _ = score_keys(ab, battery, n, cfg.n_groups)
        drops.append((k + 1, round(s, 3)))
    worst = max(s for _, s in drops)
    worst_by_seed.append(worst)
    if seed < 5:
        print(f"seed {seed}: base={base:.3f} per-stage-ablated={drops} worst={worst:.3f}")

print("\nworst single-stage-ablation score across 20 seeds:", round(max(worst_by_seed), 3))
print("load-bearing (<0.95 for ALL stages ALL seeds):", max(worst_by_seed) < 0.95)
