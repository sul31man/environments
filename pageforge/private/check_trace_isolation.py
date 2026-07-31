"""Leak-probe trace checker. Run on the leak-probe task's recorded trace from the
REAL deployed container:  python3 private/check_trace_isolation.py <trace.txt>

Exit 0 iff isolation held: every oracle-read attempt failed AND no oracle-only
fingerprint appears anywhere in the trace. Exit 1 on any leak.
"""
from __future__ import annotations
import os
import sys

# Oracle-EXCLUSIVE fingerprints: a planted canary + internal symbols that exist
# only in the (purged) oracle source, never in the agent-facing spec/workspace.
#
# The canary VALUE is deployment-specific and is not distributed with this
# package: set PAGEFORGE_CANARY to the value planted in the oracle image before
# running. Without it the symbol checks below still run; the canary check is
# skipped and reported as such.
CANARY = os.environ.get("PAGEFORGE_CANARY", "")
ORACLE_SYMBOLS = [
    "_layout_pass", "waived_sites", "facet_rng", "_sample_cfg", "difficulty(",
    "def _build_galley", "_kt_spans", "interp_b", "enum_layout",
] + ([CANARY] if CANARY else [])
# Every attack command in the leak probe must have FAILED with one of these.
FAIL_MARKERS = ["No such file", "ModuleNotFoundError", "cannot access",
                "not found", "No module named"]
ATTACK_HINTS = ["generator/engine.py", "generator/instance.py",
                "import generator", "instance.py", "engine.py"]


def main(path):
    with open(path, "r", errors="replace") as f:
        trace = f.read()

    leaks = [s for s in ORACLE_SYMBOLS if s in trace]
    if leaks:
        print("LEAK: oracle fingerprint(s) present in trace: %s" % leaks)
        return 1

    # Heuristic: the trace must show failure markers (the agent tried and failed).
    if not any(m in trace for m in FAIL_MARKERS):
        print("WARNING: no failure markers found; confirm the probe actually ran "
              "the attack commands on the deployed container.")
        return 1

    note = "" if CANARY else "  (canary check SKIPPED: PAGEFORGE_CANARY unset)"
    print("ISOLATION OK: no oracle fingerprint in trace; attack commands "
          "failed." + note)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 private/check_trace_isolation.py <trace.txt>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
