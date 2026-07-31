"""migration-lh-v2 -- framework-agnostic environment adapter (NO platform wrapper).

Single-episode, task-forced long-horizon workflow. A concurrency-safe ONLINE data
migration is live and DEGRADED. The agent must:

  A) Implement the migration service -- edit `workspace/migrate.py` so that
     `reduce(mutations, context) -> {record_id: snapshot}` folds the injected event
     stream into the exact durable state the LEGACY system produced. The correct
     semantics are NOT given; they are recovered from production evidence exposed by
     the operational tools. A naive last-write-wins / whole-record reducer PASSES the
     public test and FAILS the hidden qualification -- most of the fold is a standard
     prior (dedup, causal ordering, crash/checkpoint failover, delete/recreate,
     status priority-join, tags union); the per-instance `counter` and `head`
     field-combination table is WITHHELD and must be recovered from the worked samples.

  B) Operate the migration with the typed tools, in a legal order: reproduce the
     incident, pause the target cohort, resolve the failed generation, deploy the
     reducer, qualify each event class under canary, survive a FORCED recovery
     (diagnose then apply the matching family -- guessing is rejected), then audit,
     repair, barrier, regression, promote and submit.

Two-part determinacy (the answer is fully recoverable from what the agent can see,
but NOT from a single turn):
  - the per-instance reduction TABLE is deductively pinned by the worked `sample.records`
    (each used cell is exercised by a covering sample);
  - the global head-selector tie-break is pinned by the OPERATIONAL feedback: a wrong
    selector qualifies `dirty`, so it is discovered by deploying and reading the
    qualification signal, then corrected.
The qualification channel is a SINGLE lossy global clean/dirty bit (rate-limited -- it
cannot be brute-forced), and the forced recovery cannot fire until after deploy. Discovery
therefore drives the next action in a chain a single-turn or elective-depth episode cannot
collapse.

This module exposes the environment as plain functions/objects so it can be driven by
ANY harness. Stdlib-only, no external dependencies. Reference drivers:

    python3 -m private.selfcheck          # offline soundness suite (identifiability, oracles)
    python3 -m private.served_selfcheck   # served lifecycle: boot -> grade by value
    python3 migration_lh_v2_env.py        # this file: self-contained demo

Integration points for a host harness:
  - generate(index)                       -> an instance descriptor (seed + ids)
  - spec_text()                           -> the prompt shown to the agent
  - new_episode(seed)                     -> a live Env (drive it with Env.call)
  - TOOLS                                 -> the typed tool surface (name, doc, kind)
  - grade_episode(env)                    -> (reward, detail) for the agent's OWN run
  - grade_workspace(workspace_dir, seed)  -> (reward, detail) reference file-checker
  - purge_oracle + assert_isolated(dir)   -> serve-time oracle isolation (fail-closed)
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ENV_DIR = Path(__file__).resolve().parent
WORKSPACE = ENV_DIR / "workspace"
STUB = ENV_DIR / "stub_template" / "migrate.py"
sys.path.insert(0, str(ENV_DIR))

# Grade-time surface imported to memory BEFORE any purge, so grading keeps working once
# the reducer source and the served blob are deleted from the agent-reachable disk.
from mig_lh import generator as _gen                         # noqa: E402
from mig_lh import verifier as _vfy                          # noqa: E402
from mig_lh import candidate as _cand                        # noqa: E402
from mig_lh import served_data as _served                    # noqa: E402
from mig_lh.contract import RecoveryFamily, Tool, GATES, OBSERVATION_TOOLS, RECOVERY_SPEC, State  # noqa: E402
from mig_lh.control_plane import Env                         # noqa: E402

ANCHOR_SEED = _served.anchor_seed()
ORACLE_PKG = "mig_lh"
# the offline oracle == reducer logic (`dataplane`) + answer derivation (`generator`);
# `dataplane_core` (hashing/data shapes only) is serve-safe and stays.
ORACLE_MODULES = ("dataplane", "generator")
_SYM2FAM = {spec["symptom"]: fam for fam, spec in RECOVERY_SPEC.items()}


# --------------------------------------------------------------------------- instances
def generate(index: int = 0, namespace: str = _gen.EVAL_NAMESPACE) -> dict:
    """Deterministic per-instance descriptor. index 0 is the anchor; index >= 1 draws
    from the released eval corpus. Every released instance is feasible by construction
    (a correct reducer strict-passes) and non-trivial (a naive reducer fails the grade)."""
    seeds = _gen.released_eval_seeds()
    seed = seeds[index] if 0 <= index < len(seeds) else _gen.EVAL_CORPUS_BASE + index
    return _gen.make_instance(seed, namespace)


def released_seeds() -> list:
    return _gen.released_eval_seeds()


# --------------------------------------------------------------------------- prompt
_PROMPT = """\
A concurrency-safe online data migration is live and DEGRADED. Fix it and drive it
to a clean, canonical cutover.

TWO parts:
  A) Implement the migration service: edit `migrate.py` in your workspace so
     `reduce(mutations, context)` folds the event stream into the correct durable
     state per record -- the state the LEGACY system actually produced (see the
     workspace docstring for the exact I/O). The correct semantics are not given;
     recover them from the production evidence (incident.replay divergence,
     lineage.inspect, sample.records, qualification metrics, the failure diagnostic).
     A naive last-write-wins / whole-record reducer passes the PUBLIC test and FAILS
     the hidden qualification.
  B) Operate the migration with the typed tools, in a valid order:
     1. incident.replay + routing.pause_target (return the target cohort to legacy),
     2. generation.resolve, tests.run_public, candidate.deploy (your migrate.py),
     3. qualification.run until field-accrual, overlap, writer-failover, CDC
        reorder/replay and delete/recreate have ALL executed,
     4. survive the forced failure: diagnostics.read, then recovery.apply the
        matching family (guessing is rejected),
     5. audit.forward, repair.run, barrier.verify, regression.run,
        routing.promote_target, submit.final.
The environment captures and grades the terminal durable state against the canonical
oracle for every record. Pass the current state_version on every state-changing tool.
KEY: after each qualification, call migration.status to read a single GLOBAL divergence
status vs legacy ('clean' iff EVERY scored record matches, else 'dirty' -- no per-record or
per-partition breakdown, no counts). These checks are RATE-LIMITED (a few per qualification
phase; see `checks_remaining`, reset by qualification.run), so use them to confirm a REASONED
fix, not to brute-force -- recover the withheld rules from sample.records + lineage.inspect
(observed[] is the ordering signal), edit migrate.py, and re-check. Drive the whole stream
clean before you promote and submit.
"""


def spec_text() -> str:
    """The prompt shown to the agent. Discloses the workflow and the tool contract;
    discloses NO withheld rule and NO expected output -- those are recovered by
    operating the migration."""
    return _PROMPT


# --------------------------------------------------------------------------- tool surface
_DOC = {
    Tool.REPO_READ: "Read the candidate service workspace view (edit migrate.py with your file tools).",
    Tool.SCHEMA_DESCRIBE: "Describe the durable record schema fields.",
    Tool.MIGRATION_STATUS: "Report current state, state_version, executed event classes, AND (once deployed) a single GLOBAL divergence status vs legacy -- 'clean' iff EVERY scored record matches, else 'dirty' (no per-record/partition breakdown, no counts). RATE-LIMITED: a few divergence checks per qualification phase (see `checks_remaining`; the budget resets on each qualification.run). Use them to confirm a REASONED fix, not to brute-force.",
    Tool.LINEAGE_INSPECT: "Inspect per-write provenance for the injected records -- partition, local_seq, opaque writer_lease, the observed[] cross-partition happens-before watermark, and operation (values redacted). Use observed[] to recover the ordering rule.",
    Tool.SAMPLE_RECORDS: "Worked examples (FREE). For a set of illustrative records that are NOT in your graded set, shows the delivered mutation stream WITH field values (unlike lineage.inspect), the FULL durable output each produced, and the deploy context. These examples UNIQUELY DETERMINE this instance's counter/head field-combination table: the taught scaffolding (dedup, causal ordering, crash/checkpoint failover, delete/recreate, status priority-join, tags union) is standard; only `counter` and `head` depart, per this instance's table. Recover the table from the examples and apply it to the graded stream (which uses the SAME table); confirm via migration.status (global, rate-limited).",
    Tool.DIAGNOSTICS_READ: "Read the failure diagnostic symptom while in RECOVERY_REQUIRED (needed to choose the recovery).",
    Tool.REPO_EDIT: "Workspace edit marker (edit migrate.py directly with your file tools instead).",
    Tool.INCIDENT_REPLAY: "Reproduce the public incident and capture divergence evidence.",
    Tool.ROUTING_PAUSE_TARGET: "Pause the target cohort back to legacy reads.",
    Tool.GENERATION_RESOLVE: "Revoke the failed generation and release the lock.",
    Tool.TESTS_RUN_PUBLIC: "Run the public test suite against your workspace migrate.py (out-of-process).",
    Tool.CANDIDATE_DEPLOY: "Deploy your workspace migrate.py as the live migration service.",
    Tool.QUALIFICATION_RUN: "Execute the next injected event batch under canary; returns a single GLOBAL divergence status vs legacy ('clean' iff every scored record matches, else 'dirty'; no per-record/partition breakdown) -- refine migrate.py to drive the whole stream clean (check anytime via migration.status). May trip a forced recovery.",
    Tool.RECOVERY_APPLY: "Apply the failure-specific recovery during RECOVERY_REQUIRED (arg recovery_family: one of WORKER_CRASH, CDC_CHECKPOINT_REWIND, STALE_LEASE, PARTIAL_DEPLOY). Read diagnostics.read first; a wrong family is rejected.",
    Tool.AUDIT_FORWARD: "Prove forward convergence after all event classes + recovery.",
    Tool.REPAIR_RUN: "Repair historical divergence after forward safety.",
    Tool.BARRIER_VERIFY: "Verify per-partition canonical barriers.",
    Tool.REGRESSION_RUN: "Run ordinary-behavior regression; advances to cutover-ready.",
    Tool.ROUTING_PROMOTE_TARGET: "Promote all target reads to the migrated store.",
    Tool.SUBMIT_FINAL: "Freeze and grade the environment-owned terminal durable state.",
}

RECOVERY_FAMILIES = [f.value for f in RecoveryFamily]

TOOLS = [
    {"name": t.value,
     "kind": "OBSERVATION" if (t in OBSERVATION_TOOLS or t == Tool.REPO_EDIT) else "STATE_CHANGING",
     "doc": _DOC.get(t, f"{t.value} operational tool.")}
    for t in Tool
]


# --------------------------------------------------------------------------- episode
def reset_workspace(workspace_dir=WORKSPACE) -> None:
    """Restore the agent-facing workspace to the pristine stub migrate.py."""
    Path(workspace_dir).mkdir(parents=True, exist_ok=True)
    shutil.copy(STUB, Path(workspace_dir) / "migrate.py")


def new_episode(seed=ANCHOR_SEED) -> Env:
    """A fresh live episode. Drive it with env.call(Tool.X, args, state_version=...).
    For candidate.deploy / tests.run_public, pass the workspace candidate as the
    `candidate` arg -- see bind_workspace()."""
    return Env(int(seed), os.urandom(32))


def bind_workspace(workspace_dir=WORKSPACE):
    """A candidate callable backed by the agent's workspace migrate.py, run
    out-of-process. Pass it as the `candidate` arg to tests.run_public and
    candidate.deploy: env.call(Tool.CANDIDATE_DEPLOY, {"candidate": bind_workspace()})."""
    return _cand.workspace_candidate(str(workspace_dir))


def _reward(rep: dict) -> float:
    if rep["strict_pass"]:
        return 1.0
    gates = sum(rep[k] for k in ("S2_gates_signed_ordered", "S3_event_classes_executed",
                                 "S4_forced_recovery", "S5_integrity_regression_cutover"))
    return round(min(0.9, 0.5 * rep["S1_fraction"] + 0.4 * (gates / 4)), 3)


def grade_episode(env: Env) -> tuple:
    """Grade the agent's OWN completed episode. 1.0 iff the environment-owned terminal
    matches the frozen oracle for every record AND the full operational workflow was
    walked (signed, ordered, all event classes, forced recovery survived, cutover);
    otherwise partial credit < 1.0. This is the live RL reward."""
    rep = _vfy.verify(env)                                    # trusted frozen (hash-pinned) grade
    detail = {k: rep[k] for k in rep if k.startswith("S")}
    detail["grade_mode"] = rep.get("grade_mode")
    detail["strict_pass"] = rep["strict_pass"]
    return _reward(rep), detail


def _drive_spine(env: Env, candidate) -> None:
    """Drive the canonical operator spine around a candidate reducer: incident -> pause
    -> resolve -> deploy -> qualify (x event classes, surviving the forced recovery) ->
    audit -> repair -> barrier -> regression -> promote -> submit."""
    T = Tool
    v = lambda: env.state_version
    env.call(T.INCIDENT_REPLAY, state_version=v())
    env.call(T.ROUTING_PAUSE_TARGET, state_version=v())
    env.call(T.GENERATION_RESOLVE, state_version=v())
    env.call(T.TESTS_RUN_PUBLIC, {"candidate": candidate}, state_version=v())
    env.call(T.CANDIDATE_DEPLOY, {"candidate": candidate}, state_version=v())
    for _ in range(len(env._class_order)):
        env.call(T.QUALIFICATION_RUN, state_version=v())
        if env.state == State.RECOVERY_REQUIRED:
            obs = env.call(T.DIAGNOSTICS_READ)
            fam = _SYM2FAM[obs["observation"]["symptom"]]
            env.call(T.RECOVERY_APPLY, {"recovery_family": fam}, state_version=v())
    for t in (T.AUDIT_FORWARD, T.REPAIR_RUN, T.BARRIER_VERIFY, T.REGRESSION_RUN, T.ROUTING_PROMOTE_TARGET):
        env.call(t, state_version=v())
    env.call(T.SUBMIT_FINAL, {}, state_version=v())


def grade_workspace(workspace_dir=WORKSPACE, seed=ANCHOR_SEED) -> tuple:
    """Reference file-checker: drive the canonical operator spine around the workspace
    migrate.py and grade with strict_pass. A correct reducer scores 1.0; a naive one
    scores partial. Use it to validate a candidate migrate.py offline, or as the grade
    in a host harness that drives the workflow for the agent."""
    env = new_episode(seed)
    cand = bind_workspace(workspace_dir)
    try:
        _drive_spine(env, cand)
    except Exception as e:                                    # noqa: BLE001 -- a broken candidate floors, never crashes the grade
        rep = _vfy.verify(env)
        r, d = _reward(rep), {k: rep[k] for k in rep if k.startswith("S")}
        d["note"] = f"spine incomplete: {type(e).__name__}: {e}"
        d["strict_pass"] = rep["strict_pass"]
        return r, d
    return grade_episode(env)


# --------------------------------------------------------------------------- isolation
def oracle_on_disk(env_dir=ENV_DIR) -> bool:
    """Is the reducer SOURCE or the frozen grade material still on the agent-reachable
    disk? Stats the filesystem directly -- never trusts a purge flag, so a purge that
    failed silently (read-only mount, permission error) is still caught."""
    d = Path(env_dir)
    return (any((d / ORACLE_PKG / f"{m}.py").exists() for m in ORACLE_MODULES)
            or (d / "served" / "served_data.json").exists())


def oracle_importable(search_paths=None) -> bool:
    """Can the reducer/answer-derivation modules still be RESOLVED from the import path?
    Deleting the source is not the same as making it unreachable: a copy in
    site-packages survives the purge, so the disk check reports clean while
    `import mig_lh.dataplane` still resolves.

    Uses PathFinder(paths), NOT importlib.util.find_spec: the latter consults
    sys.modules, which the serving process legitimately populates at boot (grading
    needs the surface in memory after the purge), so it would report importable forever
    and fire on every clean deploy. invalidate_caches() first, because the path finder
    otherwise returns a spec for a directory that has already been deleted."""
    import importlib
    from importlib.machinery import PathFinder
    importlib.invalidate_caches()
    paths = list(sys.path if search_paths is None else search_paths)
    pkg = PathFinder().find_spec(ORACLE_PKG, paths)
    if pkg is None:
        return False
    sub = list(getattr(pkg, "submodule_search_locations", []) or [])
    return any(PathFinder().find_spec(f"{ORACLE_PKG}.{m}", sub) is not None for m in ORACLE_MODULES)


def isolation_report(env_dir=ENV_DIR, search_paths=None) -> dict:
    return {"oracle_on_disk": oracle_on_disk(env_dir),
            "oracle_importable": oracle_importable(search_paths)}


def assert_isolated(env_dir=ENV_DIR, search_paths=None) -> None:
    """FAIL-CLOSED serve-time isolation check over BOTH dimensions: refuse to serve
    while the reducer (source) or the frozen grade material is reachable on disk OR by
    import."""
    on_disk = oracle_on_disk(env_dir)
    importable = oracle_importable(search_paths)
    if not (on_disk or importable):
        return
    why = []
    if on_disk:
        why.append("reducer source or frozen grade material still on disk at %s (purge did "
                   "not run, or failed silently)" % env_dir)
    if importable:
        why.append("modules %s still importable from the path -- a copy outside the purged "
                   "tree, e.g. installed into site-packages by a non-editable `pip install .`"
                   % (ORACLE_MODULES,))
    raise RuntimeError("migration-lh-v2 FAIL-CLOSED: refusing to serve, the reducer/answers "
                       "are still reachable. " + " ALSO: ".join(why))


def purge_oracle(env_dir=ENV_DIR) -> None:
    """Serve-time hardening for a host that ships the full tree: after the grade surface
    is loaded to memory, delete the reducer source and the frozen grade material from the
    agent-reachable disk. The agent then reaches the migration ONLY through the tool
    surface. Fail-closed. (The reference serve image ships these absent by construction.)"""
    _served.load()                                           # cache streams + grade material in memory
    d = Path(env_dir)
    for m in ORACLE_MODULES:
        (d / ORACLE_PKG / f"{m}.py").unlink(missing_ok=True)
    for sub in ("served", "private", "docs"):
        shutil.rmtree(d / sub, ignore_errors=True)
    assert_isolated(env_dir)


# A deterministic disk+import isolation probe a host can run as a check task after purge.
LEAKPROBE_PROMPT = (
    "ISOLATION PROBE. Run each and report output verbatim; every one MUST fail:\n"
    "  cat mig_lh/dataplane.py ; cat mig_lh/generator.py ; cat served/served_data.json\n"
    "  python3 -c 'import mig_lh.dataplane as d; print(d.reduce_theta)'\n"
    "  find / -name 'dataplane.py' -o -name 'served_data.json' 2>/dev/null ; ls -la .\n"
    "No such file / ModuleNotFoundError / empty is the expected (and required) result."
)


if __name__ == "__main__":
    print("migration-lh-v2 -- standalone self-check")
    spec = spec_text()
    if not spec or "migrate.py" not in spec:
        raise RuntimeError("spec_text render failed")        # not `assert`: survives -O
    print("  spec_text renders OK (%d chars); discloses withheld rules/answers: NO" % len(spec))
    inst = generate(0)
    print("  instance 0: %s (seed=%d)" % (inst.get("instance_id", inst.get("id")), inst["seed"]))
    print("  tools: %d (%d observation, %d state-changing); gates: %d; recovery families: %s"
          % (len(TOOLS), sum(t["kind"] == "OBSERVATION" for t in TOOLS),
             sum(t["kind"] == "STATE_CHANGING" for t in TOOLS), len(GATES),
             ",".join(RECOVERY_FAMILIES)))
    import tempfile
    gold_fix = ENV_DIR / "private" / "fixtures" / "gold_migrate.py"
    if gold_fix.exists():
        ws = Path(tempfile.mkdtemp()); shutil.copy(gold_fix, ws / "migrate.py")
        r, d = grade_workspace(ws, ANCHOR_SEED)
        print("  reference grade -- gold migrate.py: reward=%.3f strict_pass=%s (expect 1.0/True)"
              % (r, d.get("strict_pass")))
    reset_workspace()
    rs, ds = grade_workspace(WORKSPACE, ANCHOR_SEED)
    print("  reference grade -- workspace stub:   reward=%.3f strict_pass=%s (expect <1.0/False)"
          % (rs, ds.get("strict_pass")))
    print("  isolation (pre-purge): %s" % isolation_report())
    print("  reference soundness suite: python3 -m private.selfcheck")
