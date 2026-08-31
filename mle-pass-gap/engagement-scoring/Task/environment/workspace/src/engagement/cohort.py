"""How the member's cohort behaves, measured over the fit window."""
import numpy as np
import pandas as pd


def rates(fit_df, column, smoothing, prior_rate):
    raise NotImplementedError


def add(df, occupation_rates, age_rates, region_rates, prior_rate):
    raise NotImplementedError
