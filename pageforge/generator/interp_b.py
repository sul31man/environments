"""Engine B (differential oracle) -- recursive/functional layout.

Same semantics as engine.py (docs/SEMANTICS.md, all families) via a different
architecture: dict galley, recursive pagination, separate predicates, min()
selection, full-recompute fixpoint. Byte-for-byte agreement is the soundness
evidence.

# PAGEFORGE_ORACLE_SENTINEL_7b1e9f4a
"""
from __future__ import annotations

from typing import List, Optional

from . import pfcore as C
from .semconfig import SemConfig


# ---- HYPH -------------------------------------------------------------------

def _points(word, k):
    return [p for p in range(k, len(word), k) if p >= 2 and len(word) - p >= 2]


def _hyph(word, avail, cfg):
    if cfg.hyph != "EVERY_K":
        return None
    for p in sorted(_points(word, cfg.hyph_k), reverse=True):
        frag, rem = word[:p], word[p:]
        if cfg.hyph_pos == "LEAD":
            if len(frag) <= avail:
                return (frag, "-" + rem)
        else:
            if len(frag) + 1 <= avail:
                return (frag + "-", rem)
    return None


# ---- BREAK (token-aware + hyphenation) --------------------------------------

def _break(block, ref_pages, cfg):
    W = cfg.W
    stack = []  # process front-to-back; use list as reversed queue
    seq = []
    for tok in block.tokens:
        t = C.token_text(tok, ref_pages)
        if isinstance(tok, C.FnMark):
            seq.append((t, tok.fid, False))
        elif isinstance(tok, C.Ref):
            seq.append((t, None, False))
        else:
            seq.append((t, None, True))
    stack = list(reversed(seq))
    out, cur, fns, width = [], [], [], 0
    while stack:
        t, fid, is_word = stack.pop()
        wt = len(t)
        if not cur:
            if wt <= W:
                cur, fns, width = [t], ([fid] if fid else []), wt
            else:
                h = _hyph(t, W, cfg) if is_word else None
                if h:
                    out.append((h[0], ()))
                    stack.append((h[1], None, True))
                else:
                    cur, fns, width = [t], ([fid] if fid else []), wt
        elif width + 1 + wt <= W:
            cur.append(t)
            if fid:
                fns.append(fid)
            width += 1 + wt
        else:
            h = _hyph(t, W - width - 1, cfg) if is_word else None
            if h:
                cur.append(h[0])
                out.append((" ".join(cur), tuple(fns)))
                cur, fns, width = [], [], 0
                stack.append((h[1], None, True))
            else:
                out.append((" ".join(cur), tuple(fns)))
                cur, fns, width = [], [], 0
                stack.append((t, fid, is_word))
    if cur:
        out.append((" ".join(cur), tuple(fns)))
    return out or [("", ())]


def _blank():
    return {"t": "", "blk": "_blank", "head": False, "first": False, "last": False,
            "len": 0, "lab": None, "kt": False, "fn": (), "blank": True}


def _galley(document, ref_pages, cfg):
    g, floats = [], []
    for b in document.blocks:
        if getattr(b, "kind", None) == "float":
            floats.append({"anchor": len(g), "h": b.h, "zone": b.zone,
                           "art": b.art, "blk": b.bid, "lab": b.label})
            continue
        if b.is_heading:
            for _ in range(cfg.head_blank_before):
                g.append(_blank())
        rows = _break(b, ref_pages, cfg)
        m = len(rows)
        for i, (txt, fns) in enumerate(rows):
            g.append({"t": txt, "blk": b.bid, "head": b.is_heading,
                      "first": i == 0, "last": i == m - 1, "len": m,
                      "lab": b.label if i == 0 else None,
                      "kt": b.keep_together, "fn": fns, "blank": False})
        if b.is_heading:
            for _ in range(cfg.head_blank_after):
                g.append(_blank())
    return g, floats


def _kt_spans(g):
    spans, i, N = [], 0, len(g)
    while i < N:
        if g[i]["kt"]:
            j = i
            while j < N and g[j]["kt"] and g[j]["blk"] == g[i]["blk"]:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def _valid_kt(spans, e):
    return not any(a < e < b for (a, b) in spans)


def _viol(g, e, N):
    v = {"KEEP": 0, "WIDOW": 0, "ORPHAN": 0}
    last = g[e - 1]
    if last["head"]:
        v["KEEP"] = 1
    if e < N:
        nxt = g[e]
        same = last["blk"] == nxt["blk"]
        if same and nxt["last"] and nxt["len"] >= 2:
            v["WIDOW"] = 1
        if same and last["first"] and last["len"] >= 2:
            v["ORPHAN"] = 1
    return v


def _vkey(g, e, N, priority):
    v = _viol(g, e, N)
    return tuple(v[name] for name in priority)


def _fn_between(g, s, e):
    ids = []
    for gl in g[s:e]:
        ids.extend(gl["fn"])
    return ids


# ---- per-page resolution (recursive) ----------------------------------------

def _pages(g, floats, notes, cfg):
    N = len(g)
    spans = _kt_spans(g)
    fq = sorted(floats, key=lambda F: F["anchor"])

    def go(s, fi, foot_cont, acc):
        if cfg.head_blank_top_drop:
            while s < N and g[s]["blank"]:
                s += 1
        if s >= N:
            if foot_cont:
                raise ValueError("unlayoutable: undrained footnote continuation")
            if fi < len(fq):
                raise ValueError("unlayoutable: undrained float queue")
            return acc
        top, bot, rtop, rbot = [], [], 0, 0
        while fi < len(fq) and fq[fi]["anchor"] <= s:
            F = fq[fi]
            if rtop + rbot + F["h"] + len(foot_cont) + 1 <= cfg.H:
                if F["zone"] == "T":
                    top = top + list(F["art"]); rtop += F["h"]
                else:
                    bot = bot + list(F["art"]); rbot += F["h"]
                fi += 1
            else:
                break
        float_res = rtop + rbot
        folio = (cfg.folio != "NONE" and
                 not (cfg.folio_suppress_topfloat and rtop > 0))
        fixed_res = float_res + (1 if folio else 0)
        cont_res = len(foot_cont)
        hi = min(s + (cfg.H - fixed_res - cont_res), N)
        cands = []
        for e in range(s + 1, hi + 1):
            if not _valid_kt(spans, e):
                continue
            anchors = _fn_between(g, s, e)
            if cfg.foot_reserve == "full":
                reserved = cont_res + sum(len(notes.get(fid, ())) for fid in anchors)
            else:
                reserved = cont_res + cfg.foot_min * len(anchors)
            if (e - s) + fixed_res + reserved > cfg.H:
                continue
            cands.append((_vkey(g, e, N, cfg.priority), -e))
        if not cands:
            raise ValueError("unlayoutable at s=%d" % s)
        e = -min(cands)[1]
        text_count = e - s
        bottom = cfg.H - fixed_res - text_count
        queue = list(foot_cont)
        for fid in _fn_between(g, s, e):
            queue.extend(notes.get(fid, ()))
        page = {"top": top, "text": g[s:e], "bot": bot, "foot": queue[:bottom],
                "folio": folio, "s": s, "e": e}
        return go(e, fi, queue[bottom:], acc + [page])

    return go(0, 0, [], [])


def _labels(g_pages, floats):
    lp = {}
    for pidx, pg in enumerate(g_pages, start=1):
        for gl in pg["text"]:
            if gl["lab"] is not None and gl["lab"] not in lp:
                lp[gl["lab"]] = pidx
    first_row = {}
    for F in floats:
        if F["lab"] is not None and F["art"]:
            first_row.setdefault(F["art"][0], F["lab"])
    for pidx, pg in enumerate(g_pages, start=1):
        for row in pg["top"] + pg["bot"]:
            if row in first_row and first_row[row] not in lp:
                lp[first_row[row]] = pidx
    return lp


# ---- JUST -------------------------------------------------------------------

def _justify(text, cfg, j):
    words = text.split(" ")
    if len(words) < 2:
        return C.pad_line(text, cfg.W)
    surplus = cfg.W - len(text)
    if surplus <= 0:
        return C.pad_line(text, cfg.W)
    gaps = len(words) - 1
    base, r = divmod(surplus, gaps)
    if cfg.just == "RIGHT_HEAVY":
        chosen = set(range(gaps - r, gaps))
    elif cfg.just == "PAGE_PARITY":
        chosen = set(range(r)) if j % 2 == 0 else set(range(gaps - r, gaps))
    else:
        chosen = set(range(r))
    parts = [words[0]]
    for gi in range(gaps):
        parts.append(" " * (1 + base + (1 if gi in chosen else 0)))
        parts.append(words[gi + 1])
    return "".join(parts)


def _render(pages, cfg):
    out = []
    for pidx, pg in enumerate(pages, start=1):
        trows = []
        for j, gl in enumerate(pg["text"]):
            if gl["blank"]:
                trows.append(" " * cfg.W)
            elif gl["head"] or gl["last"]:
                trows.append(C.pad_line(gl["t"], cfg.W))
            else:
                trows.append(_justify(gl["t"], cfg, j))
        folio_row = C.pad_line(cfg.folio_fmt % pidx, cfg.W) if pg["folio"] else None
        rows = []
        if folio_row is not None and cfg.folio == "TOP":
            rows.append(folio_row)
        rows += list(pg["top"]) + trows
        used = (len(rows) + len(pg["bot"]) + len(pg["foot"]) +
                (1 if (folio_row is not None and cfg.folio == "BOT") else 0))
        pad = cfg.H - used
        if pad < 0:
            raise ValueError("page overflow")
        rows += [" " * cfg.W] * pad + list(pg["bot"]) + list(pg["foot"])
        if folio_row is not None and cfg.folio == "BOT":
            rows.append(folio_row)
        out.append("\n".join(C.pad_line(r, cfg.W) for r in rows))
    return out


# ---- XREF fixpoint ----------------------------------------------------------

def _refd(document):
    return {t.label for b in document.blocks for t in getattr(b, "tokens", ())
            if isinstance(t, C.Ref)}


def _all_labels(document):
    return {b.label for b in document.blocks if getattr(b, "label", None) is not None}


def layout_fixed(document, cfg, ref_pages):
    M = {lab: cfg.initial_ref_page for lab in _all_labels(document)}
    M.update(ref_pages)
    g, floats = _galley(document, M, cfg)
    pages = _pages(g, floats, document.notes_map(), cfg)
    return _render(pages, cfg), _labels(pages, floats)


def layout(document, cfg, initial_ref_page=None):
    init = cfg.initial_ref_page if initial_ref_page is None else initial_ref_page
    targets = _refd(document)
    notes = document.notes_map()
    M = {lab: init for lab in _all_labels(document)}
    history = None
    for r in range(1, cfg.max_rounds + 1):
        g, floats = _galley(document, M, cfg)
        pages = _pages(g, floats, notes, cfg)
        lp = _labels(pages, floats)
        nextM = {**M, **lp}
        rel = {lab: nextM.get(lab, init) for lab in targets}
        if rel == history:
            return _render(pages, cfg), lp, r
        history = rel
        M = nextM
    raise ValueError("XREF fixpoint did not converge within max_rounds (engine B)")


def waived_sites(document, cfg):
    _ps, final_map, _r = layout(document, cfg)
    M = {lab: cfg.initial_ref_page for lab in _all_labels(document)}
    M.update(final_map)
    g, floats = _galley(document, M, cfg)
    pages = _pages(g, floats, document.notes_map(), cfg)
    N = len(g)
    sites = []
    for pidx, pg in enumerate(pages, start=1):
        e = pg["e"]
        if e < N:
            v = _viol(g, e, N)
            fired = tuple(r for r in cfg.priority if v[r])
            if fired:
                sites.append((pidx, g[e - 1]["blk"], fired))
    return sites
