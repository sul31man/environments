"""LOCKED Latchwork knobs (Phase-1 freeze).

Frozen after the knob sweep (tests/tune.py).  Changing any value here re-opens
calibration -- do not edit without re-running the Stage-0 gate battery.
"""

from .generator import GenConfig

# Regime decided up front: BAND (frontier pass@1 ~0.35-0.65), wall as fallback.
BAND = (0.35, 0.65)
ACCEPT_THRESHOLD = 0.95      # a submission "passes" (for FAR accounting) at >=0.95
ROTE_MARGIN = 0.05           # rote must wall this far below the band floor
BUDGET = 20000               # generous total-probe budget: reasoning-limited, not
                             # probe-starved (condition 3).  Batched over the
                             # ~40-80 sequential step horizon at serve time.

# Form quota (locked via tests/tune.py, config "S1"): zero intervals and zero
# ORDER -- only forms a single-field interval fit structurally CANNOT capture
# (SET non-contiguous, MODULAR periodic, LINEAR/DEPENDENCY two-field).  So
# mechanical (rote/batch) solvers wall on EVERY instance; classification-based
# adaptive discovery reaches the band.  Fields stay random -> class form-agnostic.
_QUOTA = {"INTERVAL": 0, "SET": 3, "MODULAR": 2, "LINEAR": 3, "ORDER": 0, "DEPENDENCY": 2}

# n_groups=8: finer field-location class cuts the mechanical solvers' coincidental
# (index,class) matches (rote worst-case 0.34 -> 0.28, clean margin below the band)
# and adds field-location signal for the real solver, WITHOUT leaking form
# (class is still a function of field only; MI(class;form) ~ 0.003).
LOCKED_CONFIG = GenConfig(
    n_fields=10,
    domain=64,
    n_stages=10,
    coupling=0.80,
    max_pass_rate=0.50,
    min_pass_rate=0.02,
    n_groups=8,
    form_quota=_QUOTA,
)
