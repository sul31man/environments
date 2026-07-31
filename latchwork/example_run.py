"""End-to-end example: generate an instance, probe it through the lossy channel,
and grade reconstructions against the held-out battery.

Run from the package root:  python3 example_run.py

This is the whole integration surface: serve `probe(assignment)` to your agent,
collect its JSON reconstruction, and score it with `score_keys(...)`.

NOTE: this script runs IN PROCESS, which is fine here because it only runs trusted
code (baseline solvers). A real agent is UNTRUSTED and must run OUT OF PROCESS:
in-process, the answer is directly readable from the Channel
(getattr(ch, "_Channel__pipeline")) -- name mangling is not a boundary. Serve
probe over a socket to a separate process/container and purge the source. See
README / docs/SPEC.md §7.
"""

import random

from latchwork.locked import LOCKED_CONFIG as CFG, BUDGET
from latchwork.generator import generate
from latchwork.channel import Channel
from latchwork.scoring import build_battery, score_keys
from latchwork import solvers

N, NG = CFG.n_fields, CFG.n_groups

# 1. Generate a hidden instance (deterministic in (namespace, seed)).
inst = generate("eval", 0, CFG)
print("instance: L=%d stages, N=%d fields, domain=%d"
      % (inst.pipeline.L, N, CFG.domain))

# 2. The lossy probe channel is the ONLY thing an agent should see. It exposes
#    n_fields / domain / L and a budgeted probe(assignment); it holds the pipeline
#    privately and returns first-failure (index, class) only -- no parameters.
ch = Channel(inst, budget=BUDGET)
for a in ([0] * N, [31] * N, list(range(N))):
    print("  probe(%s) -> %s" % (a, ch.probe(a)))
print("  (serve ch.probe(assignment) to your agent; index+class only)")

# 3. Build the held-out, depth-stratified grading battery.
battery = build_battery(inst, n_per_stratum=24)
print("battery: %d assignments across %d depth strata"
      % (len(battery), len({s for _, _, s in battery})))

# 4. Grade reconstructions. A reconstruction is a list of stage objects; here we
#    use the canonical value-key form (see docs/SPEC.md for the JSON schema).
gold_keys = list(inst.pipeline.key())                          # params-known reference
print("gold (params-known) score:", round(score_keys(gold_keys, battery, N, NG)[0], 4))  # 1.0

stub = [("INTERVAL", 0, 0, CFG.domain - 1)] * inst.pipeline.L   # all-permissive stub
print("all-permissive stub score:", round(score_keys(stub, battery, N, NG)[0], 4))       # ~floor

# 5. A channel-only baseline discoverer (no access to parameters), for reference.
recon = solvers.adaptive(Channel(inst, budget=BUDGET), random.Random(0), "bounded")
print("channel-only adaptive baseline score:", round(score_keys(recon, battery, N, NG)[0], 4))
