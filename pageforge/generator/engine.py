"""Engine A (gold reference) -- iterative, mutable-cursor layout.

Implements docs/SEMANTICS.md incl. all families: BREAK+HYPH (sec 3/5c),
JUST (5c, render), WID/KEEP/ORPHAN with priority permutation (sec 4), keep-
together (5), FLOAT+FOOT (5b), FURN+HEAD (5c), XREF fixpoint (sec 6).
Engine B (interp_b.py) is an independent architecture; the differential requires
byte-for-byte agreement.

# PAGEFORGE_ORACLE_SENTINEL_7b1e9f4a
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

from . import pfcore as C
from .semconfig import SemConfig


@dataclass
class GLine:
    text: str
    para_id: str
    is_heading: bool
    para_first: bool
    para_last: bool
    para_len: int
    label: Optional[str]
    keep_together: bool
    fn_ids: tuple
    is_blank: bool = False


@dataclass
class FloatRec:
    anchor: int
    h: int
    zone: str
    art: tuple
    bid: str
    label: Optional[str]


@dataclass
class PagePlan:
    top: List[str] = field(default_factory=list)
    text: List[GLine] = field(default_factory=list)
    bot: List[str] = field(default_factory=list)
    foot: List[str] = field(default_factory=list)
    folio: bool = False
    s: int = 0
    e: int = 0


# ---- HYPH (SEMANTICS sec 5c) ------------------------------------------------

def _hyph_points(word: str, k: int):
    return [p for p in range(k, len(word), k) if p >= 2 and len(word) - p >= 2]


def _try_hyph(word: str, avail: int, cfg: SemConfig):
    """Largest valid fragment that fits `avail`. Returns (piece, remainder) or None."""
    if cfg.hyph != "EVERY_K":
        return None
    for p in reversed(_hyph_points(word, cfg.hyph_k)):
        frag, rem = word[:p], word[p:]
        if cfg.hyph_pos == "LEAD":
            if len(frag) <= avail:
                return (frag, "-" + rem)
        else:  # TRAIL
            if len(frag) + 1 <= avail:
                return (frag + "-", rem)
    return None


# ---- BREAK (SEMANTICS sec 3), token-aware + hyphenation ---------------------

def _break_tokens(block: C.Block, ref_pages: dict, cfg: SemConfig):
    W = cfg.W
    items = deque()
    for tok in block.tokens:
        t = C.token_text(tok, ref_pages)
        if isinstance(tok, C.FnMark):
            items.append((t, tok.fid, False))
        elif isinstance(tok, C.Ref):
            items.append((t, None, False))
        else:
            items.append((t, None, True))
    lines = []
    cur, curfn, width = [], [], 0
    while items:
        t, fid, is_word = items.popleft()
        wt = len(t)
        if not cur:
            if wt <= W:
                cur, curfn, width = [t], ([fid] if fid else []), wt
            else:
                h = _try_hyph(t, W, cfg) if is_word else None
                if h:
                    lines.append((h[0], ()))
                    items.appendleft((h[1], None, True))
                else:
                    cur, curfn, width = [t], ([fid] if fid else []), wt
        elif width + 1 + wt <= W:
            cur.append(t)
            if fid:
                curfn.append(fid)
            width += 1 + wt
        else:
            h = _try_hyph(t, W - width - 1, cfg) if is_word else None
            if h:
                cur.append(h[0])
                lines.append((" ".join(cur), tuple(curfn)))
                cur, curfn, width = [], [], 0
                items.appendleft((h[1], None, True))
            else:
                lines.append((" ".join(cur), tuple(curfn)))
                cur, curfn, width = [], [], 0
                items.appendleft((t, fid, is_word))
    if cur:
        lines.append((" ".join(cur), tuple(curfn)))
    if not lines:
        lines = [("", ())]
    return lines


def _blank_line() -> GLine:
    return GLine(text="", para_id="_blank", is_heading=False, para_first=False,
                 para_last=False, para_len=0, label=None, keep_together=False,
                 fn_ids=(), is_blank=True)


def _build_galley(document: C.Doc, ref_pages: dict, cfg: SemConfig):
    galley: List[GLine] = []
    floats: List[FloatRec] = []
    for block in document.blocks:
        if getattr(block, "kind", None) == "float":
            floats.append(FloatRec(anchor=len(galley), h=block.h, zone=block.zone,
                                   art=block.art, bid=block.bid, label=block.label))
            continue
        if block.is_heading:
            for _ in range(cfg.head_blank_before):
                galley.append(_blank_line())
        rows = _break_tokens(block, ref_pages, cfg)
        n = len(rows)
        for i, (txt, fn_ids) in enumerate(rows):
            galley.append(GLine(
                text=txt, para_id=block.bid, is_heading=block.is_heading,
                para_first=(i == 0), para_last=(i == n - 1), para_len=n,
                label=(block.label if i == 0 else None),
                keep_together=block.keep_together, fn_ids=fn_ids))
        if block.is_heading:
            for _ in range(cfg.head_blank_after):
                galley.append(_blank_line())
    return galley, floats


def _kt_spans(galley: List[GLine]):
    spans, i, N = [], 0, len(galley)
    while i < N:
        if galley[i].keep_together:
            j = i
            while j < N and galley[j].keep_together and galley[j].para_id == galley[i].para_id:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def _splits_kt(spans, e: int) -> bool:
    return any(a < e < b for (a, b) in spans)


def _violations_at(galley: List[GLine], e: int, N: int) -> dict:
    v = {"KEEP": 0, "WIDOW": 0, "ORPHAN": 0}
    last = galley[e - 1]
    if last.is_heading:
        v["KEEP"] = 1
    if e < N:
        nxt = galley[e]
        same = last.para_id == nxt.para_id
        if same and nxt.para_last and nxt.para_len >= 2:
            v["WIDOW"] = 1
        if same and last.para_first and last.para_len >= 2:
            v["ORPHAN"] = 1
    return v


def _key(v: dict, priority: tuple) -> tuple:
    return tuple(v[name] for name in priority)


def _anchors_in(galley: List[GLine], s: int, e: int):
    out = []
    for gl in galley[s:e]:
        out.extend(gl.fn_ids)
    return out


# ---- per-page resolution (SEMANTICS sec 5b + 5c) ----------------------------

def _layout_pass(galley: List[GLine], floats: List[FloatRec], notes: dict, cfg: SemConfig):
    N = len(galley)
    spans = _kt_spans(galley)
    fq = sorted(floats, key=lambda F: F.anchor)
    fidx = 0
    foot_cont: List[str] = []
    pages: List[PagePlan] = []
    s = 0
    while s < N:
        # STEP 0: drop leading head-blank rows at page top
        if cfg.head_blank_top_drop:
            while s < N and galley[s].is_blank:
                s += 1
            if s >= N:
                break
        pg = PagePlan(s=s)
        # STEP 1: floats
        reserve_top = reserve_bot = 0
        while fidx < len(fq) and fq[fidx].anchor <= s:
            F = fq[fidx]
            if reserve_top + reserve_bot + F.h + len(foot_cont) + 1 <= cfg.H:
                if F.zone == "T":
                    pg.top.extend(F.art)
                    reserve_top += F.h
                else:
                    pg.bot.extend(F.art)
                    reserve_bot += F.h
                fidx += 1
            else:
                break
        float_res = reserve_top + reserve_bot
        # STEP 1b: folio
        has_top_float = reserve_top > 0
        folio_present = (cfg.folio != "NONE" and
                         not (cfg.folio_suppress_topfloat and has_top_float))
        pg.folio = folio_present
        fixed_res = float_res + (1 if folio_present else 0)
        cont_res = len(foot_cont)
        # STEP 2: text end
        hi = min(s + (cfg.H - fixed_res - cont_res), N)
        best_e = best_key = None
        for e in range(s + 1, hi + 1):
            if _splits_kt(spans, e):
                continue
            anchors = _anchors_in(galley, s, e)
            if cfg.foot_reserve == "full":
                reserved = cont_res + sum(len(notes.get(fid, ())) for fid in anchors)
            else:
                reserved = cont_res + cfg.foot_min * len(anchors)
            if (e - s) + fixed_res + reserved > cfg.H:
                continue
            k = _key(_violations_at(galley, e, N), cfg.priority)
            if best_e is None or k < best_key or (k == best_key and e > best_e):
                best_e, best_key = e, k
        if best_e is None:
            raise ValueError("unlayoutable at s=%d" % s)
        e = best_e
        pg.e = e
        pg.text = galley[s:e]
        # STEP 3: footnotes
        text_count = e - s
        bottom = cfg.H - fixed_res - text_count
        queue = list(foot_cont)
        for fid in _anchors_in(galley, s, e):
            queue.extend(notes.get(fid, ()))
        pg.foot = queue[:bottom]
        foot_cont = queue[bottom:]
        pages.append(pg)
        s = e
    if foot_cont:
        raise ValueError("unlayoutable: undrained footnote continuation")
    if fidx < len(fq):
        raise ValueError("unlayoutable: undrained float queue")

    label_pages: dict = {}
    for pidx, pg in enumerate(pages, start=1):
        for gl in pg.text:
            if gl.label is not None and gl.label not in label_pages:
                label_pages[gl.label] = pidx
    _assign_float_labels(pages, floats, label_pages)
    return pages, label_pages


def _assign_float_labels(pages, floats, label_pages):
    by_first_row = {}
    for F in floats:
        if F.label is not None and F.art:
            by_first_row.setdefault(F.art[0], F.label)
    for pidx, pg in enumerate(pages, start=1):
        for row in pg.top + pg.bot:
            if row in by_first_row and by_first_row[row] not in label_pages:
                label_pages[by_first_row[row]] = pidx


# ---- JUST (SEMANTICS sec 5c) ------------------------------------------------

def _justify(text: str, cfg: SemConfig, j: int) -> str:
    words = text.split(" ")
    if len(words) < 2:
        return C.pad_line(text, cfg.W)
    natural = len(text)
    surplus = cfg.W - natural
    if surplus <= 0:
        return C.pad_line(text, cfg.W)
    gaps = len(words) - 1
    base, r = divmod(surplus, gaps)
    if cfg.just == "RIGHT_HEAVY":
        chosen = set(range(gaps - r, gaps))
    elif cfg.just == "PAGE_PARITY":
        chosen = set(range(r)) if j % 2 == 0 else set(range(gaps - r, gaps))
    else:  # LEFT
        chosen = set(range(r))
    out = words[0]
    for gi in range(gaps):
        out += " " * (1 + base + (1 if gi in chosen else 0)) + words[gi + 1]
    return out


def _render(pages: List[PagePlan], cfg: SemConfig) -> List[str]:
    out = []
    for pidx, pg in enumerate(pages, start=1):
        text_rows = []
        for j, gl in enumerate(pg.text):
            if gl.is_blank:
                text_rows.append(" " * cfg.W)
            elif gl.is_heading or gl.para_last:
                text_rows.append(C.pad_line(gl.text, cfg.W))
            else:
                text_rows.append(_justify(gl.text, cfg, j))
        folio_row = C.pad_line(cfg.folio_fmt % pidx, cfg.W) if pg.folio else None
        rows = []
        if folio_row is not None and cfg.folio == "TOP":
            rows.append(folio_row)
        rows += list(pg.top) + text_rows
        used = (len(rows) + len(pg.bot) + len(pg.foot) +
                (1 if (folio_row is not None and cfg.folio == "BOT") else 0))
        pad = cfg.H - used
        if pad < 0:
            raise ValueError("page overflow: used=%d H=%d" % (used, cfg.H))
        rows += [" " * cfg.W] * pad + list(pg.bot) + list(pg.foot)
        if folio_row is not None and cfg.folio == "BOT":
            rows.append(folio_row)
        out.append("\n".join(C.pad_line(r, cfg.W) for r in rows))
    return out


# ---- XREF fixpoint (SEMANTICS sec 6) ----------------------------------------

def _referenced_labels(document: C.Doc) -> set:
    out = set()
    for b in document.blocks:
        for tok in getattr(b, "tokens", ()):
            if isinstance(tok, C.Ref):
                out.add(tok.label)
    return out


def _all_labels(document: C.Doc) -> set:
    return {b.label for b in document.blocks if getattr(b, "label", None) is not None}


def _seed_map(document: C.Doc, init: int) -> dict:
    return {lab: init for lab in _all_labels(document)}


def layout_fixed(document: C.Doc, cfg: SemConfig, ref_pages: dict):
    M = _seed_map(document, cfg.initial_ref_page)
    M.update(ref_pages)
    galley, floats = _build_galley(document, M, cfg)
    pages, label_pages = _layout_pass(galley, floats, document.notes_map(), cfg)
    return _render(pages, cfg), label_pages


def layout(document: C.Doc, cfg: SemConfig, initial_ref_page: Optional[int] = None):
    init = cfg.initial_ref_page if initial_ref_page is None else initial_ref_page
    targets = _referenced_labels(document)
    M = _seed_map(document, init)
    notes = document.notes_map()
    prev_relevant = None
    for r in range(1, cfg.max_rounds + 1):
        galley, floats = _build_galley(document, M, cfg)
        pages, label_pages = _layout_pass(galley, floats, notes, cfg)
        newM = dict(M)
        newM.update(label_pages)
        relevant = {lab: newM.get(lab, init) for lab in targets}
        if relevant == prev_relevant:
            return _render(pages, cfg), label_pages, r
        prev_relevant = relevant
        M = newM
    raise ValueError("XREF fixpoint did not converge within max_rounds")


def waived_sites(document: C.Doc, cfg: SemConfig):
    """Sanctioned (waived) violations, DEDUPED BY PHYSICAL SITE. Each page has one
    bottom boundary = one physical site; the soft rules that fire there are either
    {KEEP} alone or a subset of {WIDOW,ORPHAN} on the same paragraph (a 2-line
    split trips both but is ONE event). Returns one entry per site:
    (page, para_id, fired_rules_in_priority_order). len(...) is the sanctioned-
    violation count the difficulty gate uses (no double-counting)."""
    _ps, final_map, _r = layout(document, cfg)
    M = _seed_map(document, cfg.initial_ref_page)
    M.update(final_map)
    galley, floats = _build_galley(document, M, cfg)
    pages, _lp = _layout_pass(galley, floats, document.notes_map(), cfg)
    N = len(galley)
    sites = []
    for pidx, pg in enumerate(pages, start=1):
        e = pg.e
        if e < N:
            v = _violations_at(galley, e, N)
            fired = tuple(r for r in cfg.priority if v[r])
            if fired:
                sites.append((pidx, galley[e - 1].para_id, fired))
    return sites
