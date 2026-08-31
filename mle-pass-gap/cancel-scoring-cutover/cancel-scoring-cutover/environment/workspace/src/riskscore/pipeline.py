"""Fits on the fit window and scores the window the run config names."""
import numpy as np
import pandas as pd

from . import (account_feats, assemble, basket_feats, basket_shape, cadence,
               calendar_feats, concentration, dispersion, encoders, hygiene,
               io_layer, labels, model, peak, price_position, recency,
               return_history, seasonal, segment, sku_feats, velocity)


def _window(df, spec):
    lo = pd.Timestamp(spec["from"])
    hi = pd.Timestamp(spec["to"]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return df[(df["placed_at"] >= lo) & (df["placed_at"] <= hi)]


def _shared_features(df):
    out = calendar_feats.add(df)
    out = basket_feats.add(out)
    out = basket_shape.add(out)
    return out


def build(cfg):
    orders = io_layer.read_orders(cfg)
    hygiene.check_orders(orders)
    returns = io_layer.read_returns(cfg)
    catalogue = io_layer.read_catalogue(cfg)
    accounts = io_layer.read_accounts(cfg)

    orders = labels.attach_label(orders, returns, cfg["labelling"]["window_days"])
    orders = orders.sort_values("line_id").reset_index(drop=True)

    fit_raw = _window(orders, cfg["windows"]["fit"])
    score_raw = _window(orders, cfg["windows"]["score"])

    sku_hist = sku_feats.history(fit_raw)
    acct_hist = account_feats.history(fit_raw)

    def prepare(frame):
        out = _shared_features(frame)
        out = sku_feats.add(out, catalogue)
        out = sku_feats.attach_history(out, sku_hist)
        out = account_feats.add(out, accounts)
        out = account_feats.attach_history(out, acct_hist)
        return out

    fit_df = prepare(fit_raw)
    score_df = prepare(score_raw)

    market_price, market_price_prior = price_position.market_mean_price(fit_raw)
    fit_df = price_position.add(fit_df, market_price, market_price_prior)
    score_df = price_position.add(score_df, market_price, market_price_prior)

    fit_end = fit_raw["placed_at"].max()
    sku_stale = recency.staleness(recency.sku_last_trade(fit_raw), fit_end)
    account_stale = recency.staleness(recency.account_last_order(fit_raw), fit_end)
    stale_prior = float(sku_stale.mean())
    fit_df = recency.add(fit_df, sku_stale, account_stale, stale_prior)
    score_df = recency.add(score_df, sku_stale, account_stale, stale_prior)

    acct_counts, sku_counts = return_history.counts(fit_df, "label")
    acct_rates, rate_prior = return_history.account_rate(
        fit_df, "label", cfg["encoding"]["smoothing"])
    fit_df = return_history.add(fit_df, acct_counts, sku_counts, acct_rates, rate_prior)
    score_df = return_history.add(score_df, acct_counts, sku_counts, acct_rates, rate_prior)

    trade_days = cadence.sku_trade_days(fit_raw)
    gaps, gap_portfolio = cadence.account_gap(fit_raw)
    fit_df = cadence.add(fit_df, trade_days, gaps, gap_portfolio)
    score_df = cadence.add(score_df, trade_days, gaps, gap_portfolio)

    spread = dispersion.price_dispersion(fit_raw)
    fit_df = dispersion.add(fit_df, spread)
    score_df = dispersion.add(score_df, spread)

    speed = velocity.sku_velocity(fit_raw)
    fit_df = velocity.add(fit_df, speed)
    score_df = velocity.add(score_df, speed)

    band = concentration.price_range(fit_raw)
    fit_df = concentration.add(fit_df, band)
    score_df = concentration.add(score_df, band)

    peaks = peak.peak_month(fit_df)
    default_peak = float(fit_df["f_month"].median())
    fit_df = peak.add(fit_df, peaks, default_peak)
    score_df = peak.add(score_df, peaks, default_peak)

    factors = seasonal.factor_table(fit_df, "label")
    fit_df = seasonal.add(fit_df, factors)
    score_df = seasonal.add(score_df, factors)

    encs = encoders.fit_all(fit_df, cfg["encoding"]["columns"],
                            cfg["encoding"]["smoothing"], "label")
    fit_df = encoders.apply_all(fit_df, encs)
    score_df = encoders.apply_all(score_df, encs)

    seg = segment.Segmenter(cfg["segmentation"]["n_segments"],
                            cfg["segmentation"]["seed"]).fit(fit_df)
    fit_df = segment.add(fit_df, seg)
    score_df = segment.add(score_df, seg)
    return fit_df, score_df


def run(cfg):
    fit_df, score_df = build(cfg)

    mdl = model.RiskModel(cfg["model"]["seed"], cfg["model"]["max_iter"],
                          cfg["model"]["regularisation"])
    mdl.fit(assemble.matrix(fit_df), fit_df["label"].astype("int64").values)

    scores = mdl.score(assemble.matrix(score_df))
    threshold = float(cfg["scoring"]["hold_threshold"])
    out = pd.DataFrame({
        "line_id": score_df["line_id"].astype(str).values,
        "order_id": score_df["order_id"].astype(str).values,
        "sku": score_df["sku"].astype(str).values,
        "placed_at": score_df["placed_at"].values,
        "risk_score": np.round(scores, 6),
        "hold": (scores >= threshold).astype("int64"),
    })
    return out, fit_df, score_df
