"""Cheap structural checks on the export before any of it is trusted."""
import numpy as np

REQUIRED = ["line_id", "order_id", "sku", "units", "unit_price", "placed_at", "market"]


class ExportError(Exception):
    pass


def check_orders(df):
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ExportError("order export is missing columns: %s" % ", ".join(missing))
    if not np.all(df["units"].values > 0):
        raise ExportError("order export contains non positive line quantities")
    if df["line_id"].duplicated().any():
        raise ExportError("order export repeats line_id")
    return True
