#!/usr/bin/env python3
"""Diff two score files by rating_id.

    python3 tools/compare_scores.py <baseline.csv> <candidate.csv>
"""
import sys

import pandas as pd

TOLERANCE = 1e-6


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    baseline = pd.read_csv(sys.argv[1]).set_index("rating_id")
    candidate = pd.read_csv(sys.argv[2]).set_index("rating_id")
    joined = baseline[["engagement"]].join(
        candidate[["engagement"]], how="outer", lsuffix="_baseline", rsuffix="_candidate")
    missing = int(joined["engagement_candidate"].isna().sum())
    added = int(joined["engagement_baseline"].isna().sum())
    both = joined.dropna()
    moved = (both["engagement_baseline"] - both["engagement_candidate"]).abs()

    print("rows in baseline       %d" % len(baseline))
    print("rows in candidate      %d" % len(candidate))
    print("missing from candidate %d" % missing)
    print("not in baseline        %d" % added)
    print("matching within %g     %d" % (TOLERANCE, int((moved <= TOLERANCE).sum())))
    print("moved                  %d" % int((moved > TOLERANCE).sum()))
    if len(moved):
        print("largest movement       %.6f" % float(moved.max()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
