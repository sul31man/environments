"""The member's own record, as of the rating being scored."""
import numpy as np
import pandas as pd

from . import history


def add(df, fit_df, smoothing, prior_rate, prior_stars, prior_tenure, prior_pace):
    raise NotImplementedError
