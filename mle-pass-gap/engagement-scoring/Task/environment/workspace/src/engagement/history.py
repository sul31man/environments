"""What was known about a member or a film at the moment a rating was made.

Every quantity here is built from ratings strictly earlier than the row it describes,
and never from ratings later than the end of the fit window.
"""
import numpy as np
import pandas as pd


def _running(fit_df, key):
    """Per fit rating, the running totals for that key INCLUDING that rating."""
    raise NotImplementedError


def state_before(df, fit_df, key):
    """For each row of df, the running totals for its key strictly before its own time."""
    raise NotImplementedError
