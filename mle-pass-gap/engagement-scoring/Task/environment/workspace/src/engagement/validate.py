"""Sanity checks run before the scores are published."""


class ValidationError(Exception):
    pass


def check(scores):
    if len(scores) == 0:
        raise ValidationError("no rows were scored")
    if scores["engagement"].isna().any():
        raise ValidationError("engagement contains nulls")
    bad = scores[(scores["engagement"] < 0.0) | (scores["engagement"] > 1.0)]
    if len(bad) > 0:
        raise ValidationError("engagement outside [0, 1] on %d rows" % len(bad))
    return True
