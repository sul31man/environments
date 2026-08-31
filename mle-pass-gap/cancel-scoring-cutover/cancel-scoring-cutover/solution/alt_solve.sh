#!/usr/bin/env bash
# ALTERNATE-correct solution: the same specification implemented differently.
#
# Rate tables are dicts with a default rather than a catch-all row, basket and
# dispersion totals come from aggregate-and-join rather than transforms, the
# seasonal factor is melted and merged, and the peak month comes from a grouped
# idxmax rather than a row-wise apply.
set -euo pipefail

cd /workspace/target

cat > src/riskscore/account_feats.py <<'RISKSCORE_EOF'
"""Account tenure and history."""
import numpy as np
import pandas as pd


def add(df, accounts):
    first = dict(zip(accounts["account_id"], accounts["first_order_at"]))
    opened = pd.to_datetime(df["account_id"].map(first))
    tenure = (df["placed_at"] - opened).dt.days
    known = df["account_id"].notna().to_numpy()
    return df.assign(
        f_account_tenure_days=tenure.where(tenure.notna(), -1.0).astype("float64"),
        f_account_known=np.where(known, 1, 0).astype("int64"),
    )


def history(fit_df):
    seen = fit_df.dropna(subset=["account_id"]).groupby("account_id")
    return pd.concat(
        [seen["units"].size().rename("acct_orders"),
         seen["units"].sum().rename("acct_units")],
        axis=1).astype("float64")


def attach_history(df, hist):
    orders = df["account_id"].map(hist["acct_orders"])
    units = df["account_id"].map(hist["acct_units"])
    return df.assign(
        f_acct_orders=orders.where(orders.notna(), 0.0).astype("float64"),
        f_acct_units=units.where(units.notna(), 0.0).astype("float64"),
    )
RISKSCORE_EOF

cat > src/riskscore/basket_feats.py <<'RISKSCORE_EOF'
"""Order level aggregates joined back onto each line."""
import numpy as np
import pandas as pd


def add(df):
    out = df.copy()
    out["line_value"] = out["units"] * out["unit_price"]
    totals = out.groupby("order_id").agg(
        f_basket_lines=("sku", "size"),
        f_basket_units=("units", "sum"),
        f_basket_value=("line_value", "sum"),
    )
    out = out.merge(totals, left_on="order_id", right_index=True, how="left", sort=False)
    out["f_basket_lines"] = out["f_basket_lines"].astype("int64")
    out["f_basket_units"] = out["f_basket_units"].astype("float64")
    out["f_basket_value"] = out["f_basket_value"].astype("float64")
    share = out["line_value"].divide(out["f_basket_value"])
    share = share.replace([np.inf, -np.inf], 0.0)
    out["f_line_share"] = share.where(out["f_basket_value"] != 0.0, 0.0).astype("float64")
    return out
RISKSCORE_EOF

cat > src/riskscore/basket_shape.py <<'RISKSCORE_EOF'
"""The shape of the order a line sits in."""
import numpy as np
import pandas as pd


def add(df):
    per_order = df.groupby("order_id").agg(
        _distinct=("sku", "nunique"),
        _max_share=("f_line_share", "max"),
    )
    joined = df.merge(per_order, left_on="order_id", right_index=True, how="left", sort=False)
    lines = joined["f_basket_lines"].to_numpy(dtype="float64")
    value = joined["f_basket_value"].to_numpy(dtype="float64")
    mean_line = np.divide(value, lines, out=np.zeros_like(value), where=lines != 0)
    return joined.assign(
        f_basket_distinct_skus=joined["_distinct"].astype("float64"),
        f_basket_max_line_share=joined["_max_share"].astype("float64"),
        f_basket_mean_line_value=mean_line.astype("float64"),
    ).drop(columns=["_distinct", "_max_share"])
RISKSCORE_EOF

cat > src/riskscore/cadence.py <<'RISKSCORE_EOF'
"""How regularly the product trades and the account orders."""
import numpy as np
import pandas as pd


def sku_trade_days(fit_df):
    days = fit_df["placed_at"].dt.floor("D")
    return fit_df.assign(_d=days).groupby("sku")["_d"].nunique().astype("float64")


def account_gap(fit_df):
    seen = fit_df.dropna(subset=["account_id"]).assign(_d=fit_df["placed_at"].dt.floor("D"))
    distinct = seen[["account_id", "_d"]].drop_duplicates().sort_values(["account_id", "_d"])
    diffs = distinct.groupby("account_id")["_d"].diff().dt.days
    distinct = distinct.assign(_gap=diffs)
    gaps = distinct.groupby("account_id")["_gap"].mean().astype("float64")
    return gaps, float(gaps.mean())


def add(df, trade_days, gaps, portfolio_gap):
    days = df["sku"].astype(str).map(trade_days)
    gap = df["account_id"].map(gaps)
    return df.assign(
        f_sku_trade_days=days.where(days.notna(), 0.0).astype("float64"),
        f_account_order_gap=gap.where(gap.notna(), portfolio_gap).astype("float64"),
    )
RISKSCORE_EOF

cat > src/riskscore/calendar_feats.py <<'RISKSCORE_EOF'
"""Seasonality and time-of-order features."""
import numpy as np
import pandas as pd


def add(df):
    ts = df["placed_at"]
    iso = ts.dt.isocalendar()
    dow = ts.dt.dayofweek.to_numpy(dtype="int64")
    elapsed = (ts - ts.min()) // pd.Timedelta(days=1)
    return df.assign(
        f_hour=ts.dt.hour.to_numpy(dtype="int64"),
        f_dow=dow,
        f_month=ts.dt.month.to_numpy(dtype="int64"),
        f_week=iso["week"].to_numpy(dtype="int64"),
        f_is_weekend=np.where(dow >= 5, 1, 0).astype("int64"),
        f_days_since_epoch=elapsed.to_numpy(dtype="int64"),
    )
RISKSCORE_EOF

cat > src/riskscore/concentration.py <<'RISKSCORE_EOF'
"""How wide a price band a sku has traded in over the fit window."""
import numpy as np
import pandas as pd

CATCH_ALL = "__unlisted__"


def price_range(fit_df):
    stats = fit_df.groupby("sku")["unit_price"].agg(["min", "max"])
    band = (stats["max"] - stats["min"]).astype("float64")
    band.loc[CATCH_ALL] = float(band.mean())
    return band


def add(df, spread):
    out = df.copy()
    values = out["sku"].astype(str).map(spread)
    out["f_sku_price_range"] = values.fillna(spread.loc[CATCH_ALL]).astype("float64")
    return out
RISKSCORE_EOF

cat > src/riskscore/dispersion.py <<'RISKSCORE_EOF'
"""Per sku price dispersion, measured on the fit window.

Dispersion is the mean absolute deviation of the line price about that sku's mean
price. Lines priced unusually for their own sku are the ones that get sent back.
"""
import numpy as np
import pandas as pd

CATCH_ALL = "__unlisted__"


def price_dispersion(fit_df):
    frame = fit_df[["sku", "unit_price"]].copy()
    frame["sku_mean"] = frame.groupby("sku")["unit_price"].transform("mean")
    frame["abs_gap"] = (frame["unit_price"] - frame["sku_mean"]).abs()
    spread = frame.groupby("sku")["abs_gap"].mean().astype("float64")
    spread.loc[CATCH_ALL] = float(spread.mean())
    return spread


def add(df, dispersion):
    out = df.copy()
    values = out["sku"].astype(str).map(dispersion)
    out["f_sku_price_dispersion"] = values.fillna(
        dispersion.loc[CATCH_ALL]).astype("float64")
    return out
RISKSCORE_EOF

cat > src/riskscore/encoders.py <<'RISKSCORE_EOF'
"""Categorical rate encoding.

Rates are fitted on the fit window only. A level carrying little history is shrunk
toward the portfolio rate in proportion to how little history it has. A level with no
history at all resolves to the portfolio rate.
"""
import numpy as np
import pandas as pd


class RateEncoder(object):
    def __init__(self, column, smoothing):
        self.column = column
        self.smoothing = float(smoothing)
        self.prior_ = None
        self.rates_ = None

    def fit(self, df, label):
        self.prior_ = float(df[label].mean())
        grouped = df.groupby(self.column)[label]
        counts = grouped.size().astype("float64")
        means = grouped.mean().astype("float64")
        weight = counts / (counts + self.smoothing)
        self.rates_ = dict(weight * means + (1.0 - weight) * self.prior_)
        return self

    def transform(self, df):
        keys = df[self.column].astype(str)
        return keys.map(self.rates_).fillna(self.prior_).astype("float64").values


def fit_all(fit_df, columns, smoothing, label):
    return {c: RateEncoder(c, smoothing).fit(fit_df, label) for c in columns}


def apply_all(df, encoders):
    out = df.copy()
    for column, enc in encoders.items():
        out["f_rate_" + column] = enc.transform(out)
    return out
RISKSCORE_EOF

cat > src/riskscore/labels.py <<'RISKSCORE_EOF'
"""Derives the return label from the order and credit exports."""
import numpy as np
import pandas as pd


def attach_label(orders, returns, window_days):
    first = (returns.assign(_k=returns["account_id"].astype(str) + "|" + returns["sku"].astype(str))
             .groupby("_k", as_index=False)["raised_at"].min()
             .rename(columns={"raised_at": "_ret_at"}))
    out = orders.assign(_k=orders["account_id"].astype(str) + "|" + orders["sku"].astype(str))
    out = out.merge(first, on="_k", how="left", sort=False)
    elapsed = (out["_ret_at"] - out["placed_at"]).dt.days
    within = elapsed.between(0, window_days, inclusive="both")
    out["label"] = np.where(within.to_numpy(), 1, 0).astype("int64")
    return out.drop(columns=["_k", "_ret_at"])
RISKSCORE_EOF

cat > src/riskscore/model.py <<'RISKSCORE_EOF'
"""Estimator."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


class RiskModel(object):
    def __init__(self, seed, max_iter, regularisation):
        self.seed = int(seed)
        self.max_iter = int(max_iter)
        self.regularisation = float(regularisation)
        self.pipeline_ = None

    def fit(self, X, y):
        self.pipeline_ = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=self.regularisation, max_iter=self.max_iter,
                               random_state=self.seed, solver="lbfgs"),
        ).fit(X, y)
        return self

    def score(self, X):
        return self.pipeline_.predict_proba(X)[:, 1]
RISKSCORE_EOF

cat > src/riskscore/peak.py <<'RISKSCORE_EOF'
"""The calendar month in which an account spends most, measured on the fit window."""
import numpy as np
import pandas as pd


def peak_month(fit_df):
    spend = fit_df["units"].to_numpy(dtype="float64") * fit_df["unit_price"].to_numpy(dtype="float64")
    tally = (fit_df.assign(_spend=spend)
             .groupby(["account_id", "f_month"], sort=True)["_spend"].sum())
    winners = tally.groupby(level="account_id").idxmax()
    months = [key[1] for key in winners.to_numpy()]
    return pd.Series(months, index=winners.index, dtype="float64")


def add(df, peaks, default):
    lookup = peaks.to_dict()
    chosen = np.array([lookup.get(acct, default) for acct in df["account_id"]], dtype="float64")
    return df.assign(
        f_peak_month=chosen,
        f_in_peak_month=(chosen == df["f_month"].to_numpy(dtype="float64")).astype("int64"),
    )
RISKSCORE_EOF

cat > src/riskscore/price_position.py <<'RISKSCORE_EOF'
"""Where a line's price sits against the product's and the market's own history."""
import numpy as np
import pandas as pd


def market_mean_price(fit_df):
    by_market = fit_df.groupby("market")["unit_price"].mean().astype("float64")
    return by_market, float(by_market.mean())


def add(df, mean_price, portfolio):
    price = df["unit_price"].to_numpy(dtype="float64")
    sku_mean = df["f_sku_mean_price"].to_numpy(dtype="float64")
    against_sku = np.divide(price, sku_mean, out=np.zeros_like(price), where=sku_mean != 0.0)

    looked = df["market"].astype(str).map(mean_price)
    market = looked.where(looked.notna(), portfolio).to_numpy(dtype="float64")
    against_market = np.divide(price, market, out=np.zeros_like(price), where=market != 0.0)
    return df.assign(
        f_price_vs_sku_mean=against_sku.astype("float64"),
        f_price_vs_market_mean=against_market.astype("float64"),
    )
RISKSCORE_EOF

cat > src/riskscore/recency.py <<'RISKSCORE_EOF'
"""How long since the product and the account were last active."""
import numpy as np
import pandas as pd


def sku_last_trade(fit_df):
    return fit_df.groupby("sku")["placed_at"].max()


def account_last_order(fit_df):
    return fit_df.dropna(subset=["account_id"]).groupby("account_id")["placed_at"].max()


def staleness(last_seen, fit_end):
    gap = fit_end.to_datetime64() - last_seen.to_numpy(dtype="datetime64[ns]")
    return pd.Series(gap.astype("timedelta64[D]").astype("float64"), index=last_seen.index)


def add(df, sku_stale, account_stale, portfolio_stale):
    sku_gap = df["sku"].astype(str).map(sku_stale)
    acct_gap = df["account_id"].map(account_stale)
    return df.assign(
        f_sku_days_since_trade=sku_gap.where(sku_gap.notna(), portfolio_stale).astype("float64"),
        f_account_days_since_order=acct_gap.where(acct_gap.notna(), -1.0).astype("float64"),
    )
RISKSCORE_EOF

cat > src/riskscore/return_history.py <<'RISKSCORE_EOF'
"""How often the account and the product have been returned before."""
import numpy as np
import pandas as pd


def counts(fit_df, label):
    hit = fit_df.loc[fit_df[label].to_numpy() == 1]
    return (hit["account_id"].value_counts().astype("float64"),
            hit["sku"].value_counts().astype("float64"))


def account_rate(fit_df, label, smoothing):
    prior = float(fit_df[label].mean())
    seen = fit_df.dropna(subset=["account_id"])
    tally = seen.groupby("account_id")[label].agg(["size", "mean"]).astype("float64")
    k = float(smoothing)
    blended = (tally["size"] * tally["mean"] + k * prior) / (tally["size"] + k)
    return blended.astype("float64"), prior


def add(df, acct_counts, sku_counts, rates, prior):
    a = df["account_id"].map(acct_counts)
    s = df["sku"].astype(str).map(sku_counts)
    r = df["account_id"].map(rates)
    return df.assign(
        f_acct_prior_returns=a.where(a.notna(), 0.0).astype("float64"),
        f_sku_prior_returns=s.where(s.notna(), 0.0).astype("float64"),
        f_acct_return_rate=r.where(r.notna(), prior).astype("float64"),
    )
RISKSCORE_EOF

cat > src/riskscore/seasonal.py <<'RISKSCORE_EOF'
"""Seasonal factor by calendar month, measured on the fit window."""
import numpy as np
import pandas as pd

MONTHS = list(range(1, 13))


def factor_table(fit_df, label):
    grouped = fit_df.groupby("f_month", sort=True)[label].mean()
    return grouped.reindex(MONTHS).astype("float64")


def add(df, factors):
    lookup = factors.to_dict()
    fallback = float(np.nanmean(list(lookup.values())))
    values = np.array([lookup.get(m, np.nan) for m in df["f_month"].to_numpy()],
                      dtype="float64")
    values = np.where(np.isnan(values), fallback, values)
    return df.assign(f_seasonal=values)
RISKSCORE_EOF

cat > src/riskscore/segment.py <<'RISKSCORE_EOF'
"""Coarse behavioural segmentation used as a model input."""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEGMENT_INPUTS = ["f_basket_value", "f_basket_lines", "f_sku_mean_price",
                  "f_acct_orders"]
RESTARTS = 10


class Segmenter(object):
    def __init__(self, n_segments, seed):
        self.n_segments = int(n_segments)
        self.seed = int(seed)
        self.pipeline_ = None

    def _inputs(self, df):
        raw = df.loc[:, SEGMENT_INPUTS].to_numpy(dtype="float64")
        clean = np.where(np.isfinite(raw), raw, 0.0)
        return clean

    def fit(self, df):
        self.pipeline_ = make_pipeline(
            StandardScaler(),
            KMeans(n_clusters=self.n_segments, random_state=self.seed, n_init=RESTARTS),
        ).fit(self._inputs(df))
        return self

    def _ranking(self):
        km = self.pipeline_.steps[-1][1]
        first_axis = km.cluster_centers_[:, 0]
        ranks = np.empty(self.n_segments, dtype="int64")
        ranks[np.argsort(first_axis, kind="stable")] = np.arange(self.n_segments)
        return ranks

    def transform(self, df):
        assigned = self.pipeline_.predict(self._inputs(df))
        return self._ranking()[assigned]


def add(df, segmenter):
    return df.assign(f_segment=segmenter.transform(df).astype("int64"))
RISKSCORE_EOF

cat > src/riskscore/sku_feats.py <<'RISKSCORE_EOF'
"""Catalogue join and per sku history."""
import numpy as np
import pandas as pd


def add(df, catalogue):
    listed = dict(zip(catalogue["sku"].astype(str), catalogue["first_listed"]))
    first = pd.to_datetime(df["sku"].astype(str).map(listed))
    age = (df["placed_at"] - first).dt.days
    filled = age.where(age.notna(), -1.0).astype("float64")
    return df.assign(
        f_sku_age_days=filled,
        f_sku_is_new=np.where(filled.to_numpy() < 0, 1, 0).astype("int64"),
    )


def history(fit_df):
    grouped = fit_df.groupby("sku")
    stats = pd.concat(
        [grouped["units"].size().rename("sku_orders"),
         grouped["units"].sum().rename("sku_units"),
         grouped["unit_price"].mean().rename("sku_mean_price")],
        axis=1)
    return stats.astype("float64")


def attach_history(df, hist):
    keys = df["sku"].astype(str)
    orders = keys.map(hist["sku_orders"])
    units = keys.map(hist["sku_units"])
    price = keys.map(hist["sku_mean_price"])
    portfolio_price = float(hist["sku_mean_price"].mean())
    return df.assign(
        f_sku_orders=orders.where(orders.notna(), 0.0).astype("float64"),
        f_sku_units=units.where(units.notna(), 0.0).astype("float64"),
        f_sku_mean_price=price.where(price.notna(), portfolio_price).astype("float64"),
    )
RISKSCORE_EOF

cat > src/riskscore/velocity.py <<'RISKSCORE_EOF'
"""How fast a sku has been selling, once short-run noise is smoothed out."""
import numpy as np
import pandas as pd

WINDOW_DAYS = 10
CATCH_ALL = "__unlisted__"


def sku_velocity(fit_df):
    readings = {}
    for sku, block in fit_df.groupby("sku", sort=True):
        per_day = block.set_index("placed_at")["units"].resample("D").sum()
        smoothed = per_day.rolling(WINDOW_DAYS, min_periods=WINDOW_DAYS).mean()
        readings[sku] = smoothed.mean()
    speed = pd.Series(readings, dtype="float64")
    speed.index.name = "sku"
    portfolio = float(speed.mean())
    speed = speed.where(speed.notna(), portfolio)
    return pd.concat([speed, pd.Series({CATCH_ALL: portfolio}, dtype="float64")])


def add(df, velocity):
    known = set(velocity.index)
    keys = df["sku"].astype(str)
    keys = pd.Series(np.where(keys.isin(known), keys, CATCH_ALL), index=df.index)
    return df.assign(f_sku_velocity=velocity.reindex(keys).to_numpy(dtype="float64"))
RISKSCORE_EOF

python3 run_scoring.py --config configs/reference.yaml --out out/reference
python3 run_scoring.py --config configs/current.yaml   --out out/current
echo "rebuild complete"
