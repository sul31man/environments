"""Month on month movement in the published score.

Only meaningful when the scored window covers more than one calendar month; a single
month run has nothing to compare against and reports nothing.
"""
import numpy as np
import pandas as pd


def monthly_mean(scores):
    months = pd.to_datetime(scores["placed_at"]).dt.to_period("M").astype(str)
    return scores.groupby(months)["risk_score"].mean().astype("float64")


def month_on_month(scores):
    means = monthly_mean(scores)
    if len(means) < 2:
        return {}
    steps = means.diff().dropna()
    return {period: round(float(change), 6) for period, change in steps.items()}
