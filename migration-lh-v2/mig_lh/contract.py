"""Component 1: the frozen long-horizon contract, encoded as runnable Python.

Faithful transcription of the frozen contract (Ezequiel's draft + the three
frozen resolutions). This module is the single in-code source of truth for the
state machine, tool surface, trajectory gates, event/recovery taxonomy, and the
receipt schema. Every downstream component (control plane, scheduler, verifier,
gold, generator) imports from here so they cannot drift from the contract.

No behavior/reduction semantics live here (that is the ratified 0.3.0 core);
this is purely the trajectory/environment shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    """Section 8 state machine. SAFE_LEGACY_PENDING is App C's SAFE_LEGACY* sub-state
    (target reads returned to legacy, failed generation still held)."""
    DEGRADED_CANARY = "DEGRADED_CANARY"
    INCIDENT_CONFIRMED = "INCIDENT_CONFIRMED"
    SAFE_LEGACY_PENDING = "SAFE_LEGACY_PENDING"   # SAFE_LEGACY*: routing paused, generation still held
    SAFE_LEGACY = "SAFE_LEGACY"
    PATCH_READY = "PATCH_READY"
    CANDIDATE_CANARY = "CANDIDATE_CANARY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CANARY_QUALIFIED = "CANARY_QUALIFIED"
    RECONCILED = "RECONCILED"
    CUTOVER_READY = "CUTOVER_READY"
    COMPLETED = "COMPLETED"
    TERMINAL = "TERMINAL"                          # after submit.final freezes + grades


class EventClass(str, Enum):
    """Section 9.2 mandatory event classes. All FIVE semantic classes plus the
    forced recoverable failure MUST execute on every scored instance. FIELD_ACCRUAL
    owns the field-merge discriminator; it is a hidden qualification
    class (not baseline) so the naive whole-record prior still passes the public slice."""
    FIELD_ACCRUAL = "FIELD_ACCRUAL"
    OVERLAP = "OVERLAP"
    WRITER_FAILOVER = "WRITER_FAILOVER"
    CDC_REORDER_REPLAY = "CDC_REORDER_REPLAY"
    DELETE_RECREATE = "DELETE_RECREATE"
    RECOVERABLE_FAILURE = "RECOVERABLE_FAILURE"


SEMANTIC_EVENT_CLASSES = (
    EventClass.FIELD_ACCRUAL,
    EventClass.OVERLAP,
    EventClass.WRITER_FAILOVER,
    EventClass.CDC_REORDER_REPLAY,
    EventClass.DELETE_RECREATE,
)


class RecoveryFamily(str, Enum):
    """Section 9.3. Each seeded failure requires a *different* typed recovery;
    per frozen R2 an incorrect recovery must not be a free retry."""
    WORKER_CRASH = "WORKER_CRASH"
    CDC_CHECKPOINT_REWIND = "CDC_CHECKPOINT_REWIND"
    STALE_LEASE = "STALE_LEASE"
    PARTIAL_DEPLOY = "PARTIAL_DEPLOY"


# 9.3: symptom the agent must read (diagnostics.read) -> the one valid recovery family.
RECOVERY_SPEC: dict[RecoveryFamily, dict[str, str]] = {
    RecoveryFamily.WORKER_CRASH: {
        "symptom": "worker unavailable; durable offsets preserved",
        "recovery": "restart worker and resume from trusted checkpoint",
    },
    RecoveryFamily.CDC_CHECKPOINT_REWIND: {
        "symptom": "consumer reports replay window and duplicate deliveries",
        "recovery": "rewind/replay idempotently; do not truncate acknowledged history",
    },
    RecoveryFamily.STALE_LEASE: {
        "symptom": "old writer continues attempts after epoch promotion",
        "recovery": "revoke/refresh lease and enforce epoch validation",
    },
    RecoveryFamily.PARTIAL_DEPLOY: {
        "symptom": "candidate generation partially active",
        "recovery": "rollback or complete a clean redeploy through generation control",
    },
}


class Tool(str, Enum):
    """Section 7 + Appendix B tool surface. Typed args only; no shell/SQL/batch."""
    REPO_READ = "repo.read"
    REPO_EDIT = "repo.edit"
    SCHEMA_DESCRIBE = "schema.describe"
    MIGRATION_STATUS = "migration.status"
    INCIDENT_REPLAY = "incident.replay"
    LINEAGE_INSPECT = "lineage.inspect"
    SAMPLE_RECORDS = "sample.records"
    ROUTING_PAUSE_TARGET = "routing.pause_target"
    GENERATION_RESOLVE = "generation.resolve"
    TESTS_RUN_PUBLIC = "tests.run_public"
    CANDIDATE_DEPLOY = "candidate.deploy"
    QUALIFICATION_RUN = "qualification.run"
    DIAGNOSTICS_READ = "diagnostics.read"
    RECOVERY_APPLY = "recovery.apply"
    AUDIT_FORWARD = "audit.forward"
    REPAIR_RUN = "repair.run"
    BARRIER_VERIFY = "barrier.verify"
    REGRESSION_RUN = "regression.run"
    ROUTING_PROMOTE_TARGET = "routing.promote_target"
    SUBMIT_FINAL = "submit.final"


# Tools that never change trusted state (observation-only). Per T4/D2 they are
# idempotent and MUST NOT advance the event cursor.
OBSERVATION_TOOLS = frozenset({
    Tool.REPO_READ, Tool.SCHEMA_DESCRIBE, Tool.MIGRATION_STATUS,
    Tool.LINEAGE_INSPECT, Tool.DIAGNOSTICS_READ, Tool.SAMPLE_RECORDS,
})

# State-changing tools require the latest state_version (T2).
STATE_CHANGING_TOOLS = frozenset(t for t in Tool if t not in OBSERVATION_TOOLS) - {Tool.REPO_EDIT}
# repo.edit mutates the workspace only (no trusted state / no version), handled separately.


@dataclass(frozen=True)
class Transition:
    frm: State
    tool: Tool
    to: State
    note: str


# Appendix C state-transition matrix. qualification.run self-loops until all
# classes are done or a failure trips RECOVERY_REQUIRED (control plane decides
# which, deterministically, via the scheduler).
TRANSITIONS: tuple[Transition, ...] = (
    Transition(State.DEGRADED_CANARY, Tool.INCIDENT_REPLAY, State.INCIDENT_CONFIRMED,
               "public incident executed and divergence evidence exists"),
    Transition(State.INCIDENT_CONFIRMED, Tool.ROUTING_PAUSE_TARGET, State.SAFE_LEGACY_PENDING,
               "target cohort fully returned to legacy; generation still held"),
    Transition(State.SAFE_LEGACY_PENDING, Tool.GENERATION_RESOLVE, State.SAFE_LEGACY,
               "failed generation revoked; lock released"),
    Transition(State.SAFE_LEGACY, Tool.TESTS_RUN_PUBLIC, State.PATCH_READY,
               "frozen patch passes public suite"),
    Transition(State.PATCH_READY, Tool.CANDIDATE_DEPLOY, State.CANDIDATE_CANARY,
               "new generation active under controlled routing"),
    Transition(State.CANDIDATE_CANARY, Tool.QUALIFICATION_RUN, State.CANDIDATE_CANARY,
               "deterministic event batch executes (may instead trip RECOVERY_REQUIRED)"),
    Transition(State.CANDIDATE_CANARY, Tool.QUALIFICATION_RUN, State.RECOVERY_REQUIRED,
               "deterministic failure injected during a qualification"),
    Transition(State.RECOVERY_REQUIRED, Tool.RECOVERY_APPLY, State.CANDIDATE_CANARY,
               "failure-specific recovery completes (wrong family rejected, per R2)"),
    Transition(State.CANDIDATE_CANARY, Tool.AUDIT_FORWARD, State.CANARY_QUALIFIED,
               "all event classes complete and forward state is canonical"),
    Transition(State.CANARY_QUALIFIED, Tool.REPAIR_RUN, State.RECONCILED,
               "historical divergence repaired without collateral damage"),
    Transition(State.RECONCILED, Tool.BARRIER_VERIFY, State.RECONCILED,
               "per-partition barriers verified (regression.run also required)"),
    Transition(State.RECONCILED, Tool.REGRESSION_RUN, State.CUTOVER_READY,
               "barriers + ordinary behavior + integrity pass"),
    Transition(State.CUTOVER_READY, Tool.ROUTING_PROMOTE_TARGET, State.COMPLETED,
               "all target reads promoted"),
    Transition(State.COMPLETED, Tool.SUBMIT_FINAL, State.TERMINAL,
               "trusted freeze and grading triggered; no agent-authored payload"),
)


@dataclass(frozen=True)
class Gate:
    id: str
    name: str
    requirement: str


# Section 8.1 required trajectory gates. Verifier requires all ten, valid,
# ordered, signed, replayable.
GATES: tuple[Gate, ...] = (
    Gate("G1", "Incident evidence", "receipt proves incident replay executed and produced divergence"),
    Gate("G2", "Safe routing", "receipt proves target reads paused before generation recovery/repair"),
    Gate("G3", "Generation recovery", "failed generation and lock revoked/superseded via valid transition"),
    Gate("G4", "Candidate qualification", "frozen patch deployed through control plane after public tests"),
    Gate("G5", "Mandatory events", "field-accrual, overlap, failover, CDC reorder/replay, delete/recreate all executed"),
    Gate("G6", "Forced recovery", "a deterministic recoverable failure occurred and a valid recovery completed"),
    Gate("G7", "Forward safety", "audit proves current traffic converged under executed event history"),
    Gate("G8", "Historical repair", "repair ran only after G7 and converged divergence without collateral damage"),
    Gate("G9", "Barrier and regression", "all required partitions reached canonical barriers; ordinary behavior passed"),
    Gate("G10", "Promotion and submit", "promotion only after G1-G9; submission captured environment-owned state"),
)


# Section 2.3 strict success conjunction (also 11.3: strict_pass is Boolean AND).
STRICT_SUCCESS = (
    ("S1", "terminal canonical state matches oracle for every scored record/partition"),
    ("S2", "every mandatory trajectory gate evidenced by trusted receipts in required order"),
    ("S3", "every required injected event class executed and incorporated into terminal state"),
    ("S4", "at least one deterministic recoverable failure occurred post-deploy with a valid recovery path"),
    ("S5", "integrity, isolation, ordinary regression, and cutover gates pass"),
    ("S6", "no weighted combination compensates for S1-S5; partial scores are diagnostic only"),
)


# Appendix D receipt schema. Created exclusively by the control plane (R1),
# appended to a hash-chained store (R2), signed (control_signature).
RECEIPT_FIELDS = (
    "receipt_version", "instance_id", "receipt_id", "action_seq",
    "tool", "action_class", "state_before", "state_after",
    "state_version_before", "state_version_after",
    "normalized_args_digest", "patch_digest", "candidate_image_digest",
    "event_batch_digest", "durable_state_digest", "observation_digest",
    "previous_receipt_digest", "control_signature",
)


class ContractError(Exception):
    pass


def legal_tools(state: State) -> set[Tool]:
    """Tools whose declared transition can fire from this state, plus the
    always-available observation/workspace tools (Section 7 'Always')."""
    always = {Tool.REPO_READ, Tool.REPO_EDIT, Tool.SCHEMA_DESCRIBE, Tool.MIGRATION_STATUS,
              Tool.SAMPLE_RECORDS}
    if state in (State.INCIDENT_CONFIRMED, State.SAFE_LEGACY_PENDING, State.SAFE_LEGACY,
                 State.PATCH_READY, State.CANDIDATE_CANARY, State.RECOVERY_REQUIRED,
                 State.CANARY_QUALIFIED, State.RECONCILED, State.CUTOVER_READY, State.COMPLETED):
        always = always | {Tool.LINEAGE_INSPECT}  # after incident evidence
    return always | {t.tool for t in TRANSITIONS if t.frm == state}


def next_state(state: State, tool: Tool, *, failure_injected: bool = False) -> State:
    """Return the state after applying `tool` from `state`.

    `failure_injected` disambiguates the CANDIDATE_CANARY qualification.run fork
    (the control plane sets it when the deterministic scheduler injects the forced
    failure on this action). Observation/workspace tools do not change state.
    """
    if tool in OBSERVATION_TOOLS or tool == Tool.REPO_EDIT:
        return state
    candidates = [t for t in TRANSITIONS if t.frm == state and t.tool == tool]
    if not candidates:
        raise ContractError(f"illegal action: {tool.value} from {state.value}")
    if state == State.CANDIDATE_CANARY and tool == Tool.QUALIFICATION_RUN:
        target = State.RECOVERY_REQUIRED if failure_injected else State.CANDIDATE_CANARY
        return target
    return candidates[0].to


REFERENCE_TRAJECTORY_TOOLS = (
    # Section 14.1 reference trajectory as tool calls (observation calls omitted
    # from the state walk; four qualifications + one recovery inline).
    Tool.INCIDENT_REPLAY, Tool.ROUTING_PAUSE_TARGET, Tool.GENERATION_RESOLVE,
    Tool.TESTS_RUN_PUBLIC, Tool.CANDIDATE_DEPLOY,
    Tool.QUALIFICATION_RUN, Tool.QUALIFICATION_RUN, Tool.QUALIFICATION_RUN,
    Tool.QUALIFICATION_RUN, Tool.QUALIFICATION_RUN,  # five classes; one trips RECOVERY_REQUIRED
    Tool.RECOVERY_APPLY,
    Tool.AUDIT_FORWARD, Tool.REPAIR_RUN, Tool.BARRIER_VERIFY, Tool.REGRESSION_RUN,
    Tool.ROUTING_PROMOTE_TARGET, Tool.SUBMIT_FINAL,
)
