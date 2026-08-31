"""Estimator."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


class RiskModel(object):

    def __init__(self, seed, max_iter, regularisation):
        raise NotImplementedError

    def fit(self, X, y):
        raise NotImplementedError

    def score(self, X):
        raise NotImplementedError
