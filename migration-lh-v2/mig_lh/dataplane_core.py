"""Serve-safe data-plane primitives (NO reduction rules).

This is the ONLY data-plane surface the served process is permitted to import. It
holds pure data-shape + hashing helpers with ZERO semantic rule content, so a
the serving process never loads reducer logic, by construction:

  * `MutationV2`/`Mutation` -- the input record dataclass (data shape only),
  * `default_value` -- the neutral record value (already public in migrate.py's docstring),
  * `digest` -- canonical sha256 helper (receipt/normalize hashing, no rules),
  * `canonical_json` / `term_hash` -- canonicalization + salted HMAC used for the
    global clean/dirty and grade comparisons against PRECOMPUTED hashes,
  * `mutations_from_dicts` -- rebuild input Mutation objects from the frozen stream data.

The rule-bearing legacy reducers (the two withheld field rules) live in the
OFFLINE-ONLY oracle module, which is NOT shipped in the served image and NOT
imported by any serve module. See docs/ISOLATION.md.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def term_hash(salt: bytes, terminal: dict) -> str:
    """Salted HMAC of a (canonicalized) terminal snapshot. Used to compare an agent
    terminal to a PRECOMPUTED expected hash without ever holding the expected value."""
    return hmac.new(salt, canonical_json(terminal), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class MutationV2:
    record_id: str
    partition_id: int
    operation: str                 # CREATE | UPDATE | DELETE | RECREATE
    commit_seq: int | None         # DECOY global order
    writer_lease: str              # opaque; epoch known only via context["epoch_of_lease"]
    local_seq: int                 # per-partition reliable order
    observed: dict                 # {partition_id: highest observed-acked local_seq}
    field_ops: dict                # {counter?, status?, tags_add?, head?}
    mutation_id: str
    updated_at: int                # unreliable wall-clock (LWW decoy)
    arrival: int


Mutation = MutationV2

_MUT_FIELDS = ("record_id", "partition_id", "operation", "commit_seq", "writer_lease",
               "local_seq", "observed", "field_ops", "mutation_id", "updated_at", "arrival")


def default_value() -> dict:
    return {"counter": 0, "status": "ACTIVE", "tags": [], "head": None}


def mutation_to_dict(m: MutationV2) -> dict:
    d = {k: getattr(m, k) for k in _MUT_FIELDS}
    # observed keys are ints in-object; JSON stores them as strings -- normalize back on load
    return d


def mutations_from_dicts(rows: list[dict]) -> list[MutationV2]:
    """Rebuild input Mutation objects from frozen stream data (JSON-safe dicts).
    `observed` keys come back as strings from JSON -> coerce to int."""
    out = []
    for r in rows:
        obs = {int(k): v for k, v in (r.get("observed") or {}).items()}
        out.append(MutationV2(
            record_id=r["record_id"], partition_id=r["partition_id"], operation=r["operation"],
            commit_seq=r["commit_seq"], writer_lease=r["writer_lease"], local_seq=r["local_seq"],
            observed=obs, field_ops=r.get("field_ops") or {}, mutation_id=r["mutation_id"],
            updated_at=r["updated_at"], arrival=r["arrival"],
        ))
    return out
