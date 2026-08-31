"""Design matrix assembly."""
import numpy as np

FEATURES = [
    "f_hour", "f_dow", "f_month", "f_week", "f_is_weekend", "f_days_since_epoch",
    "f_basket_lines", "f_basket_units", "f_basket_value", "f_line_share",
    "f_sku_age_days", "f_sku_is_new", "f_sku_orders", "f_sku_units",
    "f_sku_mean_price", "f_account_tenure_days", "f_account_known",
    "f_acct_orders", "f_acct_units", "f_rate_sku", "f_rate_market",
    "f_sku_price_dispersion", "f_seasonal", "f_sku_velocity",
    "f_sku_price_range", "f_peak_month", "f_in_peak_month",
    "f_basket_distinct_skus", "f_basket_max_line_share",
    "f_basket_mean_line_value", "f_price_vs_sku_mean",
    "f_price_vs_market_mean", "f_sku_days_since_trade",
    "f_account_days_since_order", "f_acct_prior_returns",
    "f_sku_prior_returns", "f_acct_return_rate", "f_sku_trade_days",
    "f_account_order_gap", "f_segment",
]


def matrix(df):
    missing = [c for c in FEATURES if c not in df.columns]
    if missing:
        raise KeyError("design matrix is missing columns: %s" % ", ".join(missing))
    values = df[FEATURES].astype("float64").values
    return np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
