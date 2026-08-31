"""What the catalogue says about the film."""
import numpy as np
import pandas as pd


def add(df, films):
    out = df.merge(films, on="film_id", how="left", sort=False)
    year = pd.to_numeric(out["release_year"], errors="coerce")
    out["f_release_year"] = year.fillna(-1.0).astype("float64")
    age = out["rated_at"].dt.year - year
    out["f_film_age_years"] = age.fillna(-1.0).astype("float64")
    genres = out["genres"].fillna("")
    out["f_genre_count"] = genres.apply(lambda g: len(g.split("|")) if g else 0).astype("int64")
    out["f_is_multi_genre"] = (out["f_genre_count"] > 1).astype("int64")
    out["primary_genre"] = genres.apply(lambda g: g.split("|")[0] if g else "")
    return out.drop(columns=["title", "genres", "release_year"])
