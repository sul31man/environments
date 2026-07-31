"""Serve-side loader for the precomputed data blob (isolation fix).

The served process consumes ONLY this data -- input streams + salted GLOBAL hashes +
the withheld-answer sample payload. It imports NO reducer logic (see docs/ISOLATION.md).
Fail-closed: if the blob is missing, or its sha256 does not match SERVED_PIN (when set),
grading/serving refuses to proceed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# sha256 of served/served_data.json for the SHIPPED artifact. "unpinned" => skip the
# tamper check (dev/pre-ship). Set to the SERVED_PIN printed by build_served_data.py at ship.
SERVED_PIN = "sha256:220f2dbae19436424f1068b0942be1dd1fbeeeebc948cadf592eec8d9a0f21fc"

_CACHE: dict | None = None


def _path() -> Path:
    override = os.environ.get("MIG_LH_SERVED")
    if override:
        return Path(override)
    # served/served_data.json sits at the package root; walk up to find it so this
    # resolves under both the src/mig_lh env layout and the packaged mig_lh layout.
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "served" / "served_data.json"
        if cand.exists():
            return cand
    return here.parents[2] / "served" / "served_data.json"


def load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    raw = _path().read_bytes()
    if SERVED_PIN != "unpinned":
        got = "sha256:" + hashlib.sha256(raw).hexdigest()
        if got != SERVED_PIN:
            raise RuntimeError(f"served_data.json hash {got} != pinned {SERVED_PIN}")
    _CACHE = json.loads(raw)
    return _CACHE


def salt() -> bytes:
    return bytes.fromhex(load()["salt_hex"])


def anchor_seed() -> int:
    return int(load()["anchor_seed"])


def class_order() -> list[str]:
    return list(load()["class_order"])


def sample_records() -> dict:
    return load()["sample_records"]


def instance(namespace: str, seed: int) -> dict | None:
    return load().get("instances", {}).get(f"{namespace}:{seed}")
