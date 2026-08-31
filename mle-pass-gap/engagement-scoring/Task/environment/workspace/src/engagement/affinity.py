"""How the member has taken to this kind of film before now."""
import numpy as np
import pandas as pd

from . import history


def add(df, fit_df, smoothing, prior_rate):
    keyed = df.assign(_pair=df["member_id"].astype(str) + "|" + df["primary_genre"])
    fit_keyed = fit_df.assign(_pair=fit_df["member_id"].astype(str) + "|" + fit_df["primary_genre"])
    state = history.state_before(keyed, fit_keyed, "_pair")

    out = df.copy()
    seen = state["prior_n"].to_numpy()
    likes = state["prior_likes"].to_numpy()
    out["f_genre_prior_ratings"] = seen
    weight = seen / (seen + float(smoothing))
    raw = np.divide(likes, seen, out=np.zeros_like(likes), where=seen > 0)
    out["f_genre_like_rate"] = weight * raw + (1.0 - weight) * prior_rate
    return out
