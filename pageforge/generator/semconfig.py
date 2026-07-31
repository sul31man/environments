"""PageForge semantic configuration.

SemConfig holds the per-instance forms for all 10 families plus the priority
permutation; the difficulty generator samples these per instance.

NOTE: GIVEN to the agent (copied into the workspace); carries no oracle canary.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemConfig:
    # page grid
    W: int = 20
    H: int = 4
    # WID: widow threshold (a paragraph tail of < w lines may not start a page
    # alone). The w=2 widow case is implemented via PULL_BACK.
    widow: int = 2
    # priority: permutation of the soft-violation rule names, highest priority
    # FIRST. Governs which rule is waived on conflict and thus WHERE sanctioned
    # violations land (SEMANTICS sec 4). Full family set: KEEP, WIDOW, ORPHAN.
    priority: tuple = ("KEEP", "WIDOW", "ORPHAN")
    # JUST (justification, SEMANTICS sec 5c): distribute surplus spaces on every
    # non-final line of a paragraph. Forms: LEFT (prior), RIGHT_HEAVY, PAGE_PARITY.
    just: str = "LEFT"
    # HYPH (hyphenation, sec 5c): NONE (prior) or EVERY_K. hyph_pos TRAIL/LEAD.
    hyph: str = "NONE"
    hyph_k: int = 3
    hyph_pos: str = "TRAIL"
    # FURN (page furniture / folio, sec 5c): NONE, TOP, or BOT; reserves 1 row.
    folio: str = "NONE"
    folio_fmt: str = "- %d -"
    folio_suppress_topfloat: bool = False   # E10 FURN<->FLOAT capacity coupling
    # HEAD (heading spacing, sec 5c): blank rows around headings; a head-blank at
    # the TOP of a page's text is DROPPED (prior) or KEPT (anti-prior, E11).
    head_blank_before: int = 0
    head_blank_after: int = 0
    head_blank_top_drop: bool = True
    # FOOT: minimum footnote rows guaranteed on the anchor's own page (sec 5b).
    foot_min: int = 1
    # FOOT draining rule (measured decision; "min" is the default):
    #   "min"  = text-greedy; feasibility reserves only foot_min per anchor, the
    #            footnote drains into leftover/continuation (default).
    #   "full" = feasibility reserves each anchor's FULL body height, so footnotes
    #            fully fit their anchor page (no split) and text is pushed forward.
    foot_reserve: str = "min"
    # XREF fixpoint controls (SEMANTICS sec 6)
    initial_ref_page: int = 1
    max_rounds: int = 8


# The soft-violation rule names the priority key ranks over. The violation key in
# the engines is ordered by cfg.priority (a permutation of these), not this list.
RULES = ("KEEP", "WIDOW", "ORPHAN")
