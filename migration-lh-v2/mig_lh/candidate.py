"""Component 5: deterministic, out-of-process candidate runtime (frozen R3).

In a real rollout the candidate migration service is the agent's OWN code: the
agent edits `migrate.py` in the served workspace to expose
`reduce(mutations: list[dict]) -> dict[record_id, snapshot]`. `candidate.deploy`
binds that file as the deployed service; the control plane drives the injected
event stream into it and captures the terminal.

The agent's code runs in a SEPARATE subprocess (`-I -S`: no site packages, no env,
workspace-only import path, enforced timeout) so it (a) cannot IMPORT the reference reducer
and (b) is deterministic and reproducible. Everything crossing the boundary is plain JSON
-- no shared classes -- which sidesteps the cross-module identity traps.

STANDING LIMITATION (honest): `-I -S` restricts imports, NOT the filesystem. This
subprocess can still `open()` files in the container (e.g. the served blob), so a
malicious migrate.py could read the salt+hashes and self-cheat -- the leak-3 vector.
`DOCKER_RUN` below is a hardened-sandbox spec for an optional platform-side wrap; it is NOT on the
run path today (only `verify_isolation_flags` consults it). Closing this needs the
candidate to run without the blob mounted -- a deployment-side property.

Stage-0 also substitutes in-process reducers (fast) for the soundness sweeps; the
subprocess/file path is exercised by the reconstruct-and-regrade check.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

from . import dataplane_core as dp   # serve-safe: only digest() is used (no reducer logic)
from .contract import ContractError

DOCKER_RUN = (
    "docker", "run", "--rm",
    "--network", "none", "--read-only", "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges", "--user", "65534:65534",
    "--pids-limit", "128", "--memory", "512m", "--cpus", "1.0",
    "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
)
RUNTIME_ENV = {"PYTHONHASHSEED": "0", "MIG_LH_DETERMINISTIC": "1",
               "OMP_NUM_THREADS": "1", "TZ": "UTC"}

MUT_FIELDS = ("record_id", "partition_id", "operation", "commit_seq", "writer_lease",
              "local_seq", "observed", "field_ops", "mutation_id", "updated_at", "arrival")

# Runs in the isolated subprocess: import the agent's migrate.py from the workspace
# ONLY, reduce the piped mutations + context, emit the terminal as canonical JSON. No
# mig_lh. `context` is INPUT ONLY (lease->epoch map, handoff, checkpoint); the grade
# stays byte-equality on the returned snapshot, independent of context.
_RUNNER = (
    "import sys, json\n"
    "ws = sys.argv[1]; sys.path.insert(0, ws)\n"
    "import migrate\n"
    "d = json.load(sys.stdin)\n"
    "o = migrate.reduce(d['mutations'], d['context'])\n"
    "assert isinstance(o, dict), 'reduce must return a dict'\n"
    "json.dump(o, sys.stdout, sort_keys=True, separators=(',',':'), ensure_ascii=False)\n"
)


def _mutation_to_dict(m) -> dict:
    return {k: getattr(m, k) for k in MUT_FIELDS}


def normalize_terminal(raw: dict) -> dict:
    """Coerce the agent's raw reduce output into the exact oracle snapshot shape,
    recomputing value_digest so the agent need only get the SEMANTICS right."""
    out = {}
    for rid, snap in (raw or {}).items():
        if not isinstance(snap, dict):
            continue
        # GRADED SNAPSHOT = semantic durable state only. The env owns value_digest AND the
        # bookkeeping (applied_seq/source_epoch/tombstone_seq/last_operation) -- the agent's
        # copies of those are dropped here, so the agent need only get is_deleted + value right.
        is_deleted = bool(snap.get("is_deleted", False))
        value = snap.get("value")
        out[str(rid)] = {
            "record_id": snap.get("record_id", rid),
            "is_deleted": is_deleted,
            "value": value,
            "value_digest": None if is_deleted or value is None else dp.digest(value),
        }
    return out


def run_reduce(workspace: str, mut_dicts: list[dict], context: dict, timeout: float = 20.0) -> dict:
    """Run the workspace's migrate.reduce(mutations, context) in an isolated subprocess.
    Fails closed."""
    if not os.path.isfile(os.path.join(workspace, "migrate.py")):
        raise ContractError("no migrate.py in workspace (agent has not authored the service)")
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-c", _RUNNER, workspace],
            input=json.dumps({"mutations": mut_dicts, "context": context}), capture_output=True,
            text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ContractError("candidate runtime timed out (non-deterministic or hung)")
    if proc.returncode != 0:
        raise ContractError(f"candidate runtime error: {(proc.stderr or '').strip()[-300:]}")
    try:
        return json.loads(proc.stdout or "null")
    except Exception as e:
        raise ContractError(f"candidate produced non-JSON terminal: {e}")


def workspace_candidate(workspace: str):
    """A candidate callable backed by the agent's workspace file, run out-of-process.
    Signature matches the in-process reducers: (list[Mutation], context) -> snapshots."""
    def candidate(muts, context):
        raw = run_reduce(workspace, [_mutation_to_dict(m) for m in muts], context)
        return normalize_terminal(raw)
    return candidate


def load_candidate(repo_dir: str, entry: str = "migrate.py", func: str = "reduce"):
    """In-process import of the agent entrypoint (used only where the subprocess is
    unavailable). Prefer workspace_candidate for isolation."""
    path = os.path.join(repo_dir, entry)
    if not os.path.isfile(path):
        raise ContractError(f"candidate entrypoint not found: {path}")
    spec = importlib.util.spec_from_file_location("candidate_service", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, func, None)
    if not callable(fn):
        raise ContractError(f"candidate entrypoint {entry}:{func} is not callable")
    return fn


def verify_isolation_flags() -> dict:
    required = {"--network": "none", "--read-only": None, "--cap-drop": "ALL",
                "--security-opt": "no-new-privileges", "--user": "65534:65534"}
    flat = list(DOCKER_RUN)
    ok = {f: (f in flat) and (v is None or flat[flat.index(f) + 1] == v) for f, v in required.items()}
    return {"all_present": all(ok.values()), "flags": ok, "deterministic_env": RUNTIME_ENV}
