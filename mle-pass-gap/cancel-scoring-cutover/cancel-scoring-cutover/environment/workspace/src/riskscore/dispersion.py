"""How much a sku's price has moved around its own usual level.

Lines priced unusually for their own sku are the ones that get sent back.
"""
import numpy as np
import pandas as pd


def price_dispersion(fit_df):
    raise NotImplementedError


def add(df, dispersion):
    raise NotImplementedError
