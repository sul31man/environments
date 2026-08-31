"""Reads the nightly export."""
import pandas as pd

from . import config


def read_orders(cfg):
    path = config.data_dir(cfg) / "orders.csv.gz"
    df = pd.read_csv(path, parse_dates=["placed_at"], dtype={"order_id": str, "line_id": str},
                     on_bad_lines="warn")
    df["sku"] = df["sku"].astype(str)
    return df


def read_returns(cfg):
    path = config.data_dir(cfg) / "returns.csv.gz"
    df = pd.read_csv(path, parse_dates=["raised_at"], dtype={"credit_id": str},
                     on_bad_lines="warn")
    df["sku"] = df["sku"].astype(str)
    return df


def read_catalogue(cfg):
    path = config.data_dir(cfg) / "catalogue.csv"
    df = pd.read_csv(path, parse_dates=["first_listed"])
    df["sku"] = df["sku"].astype(str)
    return df


def read_accounts(cfg):
    path = config.data_dir(cfg) / "accounts.csv"
    return pd.read_csv(path, parse_dates=["first_order_at"])
