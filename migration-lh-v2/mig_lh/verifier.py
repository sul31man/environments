"""Component 6: verifier (DATA-ONLY served grade). strict_pass = S1 AND S2 AND S3 AND
S4 AND S5 (Boolean conjunction; partials are diagnostic only, never compensate).

ISOLATION FIX: the served grade imports NO oracle. S1 is a salted GLOBAL hash compare
of the env-owned terminal against the PRECOMPUTED `final_hash`; S1_fraction is binary
because per-record or per-event-class hashes would create a factorable verification
oracle. S2-S5 read only the signed receipt chain + env state. See docs/ISOLATION.md.
"""
from __future__ import annotations

from . import dataplane_core as core
from . import served_data
from .contract import GATES, SEMANTIC_EVENT_CLASSES, State, Tool, next_state
from .control_plane import GATE_FOR_TOOL


def _state_walk_ok(chain: list[dict]) -> tuple[bool, str]:
    sc = [r for r in chain if r["action_class"] == "STATE_CHANGING"]
    if not sc:
        return False, "no state-changing receipts"
    if sc[0]["state_before"] != State.DEGRADED_CANARY.value:
        return False, "walk did not start at DEGRADED_CANARY"
    if sc[-1]["state_after"] != State.TERMINAL.value:
        return False, "walk did not end at TERMINAL"
    prev_after = State.DEGRADED_CANARY.value
    prev_seq = -1
    for r in sc:
        if r["state_before"] != prev_after:
            return False, f"discontinuous walk at {r['receipt_id']}"
        if r["action_seq"] <= prev_seq:
            return False, "receipts not monotonically ordered"
        frm, to, tool = State(r["state_before"]), State(r["state_after"]), Tool(r["tool"])
        fail = to == State.RECOVERY_REQUIRED
        try:
            expect = next_state(frm, tool, failure_injected=fail)
        except Exception:
            return False, f"illegal transition {tool.value} from {frm.value}"
        if expect != to:
            return False, f"transition mismatch at {r['receipt_id']}"
        prev_after, prev_seq = r["state_after"], r["action_seq"]
    return True, "ok"


def gate_scores(env, expected_class_digests: set[str]) -> dict:
    """S2-S5 + integrity, from the signed receipt chain + env state (NO oracle, NO S1).
    Shared by the served (hash) grade and the dev (oracle) grade."""
    chain = env.receipts.chain
    sc = [r for r in chain if r["action_class"] == "STATE_CHANGING"]

    integrity = env.receipts.verify_integrity()
    walk_ok, walk_msg = _state_walk_ok(chain)
    gates_seen = {GATE_FOR_TOOL.get(Tool(r["tool"])) for r in sc if r["state_before"] != r["state_after"]}
    gates_all = {g.id for g in GATES}
    s2 = integrity and walk_ok and gates_all.issubset(gates_seen)

    qual_digests = {r["event_batch_digest"] for r in sc if r["tool"] == Tool.QUALIFICATION_RUN.value}
    s3 = qual_digests == expected_class_digests and len(qual_digests) == len(SEMANTIC_EVENT_CLASSES)

    fired = [i for i, r in enumerate(sc) if r["state_after"] == State.RECOVERY_REQUIRED.value]
    s4 = False
    if fired:
        nxt = sc[fired[0] + 1] if fired[0] + 1 < len(sc) else None
        s4 = bool(nxt and nxt["tool"] == Tool.RECOVERY_APPLY.value
                  and nxt["state_after"] == State.CANDIDATE_CANARY.value)

    tools_seq = [r["tool"] for r in sc]
    has = lambda t: t.value in tools_seq
    barrier_before_regression = (
        Tool.BARRIER_VERIFY.value in tools_seq and Tool.REGRESSION_RUN.value in tools_seq
        and tools_seq.index(Tool.BARRIER_VERIFY.value) < tools_seq.index(Tool.REGRESSION_RUN.value)
    )
    s5 = (integrity and has(Tool.REGRESSION_RUN) and has(Tool.ROUTING_PROMOTE_TARGET)
          and has(Tool.SUBMIT_FINAL) and barrier_before_regression)

    return {"integrity": integrity, "s2": s2, "s3": s3, "s4": s4, "s5": s5,
            "gates_seen": sorted(g for g in gates_seen if g), "walk": walk_msg,
            "receipt_count": len(chain)}


def _assemble(env, s1: bool, s1_fraction: float, g: dict, grade_mode: str, extra_diag: dict) -> dict:
    strict_pass = bool(s1 and g["s2"] and g["s3"] and g["s4"] and g["s5"])
    diag = {"gates_seen": g["gates_seen"], "walk": g["walk"], "receipt_count": g["receipt_count"]}
    diag.update(extra_diag)
    return {
        "instance_id": env.instance_id, "seed": env.seed, "namespace": env.namespace,
        "grade_mode": grade_mode, "strict_pass": strict_pass,
        "S1_terminal_matches_oracle": s1, "S1_fraction": s1_fraction,
        "S2_gates_signed_ordered": g["s2"], "S3_event_classes_executed": g["s3"],
        "S4_forced_recovery": g["s4"], "S5_integrity_regression_cutover": g["s5"],
        "diagnostics": diag,
    }


def _fail_closed(env, reason: str) -> dict:
    return {"instance_id": env.instance_id, "seed": env.seed, "namespace": env.namespace,
            "grade_mode": "frozen", "strict_pass": False, "S1_terminal_matches_oracle": False,
            "S1_fraction": 0.0, "S2_gates_signed_ordered": False, "S3_event_classes_executed": False,
            "S4_forced_recovery": False, "S5_integrity_regression_cutover": False,
            "diagnostics": {"fail_closed": reason}}


def verify(env) -> dict:
    """TRUSTED eval grade -- data-only. S1 = env terminal hash == precomputed final_hash;
    S1_fraction = fraction of per-class GROUP hashes matched. Fails closed on missing
    instance or a tampered served-data blob (SERVED_PIN)."""
    try:
        served_data.load()                       # pin/tamper check (fail closed)
        inst = served_data.instance(env.namespace, env.seed)
    except (FileNotFoundError, RuntimeError) as e:
        return _fail_closed(env, str(e))
    if inst is None:
        return _fail_closed(env, f"instance {env.namespace}:{env.seed} not in served data")

    salt = served_data.salt()
    term = env.terminal_state or {}
    s1 = (core.term_hash(salt, term) == inst["final_hash"])
    # v2: whole-terminal hash ONLY. Per-class group hashes are intentionally NOT shipped --
    # they would hand an agent a factorable per-subproblem oracle. S1_fraction is therefore
    # binary here; partial-credit shaping comes from the S2-S5 gate fractions in gate_scores.
    s1_fraction = 1.0 if s1 else 0.0

    gs = gate_scores(env, set(inst["class_digests"]))
    return _assemble(env, s1, s1_fraction, gs, "frozen",
                     {"records_scored": inst["records_scored"]})
