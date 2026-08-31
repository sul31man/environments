"""Run summary written beside the scores."""
import json

import numpy as np

from . import drift


def _feature_spread(fit_df, columns):
    spread = {}
    for name, series in fit_df[columns].items():
        spread[name] = round(float(series.std()), 6)
    return spread


def summarise(scores, fit_df, score_df, cfg, columns):
    return {
        "rows_scored": int(len(scores)),
        "rows_fitted": int(len(fit_df)),
        "held": int(scores["hold"].sum()),
        "hold_rate": round(float(scores["hold"].mean()), 6),
        "mean_score": round(float(scores["risk_score"].mean()), 6),
        "score_window": cfg["windows"]["score"],
        "fit_window": cfg["windows"]["fit"],
        "feature_spread": _feature_spread(fit_df, columns),
        "month_on_month": drift.month_on_month(scores),
    }


def write(path, payload):
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
