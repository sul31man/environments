"""Estimator."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


class EngagementModel(object):
    def __init__(self, seed, max_iter, regularisation):
        self.seed = int(seed)
        self.max_iter = int(max_iter)
        self.regularisation = float(regularisation)
        self.scaler_ = None
        self.clf_ = None

    def fit(self, X, y):
        self.scaler_ = StandardScaler().fit(X)
        self.clf_ = LogisticRegression(
            C=self.regularisation, max_iter=self.max_iter, random_state=self.seed,
            solver="lbfgs").fit(self.scaler_.transform(X), y)
        return self

    def score(self, X):
        return self.clf_.predict_proba(self.scaler_.transform(X))[:, 1]
