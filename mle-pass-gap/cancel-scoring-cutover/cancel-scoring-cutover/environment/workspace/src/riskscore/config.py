"""Run configuration."""
from pathlib import Path

import yaml


class Config(dict):
    @property
    def paths(self):
        return self["paths"]

    @property
    def windows(self):
        return self["windows"]


def load(path):
    with open(path) as fh:
        cfg = Config(yaml.safe_load(fh))
    root = Path(path).resolve().parents[1]
    cfg["_root"] = root
    return cfg


def data_dir(cfg):
    return Path(cfg["_root"]) / cfg["paths"]["data_dir"]
