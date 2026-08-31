#!/usr/bin/env bash
# SECOND alternate-correct solution: a third independent implementation.
#
# Written against numpy where it can be: cumulative sums over factorised keys and
# explicit index arithmetic instead of pandas grouping, dictionaries for the cohort
# tables, and boolean masks instead of where-clauses.
set -euo pipefail

cd /workspace/target

cat > src/engagement/cohort.py <<'ENGAGEMENT_EOF'
"""How the member's cohort behaves, measured over the fit window."""
import numpy as np
import pandas as pd


def rates(fit_df, column, smoothing, prior_rate):
    codes, index = pd.factorize(fit_df[column].to_numpy())
    liked = fit_df["liked"].to_numpy(dtype="float64")
    n = np.bincount(codes, minlength=len(index)).astype("float64")
    hits = np.bincount(codes, weights=liked, minlength=len(index))
    share = n / (n + float(smoothing))
    blended = share * (hits / n) + (1.0 - share) * prior_rate
    return pd.Series(blended, index=pd.Index(index), dtype="float64").sort_index()


def add(df, occupation_rates, age_rates, region_rates, prior_rate):
    out = df.copy()
    pairs = (("f_occupation", occupation_rates, "f_occupation_rate"),
             ("f_age_band", age_rates, "f_age_band_rate"),
             ("f_region", region_rates, "f_region_rate"))
    for column, table, name in pairs:
        values = out[column].map(table).to_numpy(dtype="float64")
        out[name] = np.where(np.isnan(values), prior_rate, values)
    return out
ENGAGEMENT_EOF

cat > src/engagement/history.py <<'ENGAGEMENT_EOF'
"""What was known about a member or a film at the moment a rating was made.

Every quantity here is built from ratings strictly earlier than the row it describes,
and never from ratings later than the end of the fit window.

Source rows and the rows being described are interleaved on one timeline per key, with
the described row placed ahead of anything sharing its timestamp, so a running total
read at that point covers only what came strictly before it.
"""
import numpy as np
import pandas as pd

QUERY, SOURCE = 0, 1


def state_before(df, fit_df, key):
    source = pd.DataFrame({
        "k": fit_df[key].to_numpy(),
        "t": fit_df["rated_at"].to_numpy(),
        "side": SOURCE,
        "pos": -1,
        "liked": fit_df["liked"].to_numpy(dtype="float64"),
        "stars": fit_df["stars"].to_numpy(dtype="float64"),
    })
    query = pd.DataFrame({
        "k": df[key].to_numpy(),
        "t": df["rated_at"].to_numpy(),
        "side": QUERY,
        "pos": np.arange(len(df)),
        "liked": 0.0,
        "stars": 0.0,
    })
    timeline = (pd.concat([source, query], ignore_index=True)
                .sort_values(["k", "t", "side"], kind="stable"))

    grouped = timeline.groupby("k", sort=False)
    counted = grouped["side"].cumsum().to_numpy(dtype="float64")
    liked = grouped["liked"].cumsum().to_numpy()
    stars = grouped["stars"].cumsum().to_numpy()
    earliest = grouped["t"].transform("min").to_numpy()

    taken = timeline["side"].to_numpy() == QUERY
    slots = timeline["pos"].to_numpy()[taken]

    n = np.zeros(len(df)); likes = np.zeros(len(df)); total = np.zeros(len(df))
    first = np.full(len(df), np.datetime64("NaT"), dtype="datetime64[ns]")
    n[slots] = counted[taken]
    likes[slots] = liked[taken]
    total[slots] = stars[taken]
    first[slots] = np.where(counted[taken] > 0, earliest[taken], np.datetime64("NaT"))

    return pd.DataFrame({"prior_n": n, "prior_likes": likes, "prior_stars": total,
                         "prior_first": first}, index=df.index)
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
    blank = seen == 0
    safe = np.maximum(seen, 1.0)

    out["f_mbr_prior_ratings"] = seen
    out["f_mbr_prior_likes"] = likes

    share = seen / (seen + float(smoothing))
    blended = share * (likes / safe) + (1.0 - share) * prior_rate
    out["f_mbr_like_rate"] = np.where(blank, prior_rate, blended)
    out["f_mbr_mean_stars"] = np.where(blank, prior_stars, stars / safe)

    elapsed = (out["rated_at"] - state["prior_first"]).dt.days.to_numpy(dtype="float64")
    missing = np.isnan(elapsed)
    out["f_mbr_tenure_days"] = np.where(missing, prior_tenure, elapsed)
    out["f_mbr_ratings_per_day"] = np.where(
        blank, prior_pace, seen / np.maximum(np.where(missing, 1.0, elapsed), 1.0))
    out["f_mbr_is_new"] = blank.astype("int64")
    return out
ENGAGEMENT_EOF

cat > src/engagement/recent.py <<'ENGAGEMENT_EOF'
"""How the member has been behaving lately, rather than over all time."""
import numpy as np
import pandas as pd

RECENT_RATINGS = 20


def _state(fit_df):
    ordered = fit_df.sort_values(["member_id", "rated_at"], kind="stable")
    grouped = ordered.groupby("member_id", sort=False)
    recent = grouped["liked"].transform(
        lambda s: s.shift(1).rolling(RECENT_RATINGS, min_periods=1).mean())
    frame = pd.DataFrame({
        "member_id": ordered["member_id"].to_numpy(),
        "rated_at": ordered["rated_at"].to_numpy(),
        "run_recent": recent.to_numpy(),
        "run_prev": grouped["rated_at"].shift(1).to_numpy(),
    })
    return frame.sort_values(["rated_at", "member_id"], kind="stable").reset_index(drop=True)


def add(df, fit_df, prior_rate, prior_gap):
    state = _state(fit_df)
    probe = df[["member_id", "rated_at"]].copy()
    probe["_pos"] = np.arange(len(df))
    probe = probe.sort_values(["rated_at", "member_id"], kind="stable")
    joined = pd.merge_asof(probe, state, on="rated_at", by="member_id",
                           allow_exact_matches=False, direction="backward")
    joined = joined.sort_values("_pos", kind="stable")

    out = df.copy()
    recent = joined["run_recent"].to_numpy(dtype="float64")
    out["f_mbr_recent_rate"] = np.where(np.isnan(recent), prior_rate, recent)
    previous = joined["run_prev"].to_numpy()
    delta = (out["rated_at"].to_numpy() - previous)
    days = delta.astype("timedelta64[s]").astype("float64") / 86400.0
    out["f_mbr_days_since_prev"] = np.where(np.isnan(days), prior_gap, days)
    return out
ENGAGEMENT_EOF

cat > src/engagement/spread.py <<'ENGAGEMENT_EOF'
"""How consistent a member or a film has been, as of the rating being scored."""
import numpy as np
import pandas as pd

QUERY, SOURCE = 0, 1


def prior_spread(df, fit_df, key):
    stars = fit_df["stars"].to_numpy(dtype="float64")
    source = pd.DataFrame({"k": fit_df[key].to_numpy(), "t": fit_df["rated_at"].to_numpy(),
                           "side": SOURCE, "pos": -1, "s": stars, "sq": stars ** 2})
    query = pd.DataFrame({"k": df[key].to_numpy(), "t": df["rated_at"].to_numpy(),
                          "side": QUERY, "pos": np.arange(len(df)), "s": 0.0, "sq": 0.0})
    timeline = (pd.concat([source, query], ignore_index=True)
                .sort_values(["k", "t", "side"], kind="stable"))

    grouped = timeline.groupby("k", sort=False)
    n = grouped["side"].cumsum().to_numpy(dtype="float64")
    total = grouped["s"].cumsum().to_numpy()
    square = grouped["sq"].cumsum().to_numpy()

    taken = timeline["side"].to_numpy() == QUERY
    slots = timeline["pos"].to_numpy()[taken]
    seen = n[taken]
    safe = np.maximum(seen, 1.0)
    mean = total[taken] / safe
    var = square[taken] / safe - mean ** 2

    out = np.full(len(df), np.nan)
    usable = seen > 1
    out[slots[usable]] = np.sqrt(np.maximum(var[usable], 0.0))
    return out


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
echo "rebuild complete"
