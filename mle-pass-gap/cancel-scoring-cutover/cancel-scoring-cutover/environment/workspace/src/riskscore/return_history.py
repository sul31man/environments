"""How often the account and the product have been returned before."""
import numpy as np
import pandas as pd


def counts(fit_df, label):
    raise NotImplementedError


def account_rate(fit_df, label, smoothing):
    raise NotImplementedError


def add(df, acct_counts, sku_counts, rates, prior):
    raise NotImplementedError
