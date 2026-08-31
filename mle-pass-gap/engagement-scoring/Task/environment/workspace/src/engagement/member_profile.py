"""What the membership record says about the rater."""
import numpy as np
import pandas as pd

GENDERS = ["F", "M"]


def add(df, members):
    out = df.merge(members, on="member_id", how="left", sort=False)
    out["f_gender"] = out["gender"].map({g: i for i, g in enumerate(GENDERS)}).fillna(-1).astype("int64")
    out["f_age_band"] = out["age_band"].fillna(-1).astype("int64")
    out["f_occupation"] = out["occupation"].fillna(-1).astype("int64")
    region = out["postcode"].astype(str).str.slice(0, 1)
    out["f_region"] = pd.to_numeric(region, errors="coerce").fillna(-1).astype("int64")
    return out.drop(columns=["gender", "age_band", "occupation", "postcode"])
