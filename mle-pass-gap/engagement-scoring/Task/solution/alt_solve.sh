#!/usr/bin/env bash
# ALTERNATE-correct solution: the same specification implemented differently.
#
# Prior state comes from sorted per-key arrays and searchsorted rather than
# merge_asof, rates are blended with explicit weights, and the frames are built
# by assignment rather than by copy-and-set.
set -euo pipefail

cd /workspace/target

cat > src/engagement/cohort.py <<'ENGAGEMENT_EOF'
"""How the member's cohort behaves, measured over the fit window."""
import numpy as np
import pandas as pd


def rates(fit_df, column, smoothing, prior_rate):
    tally = fit_df.groupby(column)["liked"].agg(["size", "mean"]).astype("float64")
    share = tally["size"] / (tally["size"] + float(smoothing))
    return (share * tally["mean"] + (1.0 - share) * prior_rate).astype("float64")


def add(df, occupation_rates, age_rates, region_rates, prior_rate):
    out = df
    for column, table, name in (("f_occupation", occupation_rates, "f_occupation_rate"),
                                ("f_age_band", age_rates, "f_age_band_rate"),
                                ("f_region", region_rates, "f_region_rate")):
        lookup = table.to_dict()
        values = np.array([lookup.get(key, prior_rate) for key in out[column].to_numpy()],
                          dtype="float64")
        out = out.assign(**{name: values})
    return out
ENGAGEMENT_EOF

cat > src/engagement/history.py <<'ENGAGEMENT_EOF'
"""What was known about a member or a film at the moment a rating was made.

Every quantity here is built from ratings strictly earlier than the row it describes,
and never from ratings later than the end of the fit window.
"""
import numpy as np
import pandas as pd


def _index(fit_df, key):
    """Per key, the sorted times and the cumulative totals that go with them."""
    table = {}
    ordered = fit_df.sort_values("rated_at", kind="stable")
    for name, block in ordered.groupby(key, sort=False):
        times = block["rated_at"].to_numpy()
        liked = np.concatenate([[0.0], block["liked"].to_numpy(dtype="float64").cumsum()])
        stars = np.concatenate([[0.0], block["stars"].to_numpy(dtype="float64").cumsum()])
        table[name] = (times, liked, stars)
    return table


def state_before(df, fit_df, key):
    """For each row of df, the running totals for its key strictly before its own time."""
    table = _index(fit_df, key)
    keys = df[key].to_numpy()
    stamps = df["rated_at"].to_numpy()
    n = np.zeros(len(df), dtype="float64")
    likes = np.zeros(len(df), dtype="float64")
    stars = np.zeros(len(df), dtype="float64")
    first = np.full(len(df), np.datetime64("NaT"), dtype="datetime64[ns]")

    for position, (name, stamp) in enumerate(zip(keys, stamps)):
        entry = table.get(name)
        if entry is None:
            continue
        times, cum_liked, cum_stars = entry
        taken = int(np.searchsorted(times, stamp, side="left"))
        if taken == 0:
            continue
        n[position] = taken
        likes[position] = cum_liked[taken]
        stars[position] = cum_stars[taken]
        first[position] = times[0]

    return pd.DataFrame({"prior_n": n, "prior_likes": likes, "prior_stars": stars,
                         "prior_first": first}, index=df.index)
ENGAGEMENT_EOF

cat > src/engagement/member_history.py <<'ENGAGEMENT_EOF'
"""The member's own record, as of the rating being scored."""
import numpy as np
import pandas as pd

from . import history


def add(df, fit_df, smoothing, prior_rate, prior_stars, prior_tenure, prior_pace):
    state = history.state_before(df, fit_df, "member_id")
    seen = state["prior_n"].to_numpy()
    likes = state["prior_likes"].to_numpy()
    stars = state["prior_stars"].to_numpy()
    has = seen > 0

    rate = np.full(len(df), prior_rate, dtype="float64")
    share = seen[has] / (seen[has] + float(smoothing))
    rate[has] = share * (likes[has] / seen[has]) + (1.0 - share) * prior_rate

    mean_stars = np.full(len(df), prior_stars, dtype="float64")
    mean_stars[has] = stars[has] / seen[has]

    elapsed = (df["rated_at"] - state["prior_first"]).dt.days.to_numpy(dtype="float64")
    tenure = np.where(np.isnan(elapsed), prior_tenure, elapsed)

    pace = np.full(len(df), prior_pace, dtype="float64")
    pace[has] = seen[has] / np.maximum(elapsed[has], 1.0)

    return df.assign(
        f_mbr_prior_ratings=seen,
        f_mbr_prior_likes=likes,
        f_mbr_like_rate=rate,
        f_mbr_mean_stars=mean_stars,
        f_mbr_tenure_days=tenure,
        f_mbr_ratings_per_day=pace,
        f_mbr_is_new=np.where(has, 0, 1).astype("int64"),
    )
ENGAGEMENT_EOF

cat > src/engagement/recent.py <<'ENGAGEMENT_EOF'
"""How the member has been behaving lately, rather than over all time."""
import numpy as np
import pandas as pd

RECENT_RATINGS = 20


def add(df, fit_df, prior_rate, prior_gap):
    ordered = fit_df.sort_values(["member_id", "rated_at"], kind="stable")
    grouped = ordered.groupby("member_id", sort=False)
    state = pd.DataFrame({
        "member_id": ordered["member_id"].to_numpy(),
        "rated_at": ordered["rated_at"].to_numpy(),
        "run_recent": (grouped["liked"]
                       .transform(lambda s: s.shift(1)
                                  .rolling(RECENT_RATINGS, min_periods=1).mean())).to_numpy(),
        "run_prev": grouped["rated_at"].shift(1).to_numpy(),
    }).sort_values(["rated_at", "member_id"], kind="stable").reset_index(drop=True)

    probe = (df[["member_id", "rated_at"]].assign(_pos=np.arange(len(df)))
             .sort_values(["rated_at", "member_id"], kind="stable"))
    merged = (pd.merge_asof(probe, state, on="rated_at", by="member_id",
                            allow_exact_matches=False, direction="backward")
              .sort_values("_pos", kind="stable"))

    recent = merged["run_recent"].to_numpy(dtype="float64")
    gap = ((df["rated_at"].to_numpy() - merged["run_prev"].to_numpy())
           .astype("timedelta64[s]").astype("float64") / 86400.0)
    return df.assign(
        f_mbr_recent_rate=np.where(np.isnan(recent), prior_rate, recent),
        f_mbr_days_since_prev=np.where(np.isnan(gap), prior_gap, gap),
    )
ENGAGEMENT_EOF

cat > src/engagement/spread.py <<'ENGAGEMENT_EOF'
"""How consistent a member or a film has been, as of the rating being scored."""
import numpy as np
import pandas as pd


def prior_spread(df, fit_df, key):
    ordered = fit_df.sort_values("rated_at", kind="stable")
    table = {}
    for name, block in ordered.groupby(key, sort=False):
        stars = block["stars"].to_numpy(dtype="float64")
        table[name] = (block["rated_at"].to_numpy(),
                       np.concatenate([[0.0], stars.cumsum()]),
                       np.concatenate([[0.0], (stars ** 2).cumsum()]))
    out = np.full(len(df), np.nan)
    for position, (name, stamp) in enumerate(zip(df[key].to_numpy(), df["rated_at"].to_numpy())):
        entry = table.get(name)
        if entry is None:
            continue
        times, total, square = entry
        taken = int(np.searchsorted(times, stamp, side="left"))
        if taken < 2:
            continue
        mean = total[taken] / taken
        var = square[taken] / taken - mean ** 2
        out[position] = np.sqrt(max(var, 0.0))
    return out


def add(df, fit_df, prior_member_spread, prior_film_spread):
    member = prior_spread(df, fit_df, "member_id")
    film = prior_spread(df, fit_df, "film_id")
    return df.assign(
        f_mbr_stars_spread=np.where(np.isnan(member), prior_member_spread, member),
        f_film_stars_spread=np.where(np.isnan(film), prior_film_spread, film),
    )
ENGAGEMENT_EOF

python3 run_scoring.py --config configs/reference.yaml --out out/reference
python3 run_scoring.py --config configs/current.yaml   --out out/current
echo "rebuild complete"
