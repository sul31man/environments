#!/usr/bin/env python3
"""Print the feature profile for a run, in the same shape as the published one.

    python3 tools/profile_features.py --config configs/reference.yaml

Compare the result against reference/feature_profile.csv to see which features the
service is getting right.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riskscore import assemble, config, pipeline

COLUMNS = ["count", "nulls", "mean", "std", "min", "p25", "p50", "p75", "max"]


def profile(frame):
    rows = []
    for name in assemble.FEATURES:
        s = pd.to_numeric(frame[name], errors="coerce")
        rows.append({
            "feature": name,
            "count": int(s.shape[0]),
            "nulls": int(s.isna().sum()),
            "mean": round(float(s.mean()), 6),
            "std": round(float(s.std(ddof=0)), 6),
            "min": round(float(s.min()), 6),
            "p25": round(float(s.quantile(0.25)), 6),
            "p50": round(float(s.quantile(0.50)), 6),
            "p75": round(float(s.quantile(0.75)), 6),
            "max": round(float(s.max()), 6),
        })
    return pd.DataFrame(rows)[["feature"] + COLUMNS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cfg = config.load(args.config)
    _, score_df = pipeline.build(cfg)
    out = profile(score_df)
    if args.out:
        out.to_csv(args.out, index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
