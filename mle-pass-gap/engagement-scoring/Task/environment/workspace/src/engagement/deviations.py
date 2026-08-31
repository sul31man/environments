"""How this member and this film sit against the portfolio."""
import numpy as np
import pandas as pd


def add(df, prior_rate, prior_stars):
    out = df.copy()
    out["f_mbr_vs_portfolio"] = (out["f_mbr_like_rate"] - prior_rate).astype("float64")
    out["f_film_vs_portfolio"] = (out["f_film_like_rate"] - prior_rate).astype("float64")
    out["f_mbr_stars_vs_portfolio"] = (out["f_mbr_mean_stars"] - prior_stars).astype("float64")
    out["f_genre_vs_member"] = (out["f_genre_like_rate"] - out["f_mbr_like_rate"]).astype("float64")
    return out
