"""How consistent a member or a film has been, as of the rating being scored."""
import numpy as np
import pandas as pd


def _running_square(fit_df, key):
    raise NotImplementedError


def prior_spread(df, fit_df, key):
    raise NotImplementedError


def add(df, fit_df, prior_member_spread, prior_film_spread):
    raise NotImplementedError
