"""Reads the nightly export."""
import pandas as pd

from . import config


def read_ratings(cfg):
    path = config.data_dir(cfg) / "ratings.csv.gz"
    df = pd.read_csv(path, parse_dates=["rated_at"], dtype={"rating_id": str})
    return df.sort_values("rating_id").reset_index(drop=True)


def read_members(cfg):
    return pd.read_csv(config.data_dir(cfg) / "members.csv")


def read_films(cfg):
    return pd.read_csv(config.data_dir(cfg) / "films.csv")
