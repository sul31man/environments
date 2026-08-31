#!/usr/bin/env bash
# The peak month is read as a position rather than as the month itself.
set -euo pipefail

cd /workspace/target

cat > src/riskscore/account_feats.py <<'RISKSCORE_EOF'
"""Account tenure and history."""
import numpy as np
import pandas as pd


def add(df, accounts):
    out = df.merge(accounts[["account_id", "first_order_at"]], on="account_id",
                   how="left", sort=False)
    tenure = (out["placed_at"] - out["first_order_at"]).dt.days
    out["f_account_tenure_days"] = tenure.fillna(-1.0).astype("float64")
    out["f_account_known"] = out["account_id"].notna().astype("int64")
    return out


def history(fit_df):
    known = fit_df[fit_df["account_id"].notna()]
    g = known.groupby("account_id")
    return pd.DataFrame({
        "acct_orders": g.size().astype("float64"),
        "acct_units": g["units"].sum().astype("float64"),
    })


def attach_history(df, hist):
    out = df.merge(hist, left_on="account_id", right_index=True, how="left", sort=False)
    out["f_acct_orders"] = out["acct_orders"].fillna(0.0).astype("float64")
    out["f_acct_units"] = out["acct_units"].fillna(0.0).astype("float64")
    return out.drop(columns=["acct_orders", "acct_units"])
RISKSCORE_EOF

cat > src/riskscore/basket_feats.py <<'RISKSCORE_EOF'
"""Order level aggregates joined back onto each line."""
import numpy as np


def add(df):
    out = df.copy()
    out["line_value"] = out["units"] * out["unit_price"]
    g = out.groupby("order_id")
    out["f_basket_lines"] = g["sku"].transform("size").astype("int64")
    out["f_basket_units"] = g["units"].transform("sum").astype("float64")
    out["f_basket_value"] = g["line_value"].transform("sum").astype("float64")
    out["f_line_share"] = np.where(
        out["f_basket_value"] != 0.0, out["line_value"] / out["f_basket_value"], 0.0
    )
    return out
RISKSCORE_EOF

cat > src/riskscore/basket_shape.py <<'RISKSCORE_EOF'
"""The shape of the order a line sits in."""
import numpy as np
import pandas as pd


def add(df):
    out = df.copy()
    g = out.groupby("order_id")
    out["f_basket_distinct_skus"] = g["sku"].transform("nunique").astype("float64")
    out["f_basket_max_line_share"] = g["f_line_share"].transform("max").astype("float64")
    out["f_basket_mean_line_value"] = np.where(
        out["f_basket_lines"] != 0,
        out["f_basket_value"] / out["f_basket_lines"], 0.0).astype("float64")
    return out
RISKSCORE_EOF

cat > src/riskscore/cadence.py <<'RISKSCORE_EOF'
"""How regularly the product trades and the account orders."""
import numpy as np
import pandas as pd


def sku_trade_days(fit_df):
    days = fit_df.assign(_d=fit_df["placed_at"].dt.floor("D"))
    return days.groupby("sku")["_d"].nunique().astype("float64")


def account_gap(fit_df):
    known = fit_df[fit_df["account_id"].notna()].copy()
    known["_d"] = known["placed_at"].dt.floor("D")
    dates = known.groupby("account_id")["_d"].apply(lambda s: np.sort(s.unique()))

    def mean_gap(arr):
        if len(arr) < 2:
            return np.nan
        return float(np.diff(arr.astype("datetime64[D]").astype("int64")).mean())

    gaps = dates.apply(mean_gap).astype("float64")
    return gaps, float(gaps.mean())


def add(df, trade_days, gaps, portfolio_gap):
    out = df.copy()
    out["f_sku_trade_days"] = out["sku"].astype(str).map(trade_days).fillna(0.0).astype("float64")
    out["f_account_order_gap"] = (out["account_id"].map(gaps)
                                  .fillna(portfolio_gap).astype("float64"))
    return out
RISKSCORE_EOF

cat > src/riskscore/calendar_feats.py <<'RISKSCORE_EOF'
"""Seasonality and time-of-order features."""
import numpy as np


def add(df):
    out = df.copy()
    ts = out["placed_at"]
    out["f_hour"] = ts.dt.hour.astype("int64")
    out["f_dow"] = ts.dt.dayofweek.astype("int64")
    out["f_month"] = ts.dt.month.astype("int64")
    out["f_week"] = ts.dt.isocalendar().week.astype("int64")
    out["f_is_weekend"] = (out["f_dow"] >= 5).astype("int64")
    out["f_days_since_epoch"] = (ts - ts.min()).dt.days.astype("int64")
    return out
RISKSCORE_EOF

cat > src/riskscore/concentration.py <<'RISKSCORE_EOF'
"""How wide a price band a sku has traded in over the fit window."""
import numpy as np
import pandas as pd

CATCH_ALL = "__unlisted__"


def price_range(fit_df):
    grouped = fit_df.groupby("sku")["unit_price"]
    band = (grouped.max() - grouped.min()).astype("float64")
    catch_all = pd.Series({CATCH_ALL: float(band.mean())}, dtype="float64")
    return pd.concat([band, catch_all])


def add(df, spread):
    out = df.copy()
    keys = out["sku"].astype(str)
    keys = keys.where(keys.isin(spread.index), CATCH_ALL)
    out["f_sku_price_range"] = spread.reindex(keys).astype("float64").values
    return out
RISKSCORE_EOF

cat > src/riskscore/dispersion.py <<'RISKSCORE_EOF'
"""How much a sku's price has moved around its own usual level.

Lines priced unusually for their own sku are the ones that get sent back.
"""
import numpy as np
import pandas as pd

CATCH_ALL = "__unlisted__"


def price_dispersion(fit_df):
    grouped = fit_df.groupby("sku")["unit_price"]
    spread = grouped.apply(lambda prices: (prices - prices.mean()).abs().mean())
    spread = spread.astype("float64")
    catch_all = pd.Series({CATCH_ALL: float(spread.mean())}, dtype="float64")
    return pd.concat([spread, catch_all])


def add(df, dispersion):
    out = df.copy()
    keys = out["sku"].astype(str)
    keys = keys.where(keys.isin(dispersion.index), CATCH_ALL)
    out["f_sku_price_dispersion"] = dispersion.reindex(keys).astype("float64").values
    return out
RISKSCORE_EOF

cat > src/riskscore/encoders.py <<'RISKSCORE_EOF'
"""Categorical rate encoding, fitted on the fit window.
"""
import numpy as np
import pandas as pd

CATCH_ALL = "__unlisted__"


class RateEncoder(object):
    def __init__(self, column, smoothing):
        self.column = column
        self.smoothing = float(smoothing)
        self.prior_ = None
        self.rates_ = None

    def fit(self, df, label):
        self.prior_ = float(df[label].mean())
        g = df.groupby(self.column)[label]
        stats = pd.DataFrame({"n": g.size().astype("float64"),
                              "mean": g.mean().astype("float64")})
        weight = stats["n"] / (stats["n"] + self.smoothing)
        rates = weight * stats["mean"] + (1.0 - weight) * self.prior_
        catch_all = pd.Series({CATCH_ALL: self.prior_}, dtype="float64")
        self.rates_ = pd.concat([rates, catch_all])
        return self

    def transform(self, df):
        keys = df[self.column].astype(str)
        keys = keys.where(keys.isin(self.rates_.index), CATCH_ALL)
        return self.rates_.reindex(keys).astype("float64").values


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
import pandas as pd


def attach_label(orders, returns, window_days):
    ret = returns.copy()
    ret["_k"] = ret["account_id"].astype(str) + "|" + ret["sku"].astype(str)
    first = ret.groupby("_k")["raised_at"].min()

    out = orders.copy()
    out["_k"] = out["account_id"].astype(str) + "|" + out["sku"].astype(str)
    out["_ret_at"] = out["_k"].map(first)
    delta = (out["_ret_at"] - out["placed_at"]).dt.days
    out["label"] = ((delta >= 0) & (delta <= window_days)).astype(int)
    return out.drop(columns=["_k", "_ret_at"])
RISKSCORE_EOF

cat > src/riskscore/model.py <<'RISKSCORE_EOF'
"""Estimator."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


class RiskModel(object):
    def __init__(self, seed, max_iter, regularisation):
        self.seed = int(seed)
        self.max_iter = int(max_iter)
        self.regularisation = float(regularisation)
        self.scaler_ = None
        self.clf_ = None

    def fit(self, X, y):
        self.scaler_ = StandardScaler().fit(X)
        self.clf_ = LogisticRegression(
            C=self.regularisation, max_iter=self.max_iter, random_state=self.seed,
            solver="lbfgs",
        ).fit(self.scaler_.transform(X), y)
        return self

    def score(self, X):
        return self.clf_.predict_proba(self.scaler_.transform(X))[:, 1]
RISKSCORE_EOF

cat > src/riskscore/peak.py <<'RISKSCORE_EOF'
"""The calendar month in which an account spends most, measured on the fit window."""
import numpy as np
import pandas as pd

MONTHS = list(range(1, 13))


def peak_month(fit_df):
    spend = fit_df.assign(_v=fit_df["units"] * fit_df["unit_price"])
    table = (spend.pivot_table(index="account_id", columns="f_month", values="_v",
                               aggfunc="sum")
             .reindex(columns=MONTHS))
    return table.apply(lambda row: row.argmax(), axis=1).astype("float64")


def add(df, peaks, default):
    out = df.copy()
    month = out["account_id"].map(peaks)
    out["f_peak_month"] = month.fillna(default).astype("float64")
    out["f_in_peak_month"] = (out["f_peak_month"] == out["f_month"]).astype("int64")
    return out
RISKSCORE_EOF

cat > src/riskscore/price_position.py <<'RISKSCORE_EOF'
"""Where a line's price sits against the product's and the market's own history."""
import numpy as np
import pandas as pd


def market_mean_price(fit_df):
    mean_price = fit_df.groupby("market")["unit_price"].mean().astype("float64")
    portfolio = float(mean_price.mean())
    return mean_price, portfolio


def add(df, mean_price, portfolio):
    out = df.copy()
    sku_mean = out["f_sku_mean_price"].astype("float64")
    out["f_price_vs_sku_mean"] = np.where(
        sku_mean != 0.0, out["unit_price"] / sku_mean, 0.0).astype("float64")

    market = out["market"].astype(str).map(mean_price).fillna(portfolio).astype("float64")
    out["f_price_vs_market_mean"] = np.where(
        market != 0.0, out["unit_price"] / market, 0.0).astype("float64")
    return out
RISKSCORE_EOF

cat > src/riskscore/recency.py <<'RISKSCORE_EOF'
"""How long since the product and the account were last active."""
import numpy as np
import pandas as pd


def sku_last_trade(fit_df):
    return fit_df.groupby("sku")["placed_at"].max()


def account_last_order(fit_df):
    known = fit_df[fit_df["account_id"].notna()]
    return known.groupby("account_id")["placed_at"].max()


def staleness(last_seen, fit_end):
    return (fit_end - last_seen).dt.days.astype("float64")


def add(df, sku_stale, account_stale, portfolio_stale):
    out = df.copy()
    out["f_sku_days_since_trade"] = (out["sku"].astype(str).map(sku_stale)
                                     .fillna(portfolio_stale).astype("float64"))
    out["f_account_days_since_order"] = (out["account_id"].map(account_stale)
                                         .fillna(-1.0).astype("float64"))
    return out
RISKSCORE_EOF

cat > src/riskscore/return_history.py <<'RISKSCORE_EOF'
"""How often the account and the product have been returned before."""
import numpy as np
import pandas as pd


def counts(fit_df, label):
    returned = fit_df[fit_df[label] == 1]
    return (returned.groupby("account_id").size().astype("float64"),
            returned.groupby("sku").size().astype("float64"))


def account_rate(fit_df, label, smoothing):
    known = fit_df[fit_df["account_id"].notna()]
    prior = float(fit_df[label].mean())
    g = known.groupby("account_id")[label]
    n = g.size().astype("float64")
    mean = g.mean().astype("float64")
    weight = n / (n + float(smoothing))
    return weight * mean + (1.0 - weight) * prior, prior


def add(df, acct_counts, sku_counts, rates, prior):
    out = df.copy()
    out["f_acct_prior_returns"] = out["account_id"].map(acct_counts).fillna(0.0).astype("float64")
    out["f_sku_prior_returns"] = out["sku"].astype(str).map(sku_counts).fillna(0.0).astype("float64")
    out["f_acct_return_rate"] = out["account_id"].map(rates).fillna(prior).astype("float64")
    return out
RISKSCORE_EOF

cat > src/riskscore/seasonal.py <<'RISKSCORE_EOF'
"""Seasonal factor by calendar month, measured on the fit window."""
import numpy as np
import pandas as pd

MONTHS = list(range(1, 13))


def factor_table(fit_df, label):
    table = fit_df.groupby("f_month")[label].mean().reindex(MONTHS)
    return table.astype("float64")


def add(df, factors):
    looked_up = df["f_month"].map(factors)
    portfolio_factor = float(np.nanmean(factors.values))
    out = df.copy()
    out["f_seasonal"] = looked_up.fillna(portfolio_factor).astype("float64")
    return out
RISKSCORE_EOF

cat > src/riskscore/segment.py <<'RISKSCORE_EOF'
"""Coarse behavioural segmentation used as a model input."""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

SEGMENT_INPUTS = ["f_basket_value", "f_basket_lines", "f_sku_mean_price",
                  "f_acct_orders"]

RESTARTS = 10


class Segmenter(object):
    def __init__(self, n_segments, seed):
        self.n_segments = int(n_segments)
        self.seed = int(seed)
        self.scaler_ = None
        self.model_ = None

    def _inputs(self, df):
        X = df[SEGMENT_INPUTS].astype("float64").values
        return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, df):
        X = self._inputs(df)
        self.scaler_ = StandardScaler().fit(X)
        self.model_ = KMeans(n_clusters=self.n_segments, random_state=self.seed,
                             n_init=RESTARTS).fit(self.scaler_.transform(X))
        return self

    def _order(self):
        centres = self.model_.cluster_centers_[:, 0]
        order = np.argsort(centres, kind="stable")
        lookup = np.zeros(self.n_segments, dtype="int64")
        for rank, cluster in enumerate(order):
            lookup[cluster] = rank
        return lookup

    def transform(self, df):
        X = self._inputs(df)
        raw = self.model_.predict(self.scaler_.transform(X))
        return self._order()[raw]


def add(df, segmenter):
    out = df.copy()
    out["f_segment"] = segmenter.transform(out).astype("int64")
    return out
RISKSCORE_EOF

cat > src/riskscore/sku_feats.py <<'RISKSCORE_EOF'
"""Catalogue join and per sku history."""
import numpy as np
import pandas as pd


def add(df, catalogue):
    out = df.merge(catalogue[["sku", "first_listed"]], on="sku", how="left", sort=False)
    age = (out["placed_at"] - out["first_listed"]).dt.days
    out["f_sku_age_days"] = age.fillna(-1.0).astype("float64")
    out["f_sku_is_new"] = (out["f_sku_age_days"] < 0).astype("int64")
    return out


def history(fit_df):
    stats = fit_df.groupby("sku").agg(
        sku_orders=("units", "size"),
        sku_units=("units", "sum"),
        sku_mean_price=("unit_price", "mean"),
    )
    return stats.astype("float64")


def attach_history(df, hist):
    out = df.merge(hist, left_on="sku", right_index=True, how="left", sort=False)
    out["f_sku_orders"] = out["sku_orders"].fillna(0.0).astype("float64")
    out["f_sku_units"] = out["sku_units"].fillna(0.0).astype("float64")
    portfolio_price = float(hist["sku_mean_price"].mean())
    out["f_sku_mean_price"] = (out["sku_mean_price"]
                               .fillna(portfolio_price).astype("float64"))
    return out.drop(columns=["sku_orders", "sku_units", "sku_mean_price"])
RISKSCORE_EOF

cat > src/riskscore/velocity.py <<'RISKSCORE_EOF'
"""How fast a sku has been selling, once short-run noise is smoothed out.
"""
import numpy as np
import pandas as pd

WINDOW_DAYS = 10
CATCH_ALL = "__unlisted__"


def sku_velocity(fit_df):
    daily = (fit_df.set_index("placed_at")
             .groupby("sku")["units"]
             .resample("D").sum())
    smoothed = (daily.groupby(level=0)
                .apply(lambda s: s.rolling(WINDOW_DAYS, min_periods=WINDOW_DAYS).mean()))
    speed = smoothed.groupby(level=0).mean().astype("float64")
    portfolio = float(speed.mean())
    speed = speed.fillna(portfolio)
    catch_all = pd.Series({CATCH_ALL: portfolio}, dtype="float64")
    return pd.concat([speed, catch_all])


def add(df, velocity):
    out = df.copy()
    keys = out["sku"].astype(str)
    keys = keys.where(keys.isin(velocity.index), CATCH_ALL)
    out["f_sku_velocity"] = velocity.reindex(keys).astype("float64").values
    return out
RISKSCORE_EOF

python3 run_scoring.py --config configs/reference.yaml --out out/reference
python3 run_scoring.py --config configs/current.yaml   --out out/current
