"""Coarse behavioural segmentation used as a model input."""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler


class Segmenter(object):

    def __init__(self, n_segments, seed):
        raise NotImplementedError

    def _inputs(self, df):
        raise NotImplementedError

    def fit(self, df):
        raise NotImplementedError

    def _order(self):
        raise NotImplementedError

    def transform(self, df):
        raise NotImplementedError


def add(df, segmenter):
    raise NotImplementedError
