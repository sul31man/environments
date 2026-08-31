"""Categorical rate encoding, fitted on the fit window.
"""
import numpy as np
import pandas as pd


class RateEncoder(object):

    def __init__(self, column, smoothing):
        raise NotImplementedError

    def fit(self, df, label):
        raise NotImplementedError

    def transform(self, df):
        raise NotImplementedError


def fit_all(fit_df, columns, smoothing, label):
    raise NotImplementedError


def apply_all(df, encoders):
    raise NotImplementedError
