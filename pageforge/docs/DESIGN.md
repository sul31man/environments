# PageForge -- Design

**What it is.** A hard, sound RL training environment. The agent implements an
ASCII typesetting/pagination engine -- `layout(doc, cfg) -> list[str]` -- from a
disclosed per-instance declarative spec, and is graded by EXACT rendered-page
string equality on a hidden document corpus (monospace grid, so equality is exact).
Enumerator-hard with a dense reward gradient; the difficulty is measured offline
(the reconstructed-enumerator gate scores 0.41 mean across 50 eval instances; 0.32
on the 5-instance probe). See `private/full_check.py`.

## The interacting correctness surface (10 families)
BREAK (line breaking) / HYPH (hyphenation) / JUST (justification incl.
page-parity) / WID (widow + orphan, PULL_BACK) / KEEP (keep-with-next +
keep-together) / FOOT (splittable footnotes, min-first-page + continuation) /
FLOAT (figures, T/B zones, place-or-defer) / XREF (cross-reference fixpoint) /
FURN (folio, suppress-on-top-float) / HEAD (heading spacing, top-blank drop/keep).
Plus a per-instance PRIORITY permutation over the soft rules {KEEP, WIDOW, ORPHAN}
that decides which rule is waived on conflict (and thus where sanctioned
violations land). Normative semantics: `SEMANTICS.md`.

## Why it's hard (the interaction difficulty)
The families interact through shared page state: a footnote/float/folio reservation
shrinks text capacity -> moves a break -> creates a widow -> the widow repair moves
the anchor line -> moves the footnote -> changes a page number -> changes a
cross-reference's rendered width -> changes line breaking (a true fixpoint). A
branch-per-family, independence-composed layout (the reconstructed ENUMERATOR)
scores mean 0.41 (all < 0.95): one early capacity/repair error cascades through
every downstream page. That is the training signal -- a dense gradient over a
genuinely coupled, un-enumerable-by-independent-composition surface.

## Oracle & soundness
- Two independently-architected engines: `engine.py` (A, iterative mutable cursor)
  and `interp_b.py` (B, recursive/functional). They agree byte-for-byte on 1500+
  randomized docs (differential oracle), giving a contamination-free reference.
- Seeded, deterministic generation (`facet_rng`, blake2b); eval/train disjoint.
- Grade-by-value (`generator/grade_workspace.py`): plain-data docs across the agent
  boundary, page strings compared exactly; no cross-module identity. Grading is
  independent per submission -- no workspace is left on `sys.path` -- so scoring one
  submission cannot affect the next.
- Process-isolated (`generator/sandbox.py`, the DEFAULT): the agent's `layout()`
  runs in a subprocess where the oracle was never loaded, and which refuses to
  start if it is importable. Purging the disk alone is not sufficient -- see
  `ISOLATION.md`. Agent code is also bounded in wall-clock, so a non-terminating
  submission scores rather than stalling the grader.
- FAR/FRR with Wilson CIs, cheat battery, reconstructed-agent regrade: see
  `WRITEUP.md` (section 3) and `private/soundness.py`.
- Serve-time oracle purge + leak-probe trace discipline: `pageforge_env.py`
  (`purge_oracle` / `assert_isolated`, which fails closed on BOTH the disk and
  the import path).

## Layout
`generator/` engine A/B, enumerator, grade, instance generator, probe oracle/server,
sandbox (process-isolated grading).
`private/` gates, soundness, slice_check regression, leak checker, `leak_test/`
(two-condition process-isolation tests; offline only).
`workspace/pageforge/` agent package (given pfcore/semconfig + engine.py stub);
`workspace/probe.py` Phase-1 client. `pageforge_env.py` framework-agnostic adapter.
