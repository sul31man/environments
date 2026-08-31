#!/usr/bin/env python3
"""Grader for the engagement scoring rebuild.

Runs the candidate service in a subprocess against pinned run configs, then compares
the risk scores it produces to the expected values row by row. The expected values
never enter the agent's workspace, and the candidate's own configs are replaced with
verifier-side copies so editing a run window cannot change what is graded.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

LOGS = Path(os.environ.get("VERIFIER_LOGS", "/logs/verifier"))
TESTS = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace/target"))

TOLERANCE = 1e-6          # scores are published at 6 decimal places
AGREE_PASS = 0.999        # a correct rebuild reproduces every row; measured margin
RUN_TIMEOUT = 1800

# Both windows must agree. The reference scores ship with the workspace, so credit for
# the reference window alone would be payable by copying a file that is already there.

REFERENCE_EXPECTED = TESTS / "expected_reference.csv.gz"
CURRENT_EXPECTED = TESTS / "expected_current.csv.gz"


def _stage():
    """Copy the candidate workspace somewhere writable and pin the run configs."""
    staged = Path(tempfile.mkdtemp(prefix="candidate_"))
    shutil.copytree(WORKSPACE, staged / "target", symlinks=False)
    target = staged / "target"
    pinned = TESTS / "pinned"
    if pinned.is_dir():
        (target / "configs").mkdir(parents=True, exist_ok=True)
        for cfg in pinned.glob("*.yaml"):
            shutil.copy(cfg, target / "configs" / cfg.name)
    return target


def _run(target, config_name, out_name):
    out_dir = target / "_grade_out" / out_name
    proc = subprocess.run(
        [sys.executable, "run_scoring.py", "--config", "configs/%s" % config_name,
         "--out", str(out_dir)],
        cwd=str(target), capture_output=True, text=True, timeout=RUN_TIMEOUT,
    )
    produced = out_dir / "scores.csv"
    return proc, (produced if produced.is_file() else None)


def _agreement(produced_path, expected_path):
    """Fraction of expected rows the candidate reproduces within tolerance."""
    expected = pd.read_csv(expected_path)
    produced = pd.read_csv(produced_path)
    for frame, tag in ((expected, "expected"), (produced, "produced")):
        for column in ("rating_id", "engagement"):
            if column not in frame.columns:
                return 0.0, "%s output has no %s column" % (tag, column)
    if produced["rating_id"].duplicated().any():
        return 0.0, "produced output repeats rating_id"

    merged = expected[["rating_id", "engagement"]].merge(
        produced[["rating_id", "engagement"]], on="rating_id", how="left",
        suffixes=("_expected", "_produced"))
    diff = (merged["engagement_expected"] - merged["engagement_produced"]).abs()
    matched = (diff <= TOLERANCE).fillna(False)
    note = "%d of %d rows within %g" % (int(matched.sum()), len(merged), TOLERANCE)
    return float(matched.mean()), note


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    detail = {"tolerance": TOLERANCE, "agree_pass": AGREE_PASS}
    reward = 0.0

    try:
        target = _stage()
        for tag, config_name, expected in (
            ("reference", "reference.yaml", REFERENCE_EXPECTED),
            ("current", "current.yaml", CURRENT_EXPECTED),
        ):
            proc, produced = _run(target, config_name, tag)
            if produced is None:
                detail[tag] = {"ran": False,
                               "stderr": (proc.stderr or "")[-800:],
                               "agreement": 0.0}
                continue
            agreement, note = _agreement(produced, expected)
            detail[tag] = {"ran": True, "agreement": round(agreement, 6), "note": note}

        current = detail.get("current", {}).get("agreement", 0.0)
        reference = detail.get("reference", {}).get("agreement", 0.0)
        reward = 1.0 if (current >= AGREE_PASS and reference >= AGREE_PASS) else 0.0
    except Exception as exc:                      # never let the grader crash to 1.0
        detail["error"] = "%s: %s" % (type(exc).__name__, exc)
        reward = 0.0

    detail["reward"] = reward
    LOGS.joinpath("reward.txt").write_text("1" if reward else "0")
    LOGS.joinpath("detail.json").write_text(json.dumps(detail, indent=2, sort_keys=True))
    print(json.dumps(detail, indent=2, sort_keys=True))
    print("Final score: %s" % reward)


if __name__ == "__main__":
    main()
