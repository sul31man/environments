"""Portfolio-wide levels, used wherever a row has no history of its own."""
import numpy as np
import pandas as pd


def levels(fit_df):
    """One fallback number per quantity, taken over the whole fit window."""
    member_span = fit_df.groupby("member_id")["rated_at"].agg(["min", "max", "size"])
    member_days = (member_span["max"] - member_span["min"]).dt.days.astype("float64")
    film_span = fit_df.groupby("film_id")["rated_at"].agg(["min", "max"])
    film_days = (film_span["max"] - film_span["min"]).dt.days.astype("float64")
    pace = member_span["size"].astype("float64") / np.maximum(member_days, 1.0)
    member_spread = fit_df.groupby("member_id")["stars"].std(ddof=0)
    film_spread = fit_df.groupby("film_id")["stars"].std(ddof=0)
    gaps = (fit_df.sort_values(["member_id", "rated_at"], kind="stable")
            .groupby("member_id")["rated_at"].diff().dt.total_seconds() / 86400.0)
    return {
        "rate": float(fit_df["liked"].mean()),
        "member_spread": float(member_spread.mean()),
        "film_spread": float(film_spread.mean()),
        "gap": float(gaps.mean()),
        "stars": float(fit_df["stars"].mean()),
        "tenure": float(member_days.mean()),
        "pace": float(pace.mean()),
        "exposure": float(film_days.mean()),
    }
