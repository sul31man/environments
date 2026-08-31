#!/usr/bin/env bash
# SECOND alternate-correct solution: a third independent implementation.
#
# Written against numpy rather than pandas idiom wherever it can be: bincount over
# factorised keys instead of groupby aggregates, explicit dictionaries for the
# canonical segment ordering and the credit index, boolean masks instead of fillna,
# and per-group loops where the reference vectorises.
set -euo pipefail

cd /workspace/target

cat > src/riskscore/account_feats.py <<'RISKSCORE_EOF'
"""Account tenure and history."""
import numpy as np
import pandas as pd


def add(df, accounts):
    out = df.copy()
    opened = pd.Series(accounts["first_order_at"].to_numpy(),
                       index=accounts["account_id"].to_numpy())
    matched = pd.to_datetime(pd.Series(out["account_id"].map(opened).to_numpy(), index=out.index))
    tenure = (out["placed_at"] - matched).dt.days.to_numpy(dtype="float64")
    out["f_account_tenure_days"] = np.where(np.isnan(tenure), -1.0, tenure)
    out["f_account_known"] = (~out["account_id"].isna()).to_numpy().astype("int64")
    return out


def history(fit_df):
    known = fit_df[~fit_df["account_id"].isna()]
    return pd.DataFrame({
        "acct_orders": known.groupby("account_id")["units"].count(),
        "acct_units": known.groupby("account_id")["units"].sum(),
    }).astype("float64")


def attach_history(df, hist):
    out = df.copy()
    for column, feature in (("acct_orders", "f_acct_orders"), ("acct_units", "f_acct_units")):
        values = out["account_id"].map(hist[column]).to_numpy(dtype="float64")
        out[feature] = np.where(np.isnan(values), 0.0, values)
    return out
RISKSCORE_EOF

cat > src/riskscore/basket_feats.py <<'RISKSCORE_EOF'
"""Order level aggregates joined back onto each line."""
import numpy as np
import pandas as pd


def add(df):
    out = df.copy()
    value = out["units"].to_numpy(dtype="float64") * out["unit_price"].to_numpy(dtype="float64")
    out["line_value"] = value

    orders = out["order_id"].to_numpy()
    codes, index = pd.factorize(orders)
    lines = np.bincount(codes, minlength=len(index)).astype("float64")
    units = np.bincount(codes, weights=out["units"].to_numpy(dtype="float64"), minlength=len(index))
    totals = np.bincount(codes, weights=value, minlength=len(index))

    out["f_basket_lines"] = lines[codes].astype("int64")
    out["f_basket_units"] = units[codes]
    basket_value = totals[codes]
    out["f_basket_value"] = basket_value
    share = np.zeros_like(value)
    live = basket_value != 0.0
    share[live] = value[live] / basket_value[live]
    out["f_line_share"] = share
    return out
RISKSCORE_EOF

cat > src/riskscore/basket_shape.py <<'RISKSCORE_EOF'
"""The shape of the order a line sits in."""
import numpy as np
import pandas as pd


def add(df):
    out = df.copy()
    grouped = out.groupby("order_id")
    distinct = grouped["sku"].nunique()
    biggest = grouped["f_line_share"].max()
    orders = out["order_id"]
    out["f_basket_distinct_skus"] = np.asarray(orders.map(distinct), dtype="float64")
    out["f_basket_max_line_share"] = np.asarray(orders.map(biggest), dtype="float64")

    lines = out["f_basket_lines"].to_numpy(dtype="float64")
    value = out["f_basket_value"].to_numpy(dtype="float64")
    mean_line = np.zeros_like(value)
    live = lines != 0
    mean_line[live] = value[live] / lines[live]
    out["f_basket_mean_line_value"] = mean_line
    return out
RISKSCORE_EOF

cat > src/riskscore/cadence.py <<'RISKSCORE_EOF'
"""How regularly the product trades and the account orders."""
import numpy as np
import pandas as pd


def sku_trade_days(fit_df):
    stamped = fit_df.assign(_day=fit_df["placed_at"].dt.floor("D"))
    return stamped.groupby("sku")["_day"].agg(lambda days: len(set(days))).astype("float64")


def account_gap(fit_df):
    known = fit_df[~fit_df["account_id"].isna()]
    stamped = known.assign(_day=known["placed_at"].dt.floor("D"))
    spans = {}
    for account, block in stamped.groupby("account_id"):
        days = np.sort(np.unique(block["_day"].to_numpy(dtype="datetime64[D]")))
        spans[account] = np.diff(days.astype("int64")).mean() if len(days) > 1 else np.nan
    table = pd.Series(spans, dtype="float64").sort_index()
    return table, float(table.mean())


def add(df, trade_days, gaps, portfolio_gap):
    out = df.copy()
    traded = out["sku"].astype(str).map(trade_days).to_numpy(dtype="float64")
    out["f_sku_trade_days"] = np.where(np.isnan(traded), 0.0, traded)
    spacing = out["account_id"].map(gaps).to_numpy(dtype="float64")
    out["f_account_order_gap"] = np.where(np.isnan(spacing), portfolio_gap, spacing)
    return out
RISKSCORE_EOF

cat > src/riskscore/calendar_feats.py <<'RISKSCORE_EOF'
"""Seasonality and time-of-order features."""
import numpy as np
import pandas as pd


def add(df):
    out = df.copy()
    stamps = out["placed_at"]
    parts = {
        "f_hour": stamps.dt.hour,
        "f_dow": stamps.dt.dayofweek,
        "f_month": stamps.dt.month,
        "f_week": stamps.dt.isocalendar()["week"],
    }
    for name, series in parts.items():
        out[name] = np.asarray(series, dtype="int64")
    out["f_is_weekend"] = (np.asarray(parts["f_dow"], dtype="int64") > 4).astype("int64")
    span = stamps - stamps.min()
    out["f_days_since_epoch"] = np.asarray(span.dt.days, dtype="int64")
    return out
RISKSCORE_EOF

cat > src/riskscore/concentration.py <<'RISKSCORE_EOF'
"""How wide a price band a sku has traded in over the fit window."""
import numpy as np
import pandas as pd

CATCH_ALL = "__unlisted__"


def price_range(fit_df):
    grouped = fit_df.groupby("sku")["unit_price"]
    band = grouped.apply(lambda prices: prices.max() - prices.min()).astype("float64")
    band.loc[CATCH_ALL] = float(band.mean())
    return band


def add(df, spread):
    out = df.copy()
    values = out["sku"].astype(str).map(spread).to_numpy(dtype="float64")
    out["f_sku_price_range"] = np.where(np.isnan(values), spread.loc[CATCH_ALL], values)
    return out
RISKSCORE_EOF

cat > src/riskscore/dispersion.py <<'RISKSCORE_EOF'
"""How much a sku's price has moved around its own usual level."""
import numpy as np
import pandas as pd

CATCH_ALL = "__unlisted__"


def price_dispersion(fit_df):
    codes, index = pd.factorize(fit_df["sku"].to_numpy())
    price = fit_df["unit_price"].to_numpy(dtype="float64")
    counts = np.bincount(codes, minlength=len(index)).astype("float64")
    totals = np.bincount(codes, weights=price, minlength=len(index))
    centres = totals / counts
    gaps = np.abs(price - centres[codes])
    spread = np.bincount(codes, weights=gaps, minlength=len(index)) / counts
    table = pd.Series(spread, index=pd.Index(index, name="sku"), dtype="float64")
    table = table.sort_index()
    table.loc[CATCH_ALL] = float(table.mean())
    return table


def add(df, dispersion):
    out = df.copy()
    values = out["sku"].astype(str).map(dispersion).to_numpy(dtype="float64")
    out["f_sku_price_dispersion"] = np.where(
        np.isnan(values), dispersion.loc[CATCH_ALL], values)
    return out
RISKSCORE_EOF

cat > src/riskscore/encoders.py <<'RISKSCORE_EOF'
"""Categorical rate encoding, fitted on the fit window."""
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
        codes, index = pd.factorize(df[self.column].to_numpy())
        y = df[label].to_numpy(dtype="float64")
        counts = np.bincount(codes, minlength=len(index)).astype("float64")
        hits = np.bincount(codes, weights=y, minlength=len(index))
        share = counts / (counts + self.smoothing)
        blended = share * (hits / counts) + (1.0 - share) * self.prior_
        table = pd.Series(blended, index=pd.Index(index), dtype="float64").sort_index()
        table.loc[CATCH_ALL] = self.prior_
        self.rates_ = table
        return self

    def transform(self, df):
        values = df[self.column].astype(str).map(self.rates_).to_numpy(dtype="float64")
        return np.where(np.isnan(values), self.prior_, values)


def fit_all(fit_df, columns, smoothing, label):
    built = {}
    for column in columns:
        built[column] = RateEncoder(column, smoothing).fit(fit_df, label)
    return built


def apply_all(df, encoders):
    out = df.copy()
    for column in encoders:
        out["f_rate_" + column] = encoders[column].transform(out)
    return out
RISKSCORE_EOF

cat > src/riskscore/labels.py <<'RISKSCORE_EOF'
"""Derives the return label from the order and credit exports."""
import numpy as np
import pandas as pd


def attach_label(orders, returns, window_days):
    earliest = {}
    for account, sku, raised in zip(returns["account_id"].astype(str),
                                    returns["sku"].astype(str),
                                    returns["raised_at"]):
        key = account + "|" + sku
        if key not in earliest or raised < earliest[key]:
            earliest[key] = raised

    keys = orders["account_id"].astype(str) + "|" + orders["sku"].astype(str)
    matched = pd.to_datetime(pd.Series([earliest.get(k) for k in keys], index=orders.index))
    gap = (matched - orders["placed_at"]).dt.days.to_numpy(dtype="float64")
    hit = (gap >= 0) & (gap <= float(window_days))
    out = orders.copy()
    out["label"] = np.where(np.isnan(gap), 0, hit).astype("int64")
    return out
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

    def _clean(self, X):
        block = np.asarray(X, dtype="float64").copy()
        block[~np.isfinite(block)] = 0.0
        return block

    def fit(self, X, y):
        block = self._clean(X)
        self.scaler_ = StandardScaler()
        scaled = self.scaler_.fit_transform(block)
        self.clf_ = LogisticRegression(C=self.regularisation, max_iter=self.max_iter,
                                       random_state=self.seed, solver="lbfgs")
        self.clf_.fit(scaled, y)
        return self

    def score(self, X):
        scaled = self.scaler_.transform(self._clean(X))
        return self.clf_.predict_proba(scaled)[:, 1]
RISKSCORE_EOF

cat > src/riskscore/peak.py <<'RISKSCORE_EOF'
"""The calendar month in which an account spends most, measured on the fit window."""
import numpy as np
import pandas as pd

MONTHS = list(range(1, 13))


def peak_month(fit_df):
    spend = fit_df["units"].to_numpy(dtype="float64") * fit_df["unit_price"].to_numpy(dtype="float64")
    frame = fit_df[["account_id", "f_month"]].assign(_spend=spend)
    grid = frame.pivot_table(index="account_id", columns="f_month", values="_spend",
                             aggfunc="sum").reindex(columns=MONTHS)
    values = grid.to_numpy(dtype="float64")
    filled = np.where(np.isnan(values), -np.inf, values)
    picks = np.argmax(filled, axis=1)
    months = np.asarray(MONTHS, dtype="float64")[picks]
    return pd.Series(months, index=grid.index, dtype="float64")


def add(df, peaks, default):
    out = df.copy()
    chosen = out["account_id"].map(peaks).to_numpy(dtype="float64")
    chosen = np.where(np.isnan(chosen), float(default), chosen)
    out["f_peak_month"] = chosen
    out["f_in_peak_month"] = (chosen == out["f_month"].to_numpy(dtype="float64")).astype("int64")
    return out
RISKSCORE_EOF

cat > src/riskscore/price_position.py <<'RISKSCORE_EOF'
"""Where a line's price sits against the product's and the market's own history."""
import numpy as np
import pandas as pd


def market_mean_price(fit_df):
    totals = fit_df.groupby("market")["unit_price"].agg(["sum", "count"])
    table = (totals["sum"] / totals["count"]).astype("float64")
    return table, float(table.mean())


def add(df, mean_price, portfolio):
    out = df.copy()
    price = out["unit_price"].to_numpy(dtype="float64")

    sku_mean = out["f_sku_mean_price"].to_numpy(dtype="float64")
    ratio = np.zeros_like(price)
    live = sku_mean != 0.0
    ratio[live] = price[live] / sku_mean[live]
    out["f_price_vs_sku_mean"] = ratio

    market = out["market"].astype(str).map(mean_price).to_numpy(dtype="float64")
    market = np.where(np.isnan(market), portfolio, market)
    against = np.zeros_like(price)
    live = market != 0.0
    against[live] = price[live] / market[live]
    out["f_price_vs_market_mean"] = against
    return out
RISKSCORE_EOF

cat > src/riskscore/recency.py <<'RISKSCORE_EOF'
"""How long since the product and the account were last active."""
import numpy as np
import pandas as pd


def sku_last_trade(fit_df):
    return fit_df.groupby("sku")["placed_at"].max()


def account_last_order(fit_df):
    known = fit_df[~fit_df["account_id"].isna()]
    return known.groupby("account_id")["placed_at"].max()


def staleness(last_seen, fit_end):
    return pd.Series((fit_end - last_seen).dt.days.to_numpy(dtype="float64"),
                     index=last_seen.index)


def add(df, sku_stale, account_stale, portfolio_stale):
    out = df.copy()
    stale = out["sku"].astype(str).map(sku_stale).to_numpy(dtype="float64")
    out["f_sku_days_since_trade"] = np.where(np.isnan(stale), portfolio_stale, stale)
    idle = out["account_id"].map(account_stale).to_numpy(dtype="float64")
    out["f_account_days_since_order"] = np.where(np.isnan(idle), -1.0, idle)
    return out
RISKSCORE_EOF

cat > src/riskscore/return_history.py <<'RISKSCORE_EOF'
"""How often the account and the product have been returned before."""
import numpy as np
import pandas as pd


def counts(fit_df, label):
    flagged = fit_df[fit_df[label] == 1]
    return (flagged.groupby("account_id")[label].sum().astype("float64"),
            flagged.groupby("sku")[label].sum().astype("float64"))


def account_rate(fit_df, label, smoothing):
    prior = float(fit_df[label].mean())
    known = fit_df[~fit_df["account_id"].isna()]
    codes, index = pd.factorize(known["account_id"].to_numpy())
    y = known[label].to_numpy(dtype="float64")
    n = np.bincount(codes, minlength=len(index)).astype("float64")
    hits = np.bincount(codes, weights=y, minlength=len(index))
    share = n / (n + float(smoothing))
    rates = share * (hits / n) + (1.0 - share) * prior
    return pd.Series(rates, index=pd.Index(index), dtype="float64").sort_index(), prior


def add(df, acct_counts, sku_counts, rates, prior):
    out = df.copy()
    for source, feature, blank in ((acct_counts, "f_acct_prior_returns", 0.0),
                                   (rates, "f_acct_return_rate", prior)):
        values = out["account_id"].map(source).to_numpy(dtype="float64")
        out[feature] = np.where(np.isnan(values), blank, values)
    sku_values = out["sku"].astype(str).map(sku_counts).to_numpy(dtype="float64")
    out["f_sku_prior_returns"] = np.where(np.isnan(sku_values), 0.0, sku_values)
    return out
RISKSCORE_EOF

cat > src/riskscore/seasonal.py <<'RISKSCORE_EOF'
"""Seasonal factor by calendar month, measured on the fit window."""
import numpy as np
import pandas as pd

MONTHS = list(range(1, 13))


def factor_table(fit_df, label):
    totals = fit_df.groupby("f_month")[label].agg(["sum", "count"])
    rates = (totals["sum"] / totals["count"]).reindex(MONTHS)
    return rates.astype("float64")


def add(df, factors):
    out = df.copy()
    values = out["f_month"].map(factors).to_numpy(dtype="float64")
    fallback = float(np.nanmean(factors.to_numpy(dtype="float64")))
    out["f_seasonal"] = np.where(np.isnan(values), fallback, values)
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
        self.lookup_ = None

    def _inputs(self, df):
        block = np.column_stack([df[name].to_numpy(dtype="float64")
                                 for name in SEGMENT_INPUTS])
        block[~np.isfinite(block)] = 0.0
        return block

    def fit(self, df):
        block = self._inputs(df)
        self.scaler_ = StandardScaler().fit(block)
        self.model_ = KMeans(n_clusters=self.n_segments, random_state=self.seed,
                             n_init=RESTARTS).fit(self.scaler_.transform(block))
        centres = self.model_.cluster_centers_[:, 0]
        ordering = sorted(range(self.n_segments), key=lambda i: centres[i])
        self.lookup_ = {cluster: rank for rank, cluster in enumerate(ordering)}
        return self

    def transform(self, df):
        assigned = self.model_.predict(self.scaler_.transform(self._inputs(df)))
        return np.array([self.lookup_[c] for c in assigned], dtype="int64")


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
    out = df.copy()
    listed = pd.Series(catalogue["first_listed"].to_numpy(),
                       index=catalogue["sku"].astype(str).to_numpy())
    matched = pd.to_datetime(pd.Series(out["sku"].astype(str).map(listed).to_numpy(),
                                       index=out.index))
    age = (out["placed_at"] - matched).dt.days.to_numpy(dtype="float64")
    age = np.where(np.isnan(age), -1.0, age)
    out["f_sku_age_days"] = age
    out["f_sku_is_new"] = (age < 0).astype("int64")
    return out


def history(fit_df):
    frame = fit_df[["sku", "units", "unit_price"]]
    return pd.DataFrame({
        "sku_orders": frame.groupby("sku")["units"].count(),
        "sku_units": frame.groupby("sku")["units"].sum(),
        "sku_mean_price": frame.groupby("sku")["unit_price"].mean(),
    }).astype("float64")


def attach_history(df, hist):
    out = df.copy()
    keys = out["sku"].astype(str)
    default_price = float(hist["sku_mean_price"].mean())
    for column, feature, blank in (("sku_orders", "f_sku_orders", 0.0),
                                   ("sku_units", "f_sku_units", 0.0),
                                   ("sku_mean_price", "f_sku_mean_price", default_price)):
        values = keys.map(hist[column]).to_numpy(dtype="float64")
        out[feature] = np.where(np.isnan(values), blank, values)
    return out
RISKSCORE_EOF

cat > src/riskscore/velocity.py <<'RISKSCORE_EOF'
"""How fast a sku has been selling, once short-run noise is smoothed out."""
import numpy as np
import pandas as pd

WINDOW_DAYS = 10
CATCH_ALL = "__unlisted__"


def sku_velocity(fit_df):
    frame = fit_df[["sku", "placed_at", "units"]].copy()
    frame["day"] = frame["placed_at"].dt.floor("D")
    per_day = frame.groupby(["sku", "day"])["units"].sum()

    speeds = {}
    for sku, block in per_day.groupby(level="sku"):
        series = block.droplevel("sku")
        full = series.reindex(pd.date_range(series.index.min(), series.index.max(), freq="D"),
                              fill_value=0.0)
        window = full.rolling(WINDOW_DAYS, min_periods=WINDOW_DAYS).mean()
        speeds[sku] = window.mean()

    table = pd.Series(speeds, dtype="float64").sort_index()
    table.index.name = "sku"
    fallback = float(table.mean())
    table = table.fillna(fallback)
    table.loc[CATCH_ALL] = fallback
    return table


def add(df, velocity):
    out = df.copy()
    values = out["sku"].astype(str).map(velocity).to_numpy(dtype="float64")
    out["f_sku_velocity"] = np.where(np.isnan(values), velocity.loc[CATCH_ALL], values)
    return out
RISKSCORE_EOF

python3 run_scoring.py --config configs/reference.yaml --out out/reference
python3 run_scoring.py --config configs/current.yaml   --out out/current
echo "rebuild complete"
