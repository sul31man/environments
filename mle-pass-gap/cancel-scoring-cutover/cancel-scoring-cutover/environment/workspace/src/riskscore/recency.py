"""How long since the product and the account were last active."""
import numpy as np
import pandas as pd


def sku_last_trade(fit_df):
    raise NotImplementedError


def account_last_order(fit_df):
    raise NotImplementedError


def staleness(last_seen, fit_end):
    raise NotImplementedError


def add(df, sku_stale, account_stale, portfolio_stale):
    raise NotImplementedError
