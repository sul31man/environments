"""Fits on the fit window and scores the window the run config names."""
import numpy as np
import pandas as pd

from . import (affinity, assemble, calendar_feats, cohort, deviations,
               film_history, film_profile, io_layer, member_history,
               member_profile, model, portfolio, recent, spread)


def _window(df, spec):
    lo = pd.Timestamp(spec["from"])
    hi = pd.Timestamp(spec["to"]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return df[(df["rated_at"] >= lo) & (df["rated_at"] <= hi)]


def build(cfg):
    ratings = io_layer.read_ratings(cfg)
    members = io_layer.read_members(cfg)
    films = io_layer.read_films(cfg)

    fit_raw = _window(ratings, cfg["windows"]["fit"])
    score_raw = _window(ratings, cfg["windows"]["score"])
    level = portfolio.levels(fit_raw)
    smoothing = cfg["encoding"]["smoothing"]

    def prepare(frame):
        out = calendar_feats.add(frame)
        out = member_profile.add(out, members)
        out = film_profile.add(out, films)
        return out

    fit_df = prepare(fit_raw)
    score_df = prepare(score_raw)
    fit_source = fit_df

    occupation_rates = cohort.rates(fit_source, "f_occupation", smoothing, level["rate"])
    age_rates = cohort.rates(fit_source, "f_age_band", smoothing, level["rate"])
    region_rates = cohort.rates(fit_source, "f_region", smoothing, level["rate"])

    def enrich(frame):
        out = member_history.add(frame, fit_source, smoothing, level["rate"],
                                 level["stars"], level["tenure"], level["pace"])
        out = film_history.add(out, fit_source, smoothing, level["rate"],
                               level["stars"], level["exposure"])
        out = affinity.add(out, fit_source, smoothing, level["rate"])
        out = spread.add(out, fit_source, level["member_spread"], level["film_spread"])
        out = recent.add(out, fit_source, level["rate"], level["gap"])
        out = cohort.add(out, occupation_rates, age_rates, region_rates, level["rate"])
        out = deviations.add(out, level["rate"], level["stars"])
        return out

    return enrich(fit_df), enrich(score_df)


def run(cfg):
    fit_df, score_df = build(cfg)
    mdl = model.EngagementModel(cfg["model"]["seed"], cfg["model"]["max_iter"],
                                cfg["model"]["regularisation"])
    mdl.fit(assemble.matrix(fit_df), fit_df["liked"].astype("int64").values)

    scores = mdl.score(assemble.matrix(score_df))
    threshold = float(cfg["scoring"]["promote_threshold"])
    out = pd.DataFrame({
        "rating_id": score_df["rating_id"].astype(str).values,
        "member_id": score_df["member_id"].astype("int64").values,
        "film_id": score_df["film_id"].astype("int64").values,
        "rated_at": score_df["rated_at"].values,
        "engagement": np.round(scores, 6),
        "promote": (scores >= threshold).astype("int64"),
    })
    return out, fit_df, score_df
