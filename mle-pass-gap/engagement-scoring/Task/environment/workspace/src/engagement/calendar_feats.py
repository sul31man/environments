"""When the rating was made."""
import numpy as np
import pandas as pd


def add(df):
    out = df.copy()
    ts = out["rated_at"]
    out["f_hour"] = ts.dt.hour.astype("int64")
    out["f_dow"] = ts.dt.dayofweek.astype("int64")
    out["f_month"] = ts.dt.month.astype("int64")
    out["f_is_weekend"] = (out["f_dow"] >= 5).astype("int64")
    out["f_days_into_period"] = (ts - ts.min()).dt.days.astype("int64")
    return out
