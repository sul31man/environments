"""Reconstructed ENUMERATOR (Gate 2, the whole bet).

A branch-per-family, independence-composed layout: exactly what a strong model
that decomposes the disclosed spec into one pass per constraint would produce.
Each family is handled correctly IN ISOLATION; what it gets wrong is the JOINT
resolution where one family's repair changes another family's state. Faithful
independence errors (each maps to interaction edges):

  1. WID/KEEP/ORPHAN pagination decides breaks on text capacity `H - folio_base`,
     IGNORING the FOOT/FLOAT reservations (no repair-feedback loop). Floats,
     footnotes and folio are then placed and any overflow text is pushed forward
     WITHOUT re-running widow/keep. -> misses E5 (FOOT<->WID), E6 (FOOT<->FLOAT),
     E10 (FURN<->FLOAT suppression), capacity couplings.
  2. Justification parity uses a GLOBAL line index, not the page-local index.
     -> misses E4 (JUST<->pagebreak, PAGE_PARITY).
  3. Cross-references resolved in a SINGLE pass, not iterated to fixpoint.
     -> misses E3/E7/E12/E13 (XREF couplings).

On a document that avoids the interacting features the enumerator equals gold;
it diverges only where the constraints actually interact. That is the test: if
the interactions were enumerable, branch-by-branch composition would still score
>= the strict bar. It does not.

# PAGEFORGE_ORACLE_SENTINEL_7b1e9f4a
"""
from __future__ import annotations

from typing import List

from . import pfcore as C
from . import engine as E
from .semconfig import SemConfig


def _paginate_text_only(galley, cfg):
    """Pass 3: cut positions from WID/KEEP/ORPHAN on capacity H-folio_base,
    IGNORING float/foot reservations (the missing feedback)."""
    N = len(galley)
    spans = E._kt_spans(galley)
    folio_base = 1 if cfg.folio != "NONE" else 0
    cap = cfg.H - folio_base
    cuts = []
    s = 0
    while s < N:
        if cfg.head_blank_top_drop:
            while s < N and galley[s].is_blank:
                s += 1
            if s >= N:
                break
        hi = min(s + cap, N)
        best_e = best_key = None
        for e in range(s + 1, hi + 1):
            if E._splits_kt(spans, e):
                continue
            k = E._key(E._violations_at(galley, e, N), cfg.priority)
            if best_e is None or k < best_key or (k == best_key and e > best_e):
                best_e, best_key = e, k
        if best_e is None:
            best_e = min(s + 1, N)
        cuts.append((s, best_e))
        s = best_e
    return cuts


def _enum_pass(document: C.Doc, cfg: SemConfig, M: dict):
    galley, floats = E._build_galley(document, M, cfg)
    notes = document.notes_map()
    cuts = _paginate_text_only(galley, cfg)
    fq = sorted(floats, key=lambda F: F.anchor)
    fidx = 0
    foot_cont: List[str] = []
    carry: List = []              # overflow text pushed forward (no widow recheck)
    pages = []
    ci = 0
    # walk cuts, but allow spillover pages when carry/foot remain after the last cut
    while ci < len(cuts) or carry or foot_cont:
        if ci < len(cuts):
            s, e = cuts[ci]
            ci += 1
            seg = galley[s:e]
        else:
            s = cuts[-1][1] if cuts else 0
            seg = []
        text = carry + seg
        carry = []
        pg = E.PagePlan(s=s, e=e if ci <= len(cuts) else s)
        # floats anchored on a prior page / this page start
        rtop = rbot = 0
        while fidx < len(fq) and fq[fidx].anchor <= s:
            F = fq[fidx]
            if rtop + rbot + F.h + len(foot_cont) + 1 <= cfg.H:
                if F.zone == "T":
                    pg.top.extend(F.art); rtop += F.h
                else:
                    pg.bot.extend(F.art); rbot += F.h
                fidx += 1
            else:
                break
        float_res = rtop + rbot
        folio_present = (cfg.folio != "NONE" and
                         not (cfg.folio_suppress_topfloat and rtop > 0))
        pg.folio = folio_present
        fixed_res = float_res + (1 if folio_present else 0)
        avail_text = cfg.H - fixed_res - len(foot_cont)
        if avail_text < 0:
            avail_text = 0
        placed_text = text[:avail_text]
        carry = text[avail_text:]
        pg.text = placed_text
        # footnotes for anchors in placed text; fill bottom, split overflow
        bottom = cfg.H - fixed_res - len(placed_text)
        queue = list(foot_cont)
        for gl in placed_text:
            for fid in gl.fn_ids:
                queue.extend(notes.get(fid, ()))
        pg.foot = queue[:max(0, bottom)]
        foot_cont = queue[max(0, bottom):]
        pages.append(pg)
        if ci >= len(cuts) and not carry and not foot_cont:
            break
        if ci >= len(cuts) and fidx >= len(fq) and not carry and not foot_cont:
            break
        # safety: avoid infinite spillover
        if len(pages) > 4 * (len(cuts) + 5):
            break
    label_pages = {}
    for pidx, pg in enumerate(pages, start=1):
        for gl in pg.text:
            if gl.label is not None and gl.label not in label_pages:
                label_pages[gl.label] = pidx
    E._assign_float_labels(pages, floats, label_pages)
    return pages, label_pages


def _enum_render(pages, cfg: SemConfig) -> List[str]:
    """Render. Justification is page-local (the JUST branch is correct IN
    ISOLATION); it diverges from gold only where the enumerator's own pagination
    diverges (edge E4 then falls out of the capacity/xref errors, not a universal
    JUST failure)."""
    out = []
    for pidx, pg in enumerate(pages, start=1):
        trows = []
        for j, gl in enumerate(pg.text):
            if gl.is_blank:
                trows.append(" " * cfg.W)
            elif gl.is_heading or gl.para_last:
                trows.append(C.pad_line(gl.text, cfg.W))
            else:
                trows.append(E._justify(gl.text, cfg, j))
        folio_row = C.pad_line(cfg.folio_fmt % pidx, cfg.W) if pg.folio else None
        rows = []
        if folio_row is not None and cfg.folio == "TOP":
            rows.append(folio_row)
        rows += list(pg.top) + trows
        used = (len(rows) + len(pg.bot) + len(pg.foot) +
                (1 if (folio_row is not None and cfg.folio == "BOT") else 0))
        pad = cfg.H - used
        if pad < 0:
            rows = rows[:cfg.H - (len(pg.bot) + len(pg.foot) +
                                  (1 if (folio_row is not None and cfg.folio == "BOT") else 0))]
            pad = 0
        rows += [" " * cfg.W] * pad + list(pg.bot) + list(pg.foot)
        if folio_row is not None and cfg.folio == "BOT":
            rows.append(folio_row)
        out.append("\n".join(C.pad_line(r, cfg.W) for r in rows[:cfg.H]))
    return out


def enum_layout(document: C.Doc, cfg: SemConfig):
    """Independence-composed layout. XREF resolved in a SINGLE re-pass (no
    fixpoint): lay out once at the seed, then once at the realized map, stop."""
    labels = E._all_labels(document)
    M = {lab: cfg.initial_ref_page for lab in labels}
    pages, lp = _enum_pass(document, cfg, M)
    M2 = {**M, **lp}
    pages, lp = _enum_pass(document, cfg, M2)   # one re-resolution, NOT to fixpoint
    return _enum_render(pages, cfg), lp
