"""Strategy constants for the DSRD short-strangle system (single source).

Values are frozen by the spec (docs/superpowers/specs/2026-08-18-dsrd-options-
design.md §6) — change them there first, here second, never silently.
"""

RISK_FREE_RATE = 0.07
DELTA_BAND = (0.10, 0.20)
IDEAL_DELTA = 0.15
MIN_STRIKE_DISTANCE = 0.08
PROFIT_TARGET_REMAINING = 0.20   # exit when combined premium <= 20% of entry
STOP_MULTIPLIERS = {"1:1": 2.0, "1:1.5": 2.5, "1:2": 3.0, "none": None}
MAX_POSITIONS = 3
MARGIN_BUDGET_FRACTION = 0.70
SCORE_FLOOR = 75.0
JUDGE_CAPITAL = 500_000.0  # amended from the doc's 1L — see plan deviation ledger
