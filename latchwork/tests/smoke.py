"""Smoke test: determinism, A/B evaluator agreement, feasibility, gold=1.0."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from latchwork.generator import generate, GenConfig
from latchwork.evaluator_b import observe_from_keys
from latchwork.scoring import build_battery, score_keys

cfg = GenConfig()
print("config digest:", cfg.digest())

# 1. determinism: same seed -> identical pipeline key
i1 = generate("train", 7, cfg)
i2 = generate("train", 7, cfg)
assert i1.key() == i2.key(), "non-deterministic generation"
print("determinism OK; L =", i1.pipeline.L)

# 2. train/eval namespace disjoint (different keys for same seed)
ie = generate("eval", 7, cfg)
print("train/eval differ:", i1.key() != ie.key())

# 3. A vs B evaluator agreement on random assignments
n, M = cfg.n_fields, cfg.domain
keys = list(i1.pipeline.key())
rng = random.Random(0)
disagree = 0
for _ in range(5000):
    a = tuple(rng.randrange(M) for _ in range(n))
    oa = i1.pipeline.observe(a)          # evaluator A
    ob = observe_from_keys(keys, a, n, cfg.n_groups)  # evaluator B
    if oa != ob:
        disagree += 1
print("A/B disagreements over 5000 random:", disagree)
assert disagree == 0, "evaluator A/B differential FAILED"

# 4. feasibility: witness accepted
assert i1.pipeline.accepts(i1.witness)
print("feasibility (witness accepted) OK")

# 5. gold = params-known reconstruction -> score 1.0
battery = build_battery(i1, n_per_stratum=24)
strata = sorted({s for _, _, s in battery})
print("battery size:", len(battery), "occupied strata:", strata)
gold_score, breakdown = score_keys(keys, battery, n, cfg.n_groups)
print("GOLD score:", round(gold_score, 4))
assert abs(gold_score - 1.0) < 1e-9, "gold != 1.0"
print("SMOKE PASS")
