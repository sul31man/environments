"""The film's own record, as of the rating being scored."""
import numpy as np
import pandas as pd

from . import history


def add(df, fit_df, smoothing, prior_rate, prior_stars, prior_exposure):
    """The film's counts, blended rate and mean stars as at each row."""
    state = history.state_before(df, fit_df, "film_id")
    out = df.copy()
    seen = state["prior_n"].to_numpy()
    likes = state["prior_likes"].to_numpy()
    stars = state["prior_stars"].to_numpy()

    out["f_film_prior_ratings"] = seen
    out["f_film_prior_likes"] = likes

    weight = seen / (seen + float(smoothing))
    raw_rate = np.divide(likes, seen, out=np.zeros_like(likes), where=seen > 0)
    out["f_film_like_rate"] = weight * raw_rate + (1.0 - weight) * prior_rate

    mean_stars = np.divide(stars, seen, out=np.full_like(stars, np.nan), where=seen > 0)
    out["f_film_mean_stars"] = np.where(np.isnan(mean_stars), prior_stars, mean_stars)

    exposure = (out["rated_at"] - state["prior_first"]).dt.days.to_numpy(dtype="float64")
    out["f_film_days_on_shelf"] = np.where(np.isnan(exposure), prior_exposure, exposure)

    out["f_film_is_new"] = (seen == 0).astype("int64")
    return out
