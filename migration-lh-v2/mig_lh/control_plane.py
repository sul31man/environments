"""Component 4b: control plane + tool server + event injection (DATA-ONLY serve).

The environment. Holds the trusted state machine, the candidate service, the
deterministic injected batches, and the signed receipt store. Every tool call
routes through `call()`, which enforces transition legality + the state-version
guard + trajectory-gate preconditions, injects the deterministic event batch on
each qualification (and trips the seeded forced failure), captures the env-owned
terminal at submit, and records a signed hash-chained receipt.

ISOLATION: this module imports NO reducer logic (serve-safe, by construction)
and NO scheduler. Streams, context, scenario, and the clean/dirty + barrier answers
are loaded as PRECOMPUTED DATA (`served_data`); divergence is a salted GLOBAL hash
compare against a precomputed prefix hash, never a live legacy fold. The serving
process therefore holds no reducer rule and no plaintext answer. See
docs/ISOLATION.md.
"""
from __future__ import annotations

from . import dataplane_core as core
from . import served_data
from .contract import (
    GATES, OBSERVATION_TOOLS, RECOVERY_SPEC, SEMANTIC_EVENT_CLASSES, RecoveryFamily,
    State, Tool, ContractError, next_state,
)
from .receipts import ReceiptStore

RECEIPT_VERSION = "lh-receipt-1"

# free migration.status divergence checks per qualification PHASE (reset on qualification.run):
# enough to test a couple of REASONED hypotheses, too few to brute-force against the global bit.
STATUS_CHECKS_PER_PHASE = 3

# tool -> the gate its successful state-changing receipt evidences (Section 8.1)
GATE_FOR_TOOL = {
    Tool.INCIDENT_REPLAY: "G1", Tool.ROUTING_PAUSE_TARGET: "G2",
    Tool.GENERATION_RESOLVE: "G3", Tool.CANDIDATE_DEPLOY: "G4",
    Tool.QUALIFICATION_RUN: "G5", Tool.RECOVERY_APPLY: "G6",
    Tool.AUDIT_FORWARD: "G7", Tool.REPAIR_RUN: "G8",
    Tool.REGRESSION_RUN: "G9", Tool.SUBMIT_FINAL: "G10",
}


class Env:
    """One graded instance, booted from the precomputed served-data blob. `secret` is
    the receipt-signing key (never projected)."""

    def __init__(self, seed: int, secret: bytes, namespace: str = "eval"):
        inst = served_data.instance(namespace, seed)
        if inst is None:
            raise ContractError(f"instance {namespace}:{seed} not in served data")
        self.seed = seed
        self.namespace = namespace
        self.instance_id = f"mig-lh-{namespace}-{seed}"
        self.state = State.DEGRADED_CANARY
        self.state_version = 0
        self.action_seq = 0
        self.receipts = ReceiptStore(secret)

        # streams + context + scenario as DATA (no scheduler/oracle)
        streams = inst["streams"]
        self._baseline = core.mutations_from_dicts(streams["baseline"])
        self._class_batches = [core.mutations_from_dicts(b) for b in streams["classes"]]
        self._class_order = list(streams["class_order"])
        self.context = inst["context"]
        sc = inst["scenario"]
        self._failure_family = RecoveryFamily(sc["failure_family"])
        self._failure_slot = int(sc["failure_slot"])

        # precomputed grade material (salted GLOBAL hashes; no plaintext answer)
        self._salt = served_data.salt()
        self._prefix_hashes = list(inst["prefix_hashes"])          # [k0..k5]
        self._prefix_counts = list(inst["prefix_record_counts"])
        self._barrier_digest = inst["barrier_digest"]
        self._samples = inst.get("samples", [])                    # per-instance worked examples

        self.candidate = None            # reducer set at candidate.deploy
        self.accepted: list = []         # the live stream the candidate serves (Mutation objs)
        self.classes_done: list[str] = []
        self._qual_index = 0
        self._accepted_prefix = 0         # 0=baseline; +1 per qualification (indexes prefix_hashes)
        self.failure_fired = False
        self.diagnostics_read = False
        self.failure_recovered = False
        self.barrier_verified = False
        self.public_passed = False
        self.terminal_state: dict | None = None
        self._qual_feedback: dict | None = None
        self._status_checks = 0

    def _qual_divergence(self) -> dict:
        """LOSSY production telemetry: run the deployed candidate on the accepted-so-far
        stream and report a SINGLE GLOBAL status vs legacy -- 'clean' iff EVERY scored
        record matches, else 'dirty'. NOT per-partition, NOT per-record, NO counts. The
        comparison is a salted GLOBAL hash against the PRECOMPUTED prefix hash: no oracle
        runs in-process, and the served process holds no plaintext answer."""
        k = self._accepted_prefix
        if self.candidate is None:
            return {"divergence": "clean", "records_scored": 0, "note": "no candidate deployed"}
        try:
            cand = self.candidate(list(self.accepted), self.context)
        except Exception:
            return {"candidate_error": True, "note": "your reducer raised on this stream"}
        clean = (core.term_hash(self._salt, cand) == self._prefix_hashes[k])
        return {"divergence": ("clean" if clean else "dirty"),
                "records_scored": self._prefix_counts[k],
                "note": "GLOBAL status only: clean iff EVERY scored record matches legacy "
                        "(no per-record/partition breakdown, no counts)."}

    def _sample_records(self) -> dict:
        """Per-instance worked examples (inputs + full durable outputs). They UNIQUELY
        determine this instance's field-combination table for `counter` and `head`
        (which cell of the public feature schema each write falls in, and how that cell
        folds). Recover the table from these examples and apply it to the graded stream --
        the taught scaffolding (dedup, failover, causal order, delete/recreate, status
        priority-join, tags union) is standard; only counter/head depart per-cell."""
        return {"context": self.context, "records": self._samples,
                "note": "worked examples that fully determine this instance's counter/head "
                        "combination table; the graded stream uses the SAME table."}

    # -- observation projections (T6/R3): reveal enough to act, never the future --
    def _observe(self, tool: Tool, args: dict) -> dict:
        if tool == Tool.MIGRATION_STATUS:
            obs = {"state": self.state.value, "state_version": self.state_version,
                   "classes_executed": list(self.classes_done),
                   "recovery_required": self.state == State.RECOVERY_REQUIRED}
            if self.candidate is not None:
                obs["checks_remaining"] = max(0, STATUS_CHECKS_PER_PHASE - self._status_checks)
                if self._status_checks < STATUS_CHECKS_PER_PHASE:
                    self._status_checks += 1
                    d = self._qual_divergence()
                    obs["divergence"] = d.get("divergence", "clean")
                    obs["records_scored"] = d.get("records_scored", 0)
                    if d.get("candidate_error"):
                        obs["candidate_error"] = True
                else:
                    obs["note"] = ("free divergence-check budget for this phase is exhausted; run "
                                   "qualification.run to advance (and reset the budget). Reason to the "
                                   "rule from sample.records + lineage rather than brute-forcing.")
            return obs
        if tool == Tool.DIAGNOSTICS_READ:
            if self.state != State.RECOVERY_REQUIRED:
                return {"diagnostic": None, "note": "no active failure"}
            self.diagnostics_read = True
            return {"symptom": RECOVERY_SPEC[self._failure_family]["symptom"]}
        if tool == Tool.LINEAGE_INSPECT:
            prov: dict = {}
            for b in self._class_batches:
                for m in b:
                    prov.setdefault(m.record_id, []).append({
                        "partition_id": m.partition_id, "local_seq": m.local_seq,
                        "writer_lease": m.writer_lease, "observed": m.observed,
                        "operation": m.operation,
                    })  # commit_seq omitted (ordering decoy); observed[] is the real signal
            return {"lineage": prov, "note": "per-write provenance (values redacted); "
                    "observed[] is the cross-partition happens-before watermark"}
        if tool == Tool.SAMPLE_RECORDS:
            return self._sample_records()
        if tool == Tool.SCHEMA_DESCRIBE:
            return {"record_fields": ["record_id", "is_deleted", "value"],
                    "value_fields": ["counter", "status", "tags", "head"]}
        if tool == Tool.REPO_READ:
            return {"note": "candidate source workspace (opaque in stage-0)"}
        return {}

    def call(self, tool: Tool, args: dict | None = None, state_version: int | None = None) -> dict:
        args = args or {}
        self.action_seq += 1

        if tool in OBSERVATION_TOOLS or tool == Tool.REPO_EDIT:
            obs = self._observe(tool, args) if tool != Tool.REPO_EDIT else {"edited": True}
            self._record(tool, self.state, self.state, self.state_version,
                         self.state_version, None, None, obs, args)
            return {"ok": True, "state": self.state.value,
                    "state_version": self.state_version, "observation": obs}

        if state_version is not None and state_version != self.state_version:
            raise ContractError(f"stale state_version {state_version} != {self.state_version}")

        failure_injected = False
        if tool == Tool.QUALIFICATION_RUN and self.state == State.CANDIDATE_CANARY:
            failure_injected = (self._qual_index == self._failure_slot and not self.failure_fired)

        self._check_preconditions(tool)
        before = self.state
        ver_before = self.state_version
        after = next_state(self.state, tool, failure_injected=failure_injected)

        event_digest = self._apply_side_effects(tool, args, failure_injected)

        self.state = after
        self.state_version += 1
        durable = None
        if tool == Tool.SUBMIT_FINAL:
            durable = core.digest(self.terminal_state)
        rec = self._record(tool, before, after, ver_before, self.state_version,
                           event_digest, durable,
                           {"transition": f"{before.value}->{after.value}"}, args)
        result = {"ok": True, "state": after.value, "state_version": self.state_version,
                  "receipt_id": rec["receipt_id"]}
        if tool == Tool.QUALIFICATION_RUN and self._qual_feedback is not None:
            result["observation"] = self._qual_feedback
        return result

    def _check_preconditions(self, tool: Tool) -> None:
        if tool == Tool.TESTS_RUN_PUBLIC:
            return
        if tool == Tool.RECOVERY_APPLY:
            if self.state != State.RECOVERY_REQUIRED:
                raise ContractError("recovery.apply only from RECOVERY_REQUIRED")
            if not self.diagnostics_read:
                raise ContractError("recovery.apply rejected: read diagnostics.read first (R2)")
        if tool == Tool.AUDIT_FORWARD:
            if set(self.classes_done) != {c.value for c in SEMANTIC_EVENT_CLASSES}:
                raise ContractError("audit.forward blocked: not all event classes executed (G5)")
            if not self.failure_recovered:
                raise ContractError("audit.forward blocked: forced recovery incomplete (G6)")
        if tool == Tool.REGRESSION_RUN and not self.barrier_verified:
            raise ContractError("regression.run blocked: barrier.verify required first (G9)")

    def _apply_side_effects(self, tool: Tool, args: dict, failure_injected: bool) -> str | None:
        if tool == Tool.TESTS_RUN_PUBLIC:
            cand = args.get("candidate") or self.candidate
            if cand is None:
                raise ContractError("no candidate patch provided to public tests")
            # public slice: the candidate's terminal on the clean baseline must match the
            # precomputed public (prefix-0) hash. The naive prior matches here (reaches deploy).
            try:
                out = cand(list(self._baseline), self.context)
            except Exception:
                raise ContractError("public tests failed (candidate raised)")
            if core.term_hash(self._salt, out) != self._prefix_hashes[0]:
                raise ContractError("public tests failed")
            self.candidate = cand
            self.public_passed = True
            return None

        if tool == Tool.CANDIDATE_DEPLOY:
            if self.candidate is None:
                self.candidate = args.get("candidate")
            if self.candidate is None:
                raise ContractError("candidate.deploy requires a patched service")
            self.accepted = list(self._baseline)
            self._accepted_prefix = 0
            return core.digest([m.mutation_id for m in self.accepted])

        if tool == Tool.QUALIFICATION_RUN:
            batch = self._class_batches[self._qual_index]
            cls_value = self._class_order[self._qual_index]
            self.accepted += batch
            self._accepted_prefix += 1
            if cls_value not in self.classes_done:
                self.classes_done.append(cls_value)
            self._qual_index += 1
            if failure_injected:
                self.failure_fired = True
            self._qual_feedback = self._qual_divergence()
            self._status_checks = 0
            return core.digest([m.mutation_id for m in batch])

        if tool == Tool.RECOVERY_APPLY:
            applied = args.get("recovery_family")
            fam = getattr(applied, "value", applied)
            if fam != self._failure_family.value:
                raise ContractError("recovery.apply rejected: wrong family for seeded failure")
            self.failure_recovered = True
            return core.digest({"recovery": fam})

        if tool == Tool.BARRIER_VERIFY:
            self.barrier_verified = True
            return self._barrier_digest          # precomputed (input-derived watermark)

        if tool == Tool.SUBMIT_FINAL:
            # environment-owned terminal capture: the candidate's own durable state (no oracle).
            self.terminal_state = self.candidate(list(self.accepted), self.context)
            return None
        return None

    def _record(self, tool, before, after, ver_before, ver_after, event_digest, durable, obs, args):
        fields = {
            "receipt_version": RECEIPT_VERSION, "instance_id": self.instance_id,
            "receipt_id": f"{self.instance_id}-r{self.action_seq}",
            "action_seq": self.action_seq, "tool": tool.value,
            "action_class": "OBSERVATION" if (tool in OBSERVATION_TOOLS or tool == Tool.REPO_EDIT)
                            else "STATE_CHANGING",
            "state_before": before.value, "state_after": after.value,
            "state_version_before": ver_before,
            "state_version_after": ver_after,
            "normalized_args_digest": core.digest(self._norm_args(args)),
            "patch_digest": core.digest("patch") if self.candidate is not None else None,
            "candidate_image_digest": core.digest("stage0-inproc"),
            "event_batch_digest": event_digest,
            "durable_state_digest": durable,
            "observation_digest": core.digest(obs),
        }
        return self.receipts.append(fields)

    @staticmethod
    def _norm_args(args: dict) -> dict:
        return {k: (v.__name__ if callable(v) else getattr(v, "value", v))
                for k, v in (args or {}).items()}
