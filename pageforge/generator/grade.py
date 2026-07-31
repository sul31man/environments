"""PageForge grading: reward for a candidate layout engine vs the gold oracle
on an instance's document corpus. Grade-by-value: candidate returns list[str]
rendered pages; compared to gold by exact string equality (no cross-module
identity). Reward = 0.7 * page-match fraction + 0.3 * doc-match fraction.

# PAGEFORGE_ORACLE_SENTINEL_7b1e9f4a
"""
from __future__ import annotations
from dataclasses import replace

from . import engine as A
from . import enumerator as EN
from .semconfig import SemConfig

BUCKETS = ("pages", "structure", "edge", "spec")
STRICT = 0.95


def gold_pages(doc, cfg):
    return A.layout(doc, cfg)[0]


def score(layout_fn, corpus, cfg):
    """corpus: list of (doc, category). Returns (reward, detail)."""
    tot_pages = matched_pages = 0
    tot_docs = matched_docs = 0
    bucket = {b: [0, 0] for b in BUCKETS}
    for doc, cat in corpus:
        g = A.layout(doc, cfg)[0]
        try:
            c = layout_fn(doc, cfg)
        except Exception:
            c = []
        tot_docs += 1
        pm = sum(1 for j in range(len(g)) if j < len(c) and c[j] == g[j])
        tot_pages += len(g)
        matched_pages += pm
        full = 1 if c == g else 0
        matched_docs += full
        b = {"killer": "edge", "fixpoint": "edge", "single": "spec"}.get(cat, "structure")
        bucket[b][0] += full
        bucket[b][1] += 1
    page_frac = matched_pages / tot_pages if tot_pages else 0.0
    doc_frac = matched_docs / tot_docs if tot_docs else 0.0
    reward = 0.7 * page_frac + 0.3 * doc_frac
    detail = {"page_frac": page_frac, "doc_frac": doc_frac,
              "buckets": {b: (bucket[b][0], bucket[b][1]) for b in BUCKETS}}
    return reward, detail


# ---- baseline layout functions (gold, enumerator, ladder rungs, cheats) -----

def gold_fn(doc, cfg):
    return A.layout(doc, cfg)[0]


def enumerator_fn(doc, cfg):
    return EN.enum_layout(doc, cfg)[0]


def null_fn(doc, cfg):
    """Blank pages of the right dimensions but the wrong page count (floor)."""
    return [("\n".join([" " * cfg.W] * cfg.H))]


# Per-family "prior/wrong" substitutions -> ladder rungs. Each disables ONE
# family (uses a wrong form) so its cost is measured; load-bearing if < STRICT.
def _canon_priority():
    return ("KEEP", "WIDOW", "ORPHAN")


LADDER = ("just", "hyph", "priority", "folio", "foot", "headdrop", "hyphpos", "suppress")


def ladder_fn(rung):
    def f(doc, cfg):
        if rung == "just":
            c = replace(cfg, just=("LEFT" if cfg.just != "LEFT" else "RIGHT_HEAVY"))
        elif rung == "hyph":
            c = replace(cfg, hyph=("NONE" if cfg.hyph != "NONE" else "EVERY_K"))
        elif rung == "priority":
            other = ("KEEP", "WIDOW", "ORPHAN")
            c = replace(cfg, priority=(other if cfg.priority != other
                                       else ("ORPHAN", "WIDOW", "KEEP")))
        elif rung == "folio":
            c = replace(cfg, folio=("NONE" if cfg.folio != "NONE" else "BOT"))
        elif rung == "foot":
            c = replace(cfg, foot_reserve=("full" if cfg.foot_reserve == "min" else "min"))
        elif rung == "headdrop":
            c = replace(cfg, head_blank_top_drop=not cfg.head_blank_top_drop)
        elif rung == "hyphpos":
            c = replace(cfg, hyph_pos=("LEAD" if cfg.hyph_pos == "TRAIL" else "TRAIL"))
        elif rung == "suppress":
            c = replace(cfg, folio_suppress_topfloat=not cfg.folio_suppress_topfloat)
        else:
            c = cfg
        try:
            return A.layout(doc, c)[0]
        except Exception:
            return []
    return f


# Cheat battery (all must score < STRICT).
def cheat_constant(doc, cfg):
    return [("\n".join([" " * cfg.W] * cfg.H))]


def cheat_shape(doc, cfg):
    """Right page count and dimensions, wrong content (all 'x')."""
    g = A.layout(doc, cfg)[0]
    return ["\n".join([("x" * cfg.W)] * cfg.H) for _ in g]


def cheat_hardcoded(visible):
    """Memorize the visible example outputs; return them by doc identity, else blank."""
    memo = {id(d): p for (d, p) in visible}
    def f(doc, cfg):
        return memo.get(id(doc), [("\n".join([" " * cfg.W] * cfg.H))])
    return f
