"""Sanity checks run before the scores are published."""


class ValidationError(Exception):
    pass


def check(scores):
    if len(scores) == 0:
        raise ValidationError("no rows were scored")
    values = scores["risk_score"].values
    if any(v != v for v in values):
        raise ValidationError("risk_score contains nulls")
    bad = [v for v in values if v < 0.0 or v > 1.0]
    if bad:
        raise ValidationError("risk_score outside [0, 1] on %d rows" % len(bad))
    return True
