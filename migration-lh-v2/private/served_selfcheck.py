"""migration-lh-v2 SERVED-PATH lifecycle + isolation check (offline, no Docker/billing).

Boots Env from the data-only blob and drives the full operational sequence:
  * GOLD candidate (applies the instance's theta) -> strict_pass True  (positive control)
  * TEXTBOOK candidate (sum / all-eligible LWW) -> reaches submit but S1 fails (negative)
Plus: the serve closure (control_plane/verifier/served_data/candidate/dataplane_core) imports
NO oracle module (dataplane / generator absent from a fresh serve-only interpreter).

Run:  python3 private/served_selfcheck.py
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

# the serve path reads the salt from the blob itself (served_data.salt()); this env var is
# consumed only by the offline builder, so its value here is inert for the checks below.
os.environ.setdefault("MIG_LH_SALT", "11" * 32)

from mig_lh import dataplane_core as core
from mig_lh import dataplane as dp
from mig_lh import generator as gen
from mig_lh import served_data, verifier as vfy
from mig_lh.control_plane import Env
from mig_lh.contract import Tool, State

SEEDS = [1000001] + list(range(2000000, 2000000 + 8))


def gold_candidate(theta):
    def cand(muts, context):
        dicts = [core.mutation_to_dict(m) for m in muts]
        return dp.graded_terminal(dp.reduce_theta(dicts, context, theta))
    return cand


def textbook_candidate():
    tb = dp.Theta(tuple([dp.ADD] * dp.K), tuple([True] * dp.K), "LAST")
    return gold_candidate(tb)


def drive(env, cand):
    def sv():
        return env.state_version
    fam = env._failure_family.value
    env.call(Tool.INCIDENT_REPLAY, state_version=sv())
    env.call(Tool.ROUTING_PAUSE_TARGET, state_version=sv())
    env.call(Tool.GENERATION_RESOLVE, state_version=sv())
    env.call(Tool.TESTS_RUN_PUBLIC, {"candidate": cand}, state_version=sv())
    env.call(Tool.CANDIDATE_DEPLOY, {"candidate": cand}, state_version=sv())
    for _ in range(len(env._class_order)):
        env.call(Tool.QUALIFICATION_RUN, state_version=sv())
        if env.state == State.RECOVERY_REQUIRED:
            env.call(Tool.DIAGNOSTICS_READ)
            env.call(Tool.RECOVERY_APPLY, {"recovery_family": fam}, state_version=sv())
    env.call(Tool.AUDIT_FORWARD, state_version=sv())
    env.call(Tool.REPAIR_RUN, state_version=sv())
    env.call(Tool.BARRIER_VERIFY, state_version=sv())
    env.call(Tool.REGRESSION_RUN, state_version=sv())
    env.call(Tool.ROUTING_PROMOTE_TARGET, state_version=sv())
    env.call(Tool.SUBMIT_FINAL, {}, state_version=sv())
    return vfy.verify(env)


_ISO_SUBPROC = r'''
import sys
sys.path.insert(0, %r)
import mig_lh.control_plane, mig_lh.verifier, mig_lh.served_data, mig_lh.candidate, mig_lh.dataplane_core
bad = [n for n in sys.modules if n.endswith((".dataplane", ".generator"))]
print("RESIDENT_ORACLE=" + ",".join(sorted(bad)))
'''


def isolation_clean() -> bool:
    out = subprocess.run([sys.executable, "-c", _ISO_SUBPROC % SRC], capture_output=True, text=True)
    line = [l for l in out.stdout.splitlines() if l.startswith("RESIDENT_ORACLE=")]
    resident = line[0].split("=", 1)[1] if line else "??"
    print(f"  serve closure resident oracle modules: [{resident}]  (stderr: {out.stderr.strip()[:80]})")
    return resident == ""


def main():
    served_data._CACHE = None
    print("=== migration-lh-v2 served-path lifecycle + isolation (offline) ===\n")
    gold_ok = tb_fail = pub_pass = 0
    secret = b"\x00" * 32
    for seed in SEEDS:
        theta = gen.build_instance(seed).theta   # deterministic -> same theta the blob was built from

        rg = drive(Env(seed, secret), gold_candidate(theta))
        if rg["strict_pass"]:
            gold_ok += 1

        rt = drive(Env(seed, secret), textbook_candidate())
        # textbook passes public (baseline = anchor, textbook-consistent) but fails S1 on the hidden stream
        if not rt["strict_pass"] and not rt["S1_terminal_matches_oracle"]:
            tb_fail += 1
        if rt["S2_gates_signed_ordered"]:   # reached submit with a full, ordered gate chain
            pub_pass += 1

    n = len(SEEDS)
    print(f"gold  strict_pass (positive control)      : {gold_ok}/{n}")
    print(f"textbook reaches submit but S1 FAILS      : {tb_fail}/{n}")
    print(f"textbook passed public + full gate chain  : {pub_pass}/{n}  (deploys, then fails hidden)")
    iso = isolation_clean()
    green = gold_ok == n and tb_fail == n and pub_pass == n and iso
    print("\n" + ("V2 SERVED-PATH: ALL GREEN" if green else "V2 SERVED-PATH: SEE NON-GREEN ABOVE"))
    sys.exit(0 if green else 1)


if __name__ == "__main__":
    main()
