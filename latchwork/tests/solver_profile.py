"""Profile all solvers: gold / no_probe / batch / rote / adaptive(bounded,full)."""
import sys, os, random, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from latchwork.generator import generate, GenConfig
from latchwork.channel import Channel
from latchwork import solvers as S
from latchwork.scoring import build_battery, score_keys

cfg = GenConfig()
N_SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
BUDGET = int(sys.argv[2]) if len(sys.argv) > 2 else 3000

def run(seed):
    inst = generate("train", seed, cfg)
    n, ng = cfg.n_fields, cfg.n_groups
    battery = build_battery(inst, n_per_stratum=24)
    def sc(keys): return score_keys(keys, battery, n, ng)[0]
    rng = lambda s: random.Random(s)
    out = {}
    out["gold"] = sc(S.gold(inst))
    out["no_probe"] = sc(S.no_probe(Channel(inst, budget=0), rng(seed+1)))
    out["batch"] = sc(S.batch(Channel(inst, budget=BUDGET), rng(seed+2), BUDGET))
    out["rote"] = sc(S.rote(Channel(inst, budget=BUDGET), rng(seed+3)))
    out["adaptive_bounded"] = sc(S.adaptive(Channel(inst, budget=BUDGET), rng(seed+4), "bounded"))
    chf = Channel(inst, budget=None)
    out["adaptive_full"] = sc(S.adaptive(chf, rng(seed+5), "full"))
    out["_full_probes"] = chf.count
    return out

rows = []
t0 = time.time()
for seed in range(N_SEEDS):
    rows.append(run(seed))
    print(f"seed {seed}: " + " ".join(
        f"{k}={rows[-1][k]:.3f}" for k in
        ["gold","no_probe","batch","rote","adaptive_bounded","adaptive_full"]) +
        f"  (full_probes={rows[-1]['_full_probes']})")

def avg(k): return sum(r[k] for r in rows)/len(rows)
print("\n=== MEANS over", N_SEEDS, "seeds (budget=%d) ===" % BUDGET)
for k in ["gold","no_probe","batch","rote","adaptive_bounded","adaptive_full"]:
    print(f"  {k:18s} {avg(k):.3f}")
print(f"elapsed {time.time()-t0:.1f}s")
