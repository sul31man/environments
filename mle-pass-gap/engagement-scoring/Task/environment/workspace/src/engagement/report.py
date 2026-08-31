"""Run summary written beside the scores."""
import json


def summarise(scores, fit_df, score_df, cfg, columns):
    spread = {name: round(float(fit_df[name].std()), 6) for name in columns}
    return {
        "rows_scored": int(len(scores)),
        "rows_fitted": int(len(fit_df)),
        "promoted": int(scores["promote"].sum()),
        "promote_rate": round(float(scores["promote"].mean()), 6),
        "mean_engagement": round(float(scores["engagement"].mean()), 6),
        "fit_window": cfg["windows"]["fit"],
        "score_window": cfg["windows"]["score"],
        "feature_spread": spread,
    }


def write(path, payload):
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
