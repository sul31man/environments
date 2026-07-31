"""PageForge -- agent implementation target.

Implement `layout(doc, cfg)` to match EXACTLY the declarative semantics disclosed
in this instance's spec. `pfcore` (document/token/float types) and `semconfig`
(SemConfig with this instance's forms) are GIVEN and must not be edited.

    layout(doc: pfcore.Doc, cfg: semconfig.SemConfig) -> list[str]

Return one string per rendered page: exactly cfg.H lines of exactly cfg.W
columns, lines joined by "\n". Grading compares your pages to the reference
output on hidden documents by exact string equality.

You will typically want to build these internally (any structure is fine -- only
the returned pages are graded):
  - line breaking + hyphenation      (cfg.hyph / cfg.hyph_k / cfg.hyph_pos)
  - justification                    (cfg.just; PAGE_PARITY depends on page-local
                                      line index)
  - pagination with widow/orphan/keep resolution, ranked by cfg.priority, under
    the capacity taken by floats, splittable footnotes, and the folio
  - the cross-reference fixpoint     (refs render 'p.<page>'; iterate to stable)
"""
from . import pfcore, semconfig  # noqa: F401  (given types)


def layout(doc, cfg):
    raise NotImplementedError("implement PageForge layout(doc, cfg) -> list[str]")
