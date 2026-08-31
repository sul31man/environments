"""Design matrix assembly."""
import numpy as np

FEATURES = [
    "f_hour", "f_dow", "f_month", "f_is_weekend", "f_days_into_period",
    "f_gender", "f_age_band", "f_occupation", "f_region",
    "f_release_year", "f_film_age_years", "f_genre_count", "f_is_multi_genre",
    "f_mbr_prior_ratings", "f_mbr_prior_likes", "f_mbr_like_rate",
    "f_mbr_mean_stars", "f_mbr_tenure_days", "f_mbr_ratings_per_day", "f_mbr_is_new",
    "f_film_prior_ratings", "f_film_prior_likes", "f_film_like_rate",
    "f_film_mean_stars", "f_film_days_on_shelf", "f_film_is_new",
    "f_genre_prior_ratings", "f_genre_like_rate",
    "f_mbr_stars_spread", "f_film_stars_spread",
    "f_mbr_recent_rate", "f_mbr_days_since_prev",
    "f_occupation_rate", "f_age_band_rate", "f_region_rate",
    "f_mbr_vs_portfolio", "f_film_vs_portfolio", "f_mbr_stars_vs_portfolio",
    "f_genre_vs_member",
]


def matrix(df):
    missing = [c for c in FEATURES if c not in df.columns]
    if missing:
        raise KeyError("design matrix is missing columns: %s" % ", ".join(missing))
    values = df[FEATURES].astype("float64").values
    return np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
