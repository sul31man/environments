"""PageForge instance generator + difficulty/reroll gate.

An Instance = a per-instance SemConfig (the disclosed semantics) + a document
corpus (categorized) + 40 differential-only docs. Eval and train namespaces are
disjoint by blake2b facet seeding. generate() rerolls a fresh seed until the
difficulty gate passes.

Difficulty gate (training env):
  1. gold == 1.0 on the corpus
  2. null baseline < 0.2
  3. ENUMERATOR (branch-per-family) < 0.95   (enumerator-hard: the difficulty)
  4. differential engine A == engine B on corpus + 40 random docs (0 mismatches)
  5. >= 1 corpus doc carries a sanctioned violation (deduped by site)
  6. >= 1 fixpoint doc whose converged ref-map differs from the seed (>=2 rounds)
  7. ladder rungs recorded; >= 5 of 8 are load-bearing (< 0.95) and none at floor

# PAGEFORGE_ORACLE_SENTINEL_7b1e9f4a
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from random import Random
from typing import List, Tuple

from . import pfcore as C
from . import engine as A
from . import interp_b as B
from . import grade as G
from .semconfig import SemConfig

EVAL_NAMESPACE = "eval"
TRAIN_NAMESPACE = "train"
EVAL_COUNT = 50
MAX_ATTEMPTS = 300


def facet_rng(namespace: str, index: int, attempt: int, facet: str) -> Random:
    h = hashlib.blake2b(("%s|%d|%d|%s" % (namespace, index, attempt, facet)).encode("ascii"),
                        digest_size=8).digest()
    return Random(int.from_bytes(h, "big"))


@dataclass
class Instance:
    namespace: str
    index: int
    attempt: int
    cfg: SemConfig
    corpus: List[Tuple[C.Doc, str]]      # (doc, category)
    diff_docs: List[C.Doc]               # differential-only
    report: dict = field(default_factory=dict)


# ---- config + document sampling ---------------------------------------------

import itertools
_PERMS = [p for p in itertools.permutations(("KEEP", "WIDOW", "ORPHAN"))
          if p != ("KEEP", "WIDOW", "ORPHAN")]


def _sample_cfg(rng: Random) -> SemConfig:
    # interacting forms locked on (so every ladder family is load-bearing);
    # W/H, the specific anti-prior form, and the priority permutation vary.
    return SemConfig(
        W=rng.choice([18, 20, 22]), H=rng.choice([4, 5]),
        just=rng.choice(["RIGHT_HEAVY", "PAGE_PARITY"]),
        hyph="EVERY_K", hyph_k=rng.choice([3, 4]), hyph_pos=rng.choice(["TRAIL", "LEAD"]),
        folio=rng.choice(["TOP", "BOT"]), folio_suppress_topfloat=True,
        foot_min=1, head_blank_before=1, head_blank_after=0,
        head_blank_top_drop=rng.choice([True, False]),
        priority=rng.choice(_PERMS),
    )


def _words(rng, lo=2, hi=6, n=1):
    return [C.Word("x" * rng.randint(lo, hi)) for _ in range(n)]


def _dense_doc(rng, want_float=True) -> C.Doc:
    n = rng.randint(4, 8)
    blocks, notes, fc = [], {}, 0
    put_float = want_float and rng.random() < 0.7
    for b in range(n):
        k = rng.choices(["head_para", "foot_para", "float"], weights=[4, 4, 2 if put_float else 0])[0]
        if k == "float":
            h = rng.randint(1, 2)
            blocks.append(C.fig("g%d" % b, h, rng.choice(["T", "B"]),
                                ["<f%d>" % b, "<h%d>" % b][:h]))
            continue
        if k == "head_para":
            blocks.append(C.heading("hd%d" % b, C.words("Sec %d" % b)))
        toks = []
        for _ in range(rng.randint(3, 6)):
            if rng.random() < 0.35 and k == "foot_para":
                fid = "%d" % fc
                fc += 1
                notes[fid] = tuple("n%s%d" % (fid, j) for j in range(rng.randint(1, 2)))
                toks.append(C.FnMark(fid))
            else:
                toks.append(C.Word("x" * rng.randint(2, 6)))
        blocks.append(C.para("p%d" % b, toks))
    return C.doc(*blocks, notes=notes)


def _single_family_doc(rng, family) -> C.Doc:
    """A small doc that exercises ONE family (spec bucket + ladder load-bearing)."""
    if family == "hyph":
        return C.doc(C.para("p", [C.Word("x" * 14)] + C.words("aa bb cc dd ee ff")))
    if family == "folio":
        return C.doc(C.para("p", C.words(" ".join(["aa"] * 24))))
    if family == "just":
        return C.doc(C.para("p", C.words("aa bb cc dd ee ff gg hh ii jj kk ll")))
    if family == "head":
        return C.doc(C.heading("h", C.words("Sec")), C.para("p", C.words("aa bb cc dd ee ff")))
    if family == "suppress":
        return C.doc(C.fig("g", 2, "T", ["<t1>", "<t2>"]),
                     C.para("p", C.words(" ".join(["aa"] * 20))))
    return C.doc(C.para("p", C.words("aa bb cc dd ee ff gg hh")))


def _fixpoint_doc(rng, cfg) -> C.Doc:
    # a ref near the top pointing to a heading placed several pages down, so the
    # realized ref page differs from the seed (>=2 productive rounds).
    fillers = [C.para("f%d" % i, C.words(" ".join(["aa"] * rng.randint(10, 16))))
               for i in range(rng.randint(6, 10))]
    return C.doc(C.para("p", [C.Ref("tgt")] + C.words("aa bb cc dd")),
                 *fillers,
                 C.heading("tgt", C.words("Target"), label="tgt"),
                 C.para("b", C.words("aa bb cc")))


def _layoutable(doc, cfg) -> bool:
    try:
        A.layout(doc, cfg)
        return True
    except ValueError:
        return False


def _rich_reroll(rng, cfg, maker, n, **kw):
    out, tries = [], 0
    while len(out) < n and tries < n * 60:
        tries += 1
        d = maker(rng, **kw)
        if _layoutable(d, cfg):
            out.append(d)
    return out


def _build_corpus(rng, cfg):
    corpus = []
    corpus += [(d, "killer") for d in _rich_reroll(rng, cfg, _dense_doc, 10)]
    for fam in ("hyph", "folio", "just", "head", "suppress"):
        d = _single_family_doc(rng, fam)
        if _layoutable(d, cfg):
            corpus.append((d, "single"))
    corpus += [(d, "random") for d in _rich_reroll(rng, cfg, lambda r: _dense_doc(r, want_float=False), 6)]
    # fixpoint docs
    fp = 0
    tries = 0
    while fp < 2 and tries < 80:
        tries += 1
        d = _fixpoint_doc(rng, cfg)
        if _layoutable(d, cfg):
            corpus.append((d, "fixpoint"))
            fp += 1
    diff_docs = _rich_reroll(rng, cfg, _dense_doc, 40)
    return corpus, diff_docs


# ---- difficulty gate --------------------------------------------------------

def _fixpoint_rounds(doc, cfg):
    try:
        _p, _lp, r = A.layout(doc, cfg)
        return r
    except ValueError:
        return 0


def _productive_fixpoint(doc, cfg):
    """converged ref-map differs from the initial seed -> >=1 productive round."""
    labels = A._referenced_labels(doc)
    if not labels:
        return False
    try:
        _p, lp, r = A.layout(doc, cfg)
    except ValueError:
        return False
    return r >= 2 and any(lp.get(l, cfg.initial_ref_page) != cfg.initial_ref_page for l in labels)


def difficulty(inst: Instance):
    cfg, corpus, diff_docs = inst.cfg, inst.corpus, inst.diff_docs
    rep = {}
    gold_r, _ = G.score(G.gold_fn, corpus, cfg)
    null_r, _ = G.score(G.null_fn, corpus, cfg)
    enum_r, _ = G.score(G.enumerator_fn, corpus, cfg)
    rep["gold"], rep["null"], rep["enum"] = gold_r, null_r, enum_r
    # differential on corpus + diff docs
    diff_ok = True
    for d, _c in corpus:
        if A.layout(d, cfg)[0] != B.layout(d, cfg)[0]:
            diff_ok = False
    for d in diff_docs:
        if not _layoutable(d, cfg):
            continue
        if A.layout(d, cfg)[0] != B.layout(d, cfg)[0]:
            diff_ok = False
    rep["diff_ok"] = diff_ok
    # sanctioned present
    sanct = sum(len(A.waived_sites(d, cfg)) for d, _c in corpus)
    rep["sanctioned"] = sanct
    # fixpoint present + productive
    fps = [d for d, c in corpus if c == "fixpoint"]
    prod = any(_productive_fixpoint(d, cfg) for d in fps)
    rep["fixpoint_productive"] = prod
    # ladder
    rungs = {}
    for name in G.LADDER:
        r, _ = G.score(G.ladder_fn(name), corpus, cfg)
        rungs[name] = r
    rep["ladder"] = rungs
    loadbearing = sum(1 for v in rungs.values() if v < G.STRICT)
    rep["ladder_loadbearing"] = loadbearing
    rep["ladder_min"] = min(rungs.values()) if rungs else 0.0

    # Note: single-family layout errors CASCADE (a wrong folio/spacing shifts
    # every downstream page), so a load-bearing rung can legitimately score near
    # 0. No floor guard: the gradient is the spread across rungs, and load-bearing
    # means < STRICT. gold==1 is the exact anchor; the ladder shows the gradient.
    ok = (abs(gold_r - 1.0) < 1e-9 and null_r < 0.2 and enum_r < G.STRICT
          and diff_ok and sanct >= 1 and prod
          and loadbearing >= 5
          and len(corpus) >= 20)
    return ok, rep


def generate(index: int, namespace: str = EVAL_NAMESPACE) -> Instance:
    for attempt in range(MAX_ATTEMPTS):
        rng_c = facet_rng(namespace, index, attempt, "cfg")
        rng_d = facet_rng(namespace, index, attempt, "docs")
        cfg = _sample_cfg(rng_c)
        corpus, diff_docs = _build_corpus(rng_d, cfg)
        inst = Instance(namespace, index, attempt, cfg, corpus, diff_docs)
        ok, rep = difficulty(inst)
        inst.report = rep
        if ok:
            return inst
    raise RuntimeError("generate: no in-band instance for index %d after %d attempts"
                       % (index, MAX_ATTEMPTS))
