#!/usr/bin/env bash
# The recent-form window is the wrong length.
set -euo pipefail

cd /workspace/target

cat > src/engagement/cohort.py <<'ENGAGEMENT_EOF'
"""How the member's cohort behaves, measured over the fit window."""
import numpy as np
import pandas as pd


def rates(fit_df, column, smoothing, prior_rate):
    grouped = fit_df.groupby(column)["liked"]
    n = grouped.size().astype("float64")
    mean = grouped.mean().astype("float64")
    weight = n / (n + float(smoothing))
    return (weight * mean + (1.0 - weight) * prior_rate).astype("float64")


def add(df, occupation_rates, age_rates, region_rates, prior_rate):
    out = df.copy()
    for column, table, name in (("f_occupation", occupation_rates, "f_occupation_rate"),
                                ("f_age_band", age_rates, "f_age_band_rate"),
                                ("f_region", region_rates, "f_region_rate")):
        looked = out[column].map(table)
        out[name] = looked.fillna(prior_rate).astype("float64")
    return out
ENGAGEMENT_EOF

cat > src/engagement/history.py <<'ENGAGEMENT_EOF'
"""What was known about a member or a film at the moment a rating was made.

Every quantity here is built from ratings strictly earlier than the row it describes,
and never from ratings later than the end of the fit window.
"""
import numpy as np
import pandas as pd


def _running(fit_df, key):
    """Per fit rating, the running totals for that key INCLUDING that rating."""
    grouped = fit_df.groupby(key, sort=False)
    frame = pd.DataFrame({
        key: fit_df[key].to_numpy(),
        "rated_at": fit_df["rated_at"].to_numpy(),
        "run_n": (grouped.cumcount() + 1).to_numpy().astype("float64"),
        "run_likes": grouped["liked"].cumsum().to_numpy().astype("float64"),
        "run_stars": grouped["stars"].cumsum().to_numpy().astype("float64"),
        "run_first": grouped["rated_at"].transform("min").to_numpy(),
    })
    return frame.sort_values(["rated_at", key], kind="stable").reset_index(drop=True)


def state_before(df, fit_df, key):
    """For each row of df, the running totals for its key strictly before its own time."""
    running = _running(fit_df, key)
    probe = (df[[key, "rated_at"]]
             .assign(_pos=np.arange(len(df)))
             .sort_values(["rated_at", key], kind="stable"))
    merged = pd.merge_asof(probe, running, on="rated_at", by=key,
                           allow_exact_matches=False, direction="backward")
    merged = merged.sort_values("_pos", kind="stable")
    out = pd.DataFrame(index=df.index)
    out["prior_n"] = merged["run_n"].fillna(0.0).to_numpy()
    out["prior_likes"] = merged["run_likes"].fillna(0.0).to_numpy()
    out["prior_stars"] = merged["run_stars"].fillna(0.0).to_numpy()
    out["prior_first"] = merged["run_first"].to_numpy()
    return out
ENGAGEMENT_EOF

cat > src/engagement/member_history.py <<'ENGAGEMENT_EOF'
"""The member's own record, as of the rating being scored."""
import numpy as np
import pandas as pd

from . import history


def add(df, fit_df, smoothing, prior_rate, prior_stars, prior_tenure, prior_pace):
    state = history.state_before(df, fit_df, "member_id")
    out = df.copy()
    seen = state["prior_n"].to_numpy()
    likes = state["prior_likes"].to_numpy()
    stars = state["prior_stars"].to_numpy()

    out["f_mbr_prior_ratings"] = seen
    out["f_mbr_prior_likes"] = likes

    weight = seen / (seen + float(smoothing))
    raw_rate = np.divide(likes, seen, out=np.zeros_like(likes), where=seen > 0)
    out["f_mbr_like_rate"] = weight * raw_rate + (1.0 - weight) * prior_rate

    mean_stars = np.divide(stars, seen, out=np.full_like(stars, np.nan), where=seen > 0)
    out["f_mbr_mean_stars"] = np.where(np.isnan(mean_stars), prior_stars, mean_stars)

    tenure = (out["rated_at"] - state["prior_first"]).dt.days.to_numpy(dtype="float64")
    out["f_mbr_tenure_days"] = np.where(np.isnan(tenure), prior_tenure, tenure)

    pace = np.divide(seen, np.maximum(tenure, 1.0),
                     out=np.full_like(seen, np.nan), where=seen > 0)
    out["f_mbr_ratings_per_day"] = np.where(np.isnan(pace), prior_pace, pace)

    out["f_mbr_is_new"] = (seen == 0).astype("int64")
    return out
ENGAGEMENT_EOF

cat > src/engagement/recent.py <<'ENGAGEMENT_EOF'
"""How the member has been behaving lately, rather than over all time."""
import numpy as np
import pandas as pd

RECENT_RATINGS = 10


def add(df, fit_df, prior_rate, prior_gap):
    ordered = fit_df.sort_values(["member_id", "rated_at"], kind="stable")
    grouped = ordered.groupby("member_id", sort=False)
    rolling = (grouped["liked"]
               .transform(lambda s: s.shift(1).rolling(RECENT_RATINGS, min_periods=1).mean()))
    previous = grouped["rated_at"].shift(1)
    state = pd.DataFrame({
        "member_id": ordered["member_id"].to_numpy(),
        "rated_at": ordered["rated_at"].to_numpy(),
        "run_recent": rolling.to_numpy(),
        "run_prev": previous.to_numpy(),
    }).sort_values(["rated_at", "member_id"], kind="stable").reset_index(drop=True)

    probe = (df[["member_id", "rated_at"]].assign(_pos=np.arange(len(df)))
             .sort_values(["rated_at", "member_id"], kind="stable"))
    merged = pd.merge_asof(probe, state, on="rated_at", by="member_id",
                           allow_exact_matches=False, direction="backward")
    merged = merged.sort_values("_pos", kind="stable")

    out = df.copy()
    recent = merged["run_recent"].to_numpy(dtype="float64")
    out["f_mbr_recent_rate"] = np.where(np.isnan(recent), prior_rate, recent)
    gap = (out["rated_at"].to_numpy() - merged["run_prev"].to_numpy())
    gap_days = gap.astype("timedelta64[s]").astype("float64") / 86400.0
    out["f_mbr_days_since_prev"] = np.where(np.isnan(gap_days), prior_gap, gap_days)
    return out
ENGAGEMENT_EOF

cat > src/engagement/spread.py <<'ENGAGEMENT_EOF'
"""How consistent a member or a film has been, as of the rating being scored."""
import numpy as np
import pandas as pd


def _running_square(fit_df, key):
    grouped = fit_df.groupby(key, sort=False)
    frame = pd.DataFrame({
        key: fit_df[key].to_numpy(),
        "rated_at": fit_df["rated_at"].to_numpy(),
        "run_n": (grouped.cumcount() + 1).to_numpy().astype("float64"),
        "run_stars": grouped["stars"].cumsum().to_numpy().astype("float64"),
        "run_sq": fit_df.assign(_sq=fit_df["stars"].astype("float64") ** 2)
                  .groupby(key, sort=False)["_sq"].cumsum().to_numpy().astype("float64"),
    })
    return frame.sort_values(["rated_at", key], kind="stable").reset_index(drop=True)


def prior_spread(df, fit_df, key):
    running = _running_square(fit_df, key)
    probe = (df[[key, "rated_at"]].assign(_pos=np.arange(len(df)))
             .sort_values(["rated_at", key], kind="stable"))
    merged = pd.merge_asof(probe, running, on="rated_at", by=key,
                           allow_exact_matches=False, direction="backward")
    merged = merged.sort_values("_pos", kind="stable")
    n = merged["run_n"].fillna(0.0).to_numpy()
    total = merged["run_stars"].fillna(0.0).to_numpy()
    square = merged["run_sq"].fillna(0.0).to_numpy()
    mean = np.divide(total, n, out=np.zeros_like(total), where=n > 0)
    var = np.divide(square, n, out=np.zeros_like(square), where=n > 0) - mean ** 2
    return np.where(n > 1, np.sqrt(np.maximum(var, 0.0)), np.nan)


def add(df, fit_df, prior_member_spread, prior_film_spread):
    out = df.copy()
    member = prior_spread(df, fit_df, "member_id")
    film = prior_spread(df, fit_df, "film_id")
    out["f_mbr_stars_spread"] = np.where(np.isnan(member), prior_member_spread, member)
    out["f_film_stars_spread"] = np.where(np.isnan(film), prior_film_spread, film)
    return out
ENGAGEMENT_EOF

python3 run_scoring.py --config configs/reference.yaml --out out/reference
python3 run_scoring.py --config configs/current.yaml   --out out/current
