# PageForge -- Normative Semantics (SEMANTICS.md)

This document is the single source of truth for the layout semantics -- the
oracle specification. **It is withheld from the agent:** during an episode the
agent sees no part of these rules, and must recover each per-instance form
through the Phase-1 probe channel. Two independently-architected engines
(A = `generator/engine.py`, B = `generator/interp_b.py`) must both implement
EXACTLY these rules and agree byte-for-byte. Any divergence found by the
differential is resolved HERE first -- never by a silent tie-break in code.

All families below are normative for every instance; the per-instance config
selects each family's form. Two independently-architected engines
(A = generator/engine.py, B = generator/interp_b.py) must both implement them and
agree byte-for-byte.

## 0. Grid and rendering

- A page has exactly `H` content lines, each exactly `W` columns.
- A line's text is left-aligned and right-padded with spaces (`0x20`) to `W`.
- A page with fewer than `H` content lines is padded with blank lines (each `W`
  spaces) to exactly `H` lines. A page renders as the `H` line-strings joined by
  `"\n"`. A document renders to `list[str]`, one string per page, in order.
- Output equality is exact string equality per page and equal page count.

## 1. Document model

A document is an ordered list of BLOCKS. A block is one of:
- PARA: a paragraph, `kind="para"`, an ordered list of TOKENS, optional `label`.
- HEADING: `kind="heading"`, tokens, optional `label`. A heading has the
  keep-with-next property (see sec 5).

A block may carry `keep_together=True` (KEEP family; see sec 5): all of its galley
lines must lie on a single page.

A TOKEN is either a WORD (literal ASCII string, no spaces) or a REF (carries a
target `label`). Blocks and labels are unique within a document.

## 2. Reference rendering (REF) and the label->page map

- The label->page map `M` maps each block `label` to the 1-based page index on
  which that block's FIRST galley line is placed (sec 4).
- A REF to `label` renders to the literal string `"p." + str(M[label])`. Its
  width is the length of that string.
- Because a REF's width depends on `M`, and `M` is produced by layout, and layout
  depends on line breaks which depend on REF widths, the layout is defined as a
  FIXPOINT over `M` (sec 6).

## 3. Line breaking (BREAK) -- forward first-fit greedy

Given a block's tokens and the current map `M` (so every REF has a concrete
width), break into lines for column width `W`:

1. Start with an empty current line and `cur = 0` (used columns).
2. For each token `t` with rendered width `wt`:
   - If the current line is empty: place `t`; set `cur = wt`.
   - Else if `cur + 1 + wt <= W`: append `t` with one separating space; set
     `cur = cur + 1 + wt`.
   - Else: flush the current line; start a new line with `t`; set `cur = wt`.
3. Flush the final non-empty line.

A single token wider than `W` occupies its own line and is NOT truncated;
documents are constructed so this does not arise, and mid-word splitting is
governed by HYPH (sec 5c). Line text is the tokens joined by single spaces.
Headings break by the same rule.

The GALLEY is the concatenation, in document order, of every block's broken
lines. Each galley line carries: its text; the id of its block (`para_id`);
whether the block is a heading; `para_first`/`para_last` (is this the first/last
line of its block); and `para_len` (number of lines in its block). The FIRST
galley line of a block is the one whose page defines `M[label]`.

## 4. Pagination -- canonical greedy left-to-right with local, priority-scored cuts

Pagination assigns a contiguous run of galley lines to each page, in order, with
at most `H` lines per page and at least 1 line per page. It is defined as a
single LEFT-TO-RIGHT pass that never revisits a completed page. For a page
starting at galley index `s` (0-based), choose the end index `e` (the page holds
`G[s:e]`, so `s < e <= min(s+H, N)` where `N = len(G)`):

First, CANDIDATE VALIDITY (hard constraints, non-waivable). A candidate `e` is
INVALID if it splits a keep-together block -- i.e. some keep-together block spans
galley indices `[a, b)` with `a < e < b`. Invalid candidates are excluded before
scoring. If no candidate in `[s+1, min(s+H, N)]` is valid (a keep-together block
starting at `s` is taller than `H`, or a block straddles the entire window), the
document is UNLAYOUTABLE and is rejected by the generator (only layoutable
documents are emitted). Excluding a keep-together block from a page can force
the page to end on a heading (a KEEP boundary violation with no alternative) --
that is the capacity pressure that makes sec 5's sanctioned violations possible.

For each VALID candidate `e`, the CUT lies between `G[e-1]` (last line on this
page) and `G[e]` (first line of the next page, if `e < N`). Define the BOUNDARY
VIOLATIONS of a candidate `e`:

- KEEP violation -- iff `G[e-1].is_heading` is true (a heading may not be the
  last line of a page). Depends only on `e`.
- WIDOW violation -- iff `e < N` and `G[e].para_last` and `G[e].para_len >= 2`
  and `G[e-1].para_id == G[e].para_id` (the cut splits off a paragraph's final
  line, leaving it alone atop the next page). Depends only on `e`.
- ORPHAN violation -- iff `e < N` and `G[e-1].para_first` and
  `G[e-1].para_len >= 2` and `G[e-1].para_id == G[e].para_id` (the cut leaves a
  paragraph's FIRST line alone at the bottom of this page). Depends only on `e`.

The priority key ranks these soft violations by `cfg.priority`, a PERMUTATION of
`("KEEP","WIDOW","ORPHAN")`. The permutation is a per-instance facet: it decides
which rule is waived on conflict and therefore WHERE sanctioned violations land.
`head`-blank lines (sec 5c HEAD) and folio/float rows never trigger KEEP/WIDOW/ORPHAN
(they carry no `para_first/para_last`).

Selection rule (deterministic, unique):
1. Enumerate all candidates `e` in `[s+1, min(s+H, N)]`.
2. For each, form the violation key: a tuple counting violations in PRIORITY
   order, highest-priority first. The priority order is given by `cfg.priority`,
   a per-instance permutation of `("KEEP","WIDOW","ORPHAN")`; `key(e) =
   (count_of_highest_priority_violation, count_of_next, count_of_last)`.
3. Choose the candidate that LEXICOGRAPHICALLY MINIMIZES the violation key
   (satisfy higher-priority rules first). Among candidates tied on the key,
   choose the LARGEST `e` (maximize page utilization). This is total and unique.
4. A violation present in the chosen `e` is a SANCTIONED VIOLATION: it remains in
   the output because avoiding it would incur an equal-or-higher-priority
   violation, or because no candidate avoids it. The chosen `e` still minimizes
   the priority-ordered key, so a sanctioned violation is always of strictly
   lower priority than any violation it was traded against.

Set the next page start to `e` and repeat until `e == N`.

### Path dependence
The start index `s` of every page is determined by all earlier pages' choices.
Reducing a page's `e` to satisfy a higher-priority rule (equivalently, "pulling
back" a line so a paragraph's tail travels together to the next page) shifts `s`
for every later page and can change their cuts and page numbers. Thus the layout
depends on the repair TRAJECTORY, not merely on which layouts are rule-consistent.
A global penalty-minimizer that trades violations across non-adjacent pages will
in general reach a different, rule-consistent-but-non-canonical layout; only the
left-to-right greedy result is correct.

### WID = PULL_BACK, stated as lookahead
The WID repair form is PULL_BACK: a paragraph's final line must not be
alone atop a page. Under the greedy pass this is realized by page `P-1` choosing
a smaller `e` (placing one fewer line) so that `>= 2` tail lines of the paragraph
begin page `P` together. No page is revisited; the effect is identical to
retracting page `P-1`'s last line.

## 5. Keep-with-next (KEEP)

The KEEP family has two sub-rules:
- keep-with-next (heading): a heading may not be the last line of a page (there
  must be at least one following line on the same page). This is the KEEP
  boundary violation in sec 4 (a priority-waivable soft rule).
- keep-together (`keep_together=True`): all lines of the block lie on one page.
  This is a HARD constraint enforced by candidate exclusion in sec 4 (never waived).

Sanctioned violations require CAPACITY PRESSURE: with under-fill permitted and
mid-paragraph cuts always clean, KEEP-with-next and WIDOW are mutually blocking
ONLY when the residual page space is smaller than the smallest legal placement.
Three independent families supply that pressure -- keep-together here, and the
capacity consumers of sec 5b (footnote areas, edge E5 FOOT<->WID; and floats, edge
E6 FOOT<->FLOAT). A keep-together block that cannot fit in a page's remaining
space is excluded, which can force the page to end on a heading (sanctioned
KEEP) or force a paragraph's final line alone onto the next page (sanctioned
WIDOW). When KEEP-with-next and WIDOW clash, sec 4's priority-ordered key decides
which is waived, per `cfg.priority`. Both engines must place the identical
waived site.

## 5b. Floats (FLOAT) and splittable footnotes (FOOT)

These are the capacity-consuming families. They make the sanctioned-violation
property arise NATURALLY: footnote areas and floats shrink
a page's text capacity, which forces widow/keep clashes that sec 4's priority key
must waive. All of sec 5b is normative and both engines must agree byte-for-byte.

### Model additions
- A FLOAT is an out-of-flow block (`kind="float"`) with height `h` (rows), a zone
  `T` (top) or `B` (bottom), and `h` fixed ASCII art rows. It produces NO text
  galley lines. Its ANCHOR index is the number of text galley lines emitted
  before it in document order.
- A FNMARK token `^id` inside a paragraph renders in the text as the literal
  `"^"+id` (its width counts in BREAK, sec 3 -- a FOOT<->BREAK coupling). It anchors a
  FOOTNOTE whose body is `doc.notes[id]`, a tuple of fixed ASCII rows. A text
  galley line records the ordered list of fnmark ids it contains.

### Per-page resolution PAGE(P)
Pagination (sec 4) is replaced, when floats/footnotes are present, by the following
deterministic per-page procedure. Inputs: text start index `s`; the ordered
queue of not-yet-placed floats; `foot_cont` = the ordered list of footnote body
rows carried (split) from the previous page. Let `f = cfg.foot_min` (default 1).

STEP 1 -- place floats (before choosing text). Walk the float queue in anchor
order. A float `F` is ELIGIBLE iff `anchor(F) <= s` (its call site is on a prior
page or exactly at this page's first line). For each float, in order:
- if `F` is not eligible: STOP (all later floats have later anchors).
- else if `reserve_top + reserve_bot + F.h + len(foot_cont) + 1 <= H`: place `F`
  on page P in its zone; add `F.h` to the zone reserve.
- else: STOP (strict-order queue: do not skip an earlier-anchor float to fit a
  later one; the float defers to a subsequent page).
Let `float_res = reserve_top + reserve_bot`.

STEP 2 -- choose the text end `e`. Let `cont_res = len(foot_cont)`. For each
candidate `e` in `[s+1, min(s + (H - float_res - cont_res), N)]`:
- exclude if it splits a keep-together block (sec 4).
- let `anchors_in` = the fnmark ids in `galley[s:e]` (in order).
- `reserved_min = cont_res + f * len(anchors_in)` (guaranteed footnote rows).
- FEASIBLE iff `(e - s) + float_res + reserved_min <= H`. Exclude infeasible `e`.
- compute the KEEP/WIDOW boundary violations of `e` exactly as sec 4.
Among feasible, non-splitting, valid candidates, choose the one MINIMIZING the
sec 4 priority-ordered violation key, then MAXIMIZING `e`. If NO candidate is
feasible (a single line plus its minimum footnote plus floats cannot fit), the
document is UNLAYOUTABLE (rejected by the generator). A chosen `e` that still
carries a violation is a SANCTIONED violation exactly as sec 4 -- but now the
pressure forcing it comes from `float_res`/`cont_res`, i.e. from FLOAT/FOOT.

STEP 3 -- fill the footnote area (bottom-anchored, in order). Let
`text_count = e - s` and `bottom = H - float_res - text_count` (rows available
for footnotes on this page). Build the ordered row list
`queue = foot_cont ++ (for each id in anchors_in: list(doc.notes[id]))`. First
guarantee the minimum: reserve `f` rows for each anchor's footnote (these are the
rows at the anchor-footnote's start). Then fill `queue` into `bottom` rows IN
ORDER, line by line; place as many as fit. The rows placed this page are the
footnote area; any unplaced tail of `queue` becomes `foot_cont` for page P+1 (a
CONTINUATION, next-page bottom). Feasibility (STEP 2) guarantees every anchor
gets at least `f` rows on its own page.

STEP 4 -- record `label->page` from the FIRST TEXT line of each labelled block
(floats/footnote rows do NOT count). Advance `s := e` and repeat until `s == N`
with the float queue drained onto legal pages and `foot_cont` empty (else the
final page carries the tail; a document whose footnotes cannot drain by the last
page is UNLAYOUTABLE).

### Page rendering with floats/footnotes (exact vertical order, top->bottom)
`[TOP float art rows] ++ [text rows] ++ [blank pad] ++ [BOT float art rows] ++
[footnote rows]`, where `pad = H - top - text - bot - foot >= 0` keeps the bottom
matter flush to the page bottom. Every row padded to `W`; the page is exactly `H`
rows. (A page with no floats/footnotes reduces to sec 0/sec 4.)

### Interaction edges (FOOT/FLOAT)
- E5 FOOT<->WID: a footnote's reserved rows shrink text capacity (STEP 2), forcing
  a widow whose repair moves the anchor line off the page -- which moves the
  footnote with it (STEP 4 re-derivation on the next page). Two-round feedback.
- E6 FOOT<->FLOAT: a BOT float (reserved in STEP 1) and a footnote compete for the
  same bottom rows; the float wins the space (placed first), so the footnote
  splits/continues or the text end retreats -- a capacity clash that can itself
  force a sanctioned widow/keep.

## 5c. JUST, HYPH, FURN, HEAD (remaining families)

All normative; both engines agree byte-for-byte. Each family carries a per-
instance FORM (with an anti-prior variant) and its coupling.

### HYPH (hyphenation) -- extends BREAK (sec 3)
When the next word `w` (width `wt`) does not fit on the current line (available
columns `avail = W - cur - 1`, or `W` on an empty line), attempt to hyphenate
BEFORE wrapping (form `EVERY_K`; form `NONE` = never hyphenate, always wrap):
- Valid split positions `p` (1-based char count of the first fragment): the
  fragment `w[:p]` and remainder `w[p:]` must each have length `>= 2`, and
  `p` is a multiple of `cfg.hyph_k`.
- Choose the LARGEST valid `p` such that the placed fragment fits `avail`:
  - `hyph_pos = TRAIL`: the current line receives `w[:p] + "-"` (needs
    `len(w[:p]) + 1 <= avail`); the remainder token that starts the next line is
    `w[p:]`.
  - `hyph_pos = LEAD` (anti-prior): the current line receives `w[:p]` (needs
    `len(w[:p]) <= avail`); the remainder token is `"-" + w[p:]`.
- If a fragment is placed, flush the line; the remainder becomes the first token
  of the next line and re-enters BREAK (it may hyphenate again).
- If no valid fragment fits, wrap `w` whole (flush, start next line with `w`).
The remainder token is an ordinary word for width purposes (its leading/trailing
`-` counts). A FnMark/Ref token is never hyphenated (only literal words).

### JUST (justification) -- RENDER-time transform, depends on pagination (E4)
Applied when rendering a text row that is NOT its block's final line, is not a
heading, is not a head-blank, and has `>= 2` space-separated words. Let
`gaps = words - 1`, `surplus = W - natural_width` (`natural_width` = single-space
width). Distribute `surplus` extra spaces over the gaps: each gap gets
`surplus // gaps`; the remaining `r = surplus % gaps` +1-spaces are assigned to
`r` gaps chosen by the form, where the page-local text-row index `j` (0-based,
counting only text rows within the page) is used by PAGE_PARITY:
- `LEFT` (prior): the leftmost `r` gaps.
- `RIGHT_HEAVY`: the rightmost `r` gaps.
- `PAGE_PARITY`: leftmost `r` gaps if `j` is even, else rightmost `r` gaps.
Final/heading/blank/one-word rows are left-aligned and right-padded. Justification
NEVER changes a line's width (always `W`), so it does not feed back into
pagination; but under PAGE_PARITY the rendered row depends on the page-local index
`j`, so any page-break motion re-justifies rows (edge E4). An enumerator that
justifies during the line pass (global index, pre-pagination) gets the parity
wrong.

### FURN (folio) -- reserves a row, couples capacity (E10)
If `cfg.folio != NONE`, every page carries a folio row showing
`cfg.folio_fmt % page_index` at the page TOP (`folio=TOP`) or BOTTOM
(`folio=BOT`). The folio reserves 1 row of the page (`folio_res = 1`), EXCEPT
when `cfg.folio_suppress_topfloat` is set and the page carries a TOP-zone float,
in which case the folio is suppressed (`folio_res = 0`, no folio row) -- a
capacity coupling with FLOAT (E10). `folio_res` enters the per-page capacity
exactly like `float_res` (STEP 2 feasibility and the text window). The page index
is known (no fixpoint).

### HEAD (heading spacing) -- blank rows, top-drop couples capacity (E11)
`cfg.head_blank_before` blank galley rows are emitted before each heading and
`cfg.head_blank_after` after it. A blank row is a galley line with no paragraph
identity (never triggers KEEP/WIDOW/ORPHAN) and is not justified. TOP-DROP rule:
when a page's TEXT region would BEGIN with one or more head-blank rows, those
leading blanks are DROPPED under `head_blank_top_drop=True` (they consume no
capacity: the page start `s` advances past leading blank rows BEFORE floats/text
are chosen) and KEPT under `False` (they consume rows like any line). Dropping at
the page top frees capacity, changing widow/keep arithmetic at the boundary
(edge E11). Blank rows in a page interior always render as blank rows.

### Per-page resolution PAGE(P), amended for sec 5c
STEP 0 (new): under `head_blank_top_drop`, advance `s` past any leading
head-blank galley rows (they are dropped, render nothing, consume nothing).
STEP 1b (new, after floats): compute `folio_res` per FURN. Let
`fixed_res = float_res + folio_res`. Everywhere STEP 2 used `float_res`, use
`fixed_res`. STEP 3 `bottom = H - fixed_res - text_count`. Rendering order,
top->bottom: `[folio if TOP] ++ [TOP floats] ++ [text rows (justified)] ++ [pad]
++ [BOT floats] ++ [footnote rows] ++ [folio if BOT]`, padded to exactly `H`.

## 6. Cross-reference fixpoint (XREF)

The output is the self-consistent layout reached by iterating the map `M`:

1. Initialize `M_0`: every label maps to `cfg.initial_ref_page` (default 1). This
   fixes every REF width for the first round. (`initial_ref_page` is a
   deliberately confusable seed used by the uniqueness probe; the fixpoint must
   be invariant to it -- see below.)
2. Round `r`: run BREAK (sec 3) with `M_{r-1}` to build the galley, then paginate
   (sec 4) to obtain pages and the realized map `M_r` (each label -> page of its
   block's first galley line).
3. Stop when `M_r` agrees with `M_{r-1}` on every label that is the target of at
   least one REF (the reference-relevant subset). The layout for `M_r` is the
   output. Iterate at most `cfg.max_rounds` (default 8); a document that has not
   converged by then is INVALID (the generator rerolls it; only convergent
   documents are emitted).

### Uniqueness requirement (normative)
The reachable fixpoint must be UNIQUE and independent of `initial_ref_page`.
Two properties guarantee it and are asserted by the differential harness:
- Determinism of each round: sec 3 and sec 4 are total functions of `(doc, M_{r-1})`.
- Confluence: for a valid (accepted) document the iteration reaches the same
  reference-relevant `M` regardless of `initial_ref_page` in {1, a 2-digit seed}.
If confluence fails for a document, the document is INVALID (rerolled); the
semantics are NOT patched with a tie-break. If confluence fails for ALL seeds of
a construction, that is a semantics ambiguity and is resolved in THIS document
before any scaling.

## 7. What the two engines may and may not differ on

Engines A and B MUST agree on: the galley (line texts and order), the page cuts,
the realized map `M`, and the rendered pages -- byte-for-byte. They SHOULD differ
in architecture (A: iterative mutable cursor with an incremental candidate
scan and early-exit fixpoint loop; B: recursive/functional pagination with
independent violation predicates and a full-recompute fixpoint loop over a
different galley representation). Agreement across these two independent codebases
is the soundness evidence that these rules are unambiguous and canonical.
