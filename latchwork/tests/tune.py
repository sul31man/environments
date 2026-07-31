"""Lean tune: no_probe/batch/rote/bounded at two budgets (skip slow full)."""
import sys, os, random, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from latchwork.generator import GenConfig
from latchwork.channel import Channel
from latchwork import solvers as S
from latchwork.scoring import build_battery, score_keys
from latchwork.generator import generate
from latchwork.metrics import shallow_pass_region

BAND=(0.35,0.65); NS=int(os.environ.get("NS","12")); B=int(os.environ.get("BUDGET","20000"))
def wts(i,o,d,l,m,s): return {"INTERVAL":i,"ORDER":o,"DEPENDENCY":d,"LINEAR":l,"MODULAR":m,"SET":s}
def quota(i,s,m,l,o,d): return {"INTERVAL":i,"SET":s,"MODULAR":m,"LINEAR":l,"ORDER":o,"DEPENDENCY":d}
CONFIGS={
 "S1_L10_noOrd": GenConfig(n_stages=10,coupling=0.80,max_pass_rate=0.50,form_quota=quota(0,3,2,3,0,2)),
 "S2_L10_noOrd": GenConfig(n_stages=10,coupling=0.80,max_pass_rate=0.50,form_quota=quota(0,3,3,2,0,2)),
 "S3_L8_noOrd":  GenConfig(n_stages=8, coupling=0.80,max_pass_rate=0.50,form_quota=quota(0,2,2,2,0,2)),
}
def prof(cfg,seeds,budget):
    agg={k:[] for k in ["gold","no_probe","batch","rote","bounded"]}
    for seed in seeds:
        inst=generate("train",seed,cfg); n,ng=cfg.n_fields,cfg.n_groups
        bat=build_battery(inst,24); sc=lambda ks:score_keys(ks,bat,n,ng)[0]; R=lambda s:random.Random(s)
        agg["gold"].append(sc(S.gold(inst)))
        agg["no_probe"].append(sc(S.no_probe(Channel(inst,budget=0),R(seed+1))))
        agg["batch"].append(sc(S.batch(Channel(inst,budget=budget),R(seed+2),budget)))
        agg["rote"].append(sc(S.rote(Channel(inst,budget=budget),R(seed+3))))
        agg["bounded"].append(sc(S.adaptive(Channel(inst,budget=budget),R(seed+4),"bounded")))
    return agg
for name,cfg in CONFIGS.items():
    t0=time.time()
    p1=prof(cfg,range(NS),B); p2=prof(cfg,range(NS),2*B)
    mean=lambda a:sum(a)/len(a)
    spr=shallow_pass_region(cfg,list(range(NS))[:6])
    print(f"\n=== {name} coup={cfg.coupling} intW={cfg.form_weights['INTERVAL']} budget={B}/{2*B} [{time.time()-t0:.0f}s]")
    for k in ["gold","no_probe","batch","rote","bounded"]:
        a=p1[k]; print(f"  {k:9s} mean={mean(a):.3f} min={min(a):.3f} max={max(a):.3f}"
                        + (f"   (2B mean={mean(p2[k]):.3f})" if k in("bounded","rote") else ""))
    print(f"  rote margin below band = {BAND[0]-max(p1['rote']):+.3f}")
    print(f"  bounded in-band? mean={mean(p1['bounded']):.3f}  budget-delta={abs(mean(p1['bounded'])-mean(p2['bounded'])):.3f}")
    print(f"  shallow P(pass>=2)={spr[2]:.4f}")
