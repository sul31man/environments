"""Run configuration."""
from pathlib import Path

import yaml


class Config(dict):
    @property
    def windows(self):
        return self["windows"]


def load(path):
    with open(path) as fh:
        cfg = Config(yaml.safe_load(fh))
    cfg["_root"] = Path(path).resolve().parents[1]
    return cfg


def data_dir(cfg):
    return Path(cfg["_root"]) / cfg["paths"]["data_dir"]
