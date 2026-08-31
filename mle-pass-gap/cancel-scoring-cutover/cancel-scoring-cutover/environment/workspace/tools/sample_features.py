#!/usr/bin/env python3
"""Dump the feature values for a fixed sample of scored lines.

    python3 tools/sample_features.py --config configs/reference.yaml

The sample is the first 500 lines of the scored window in line_id order, so it is the
same set every time. Compare against reference/feature_sample.csv to check a feature
row by row rather than only in aggregate.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riskscore import assemble, config, pipeline

SAMPLE_ROWS = 500


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cfg = config.load(args.config)
    _, score_df = pipeline.build(cfg)
    frame = score_df.sort_values("line_id").head(SAMPLE_ROWS)
    out = frame[["line_id"] + list(assemble.FEATURES)].copy()
    for col in assemble.FEATURES:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(6)
    if args.out:
        out.to_csv(args.out, index=False)
    print(out.to_string(index=False, max_cols=8))


if __name__ == "__main__":
    main()
