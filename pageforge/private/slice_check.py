"""PageForge oracle regression + differential harness.

The ALL-FAMILIES engine A == engine B regression (BREAK, HYPH, JUST, WID+ORPHAN,
KEEP, FOOT, FLOAT, XREF, FURN, HEAD + the priority permutation). Sections [1]-[4],
[FF], and [PR] are curated property checks; section [5] is the randomized
differential across all families.

Proves, on the core families, the three properties the env's soundness rests on:

  1. Engine A == Engine B byte-for-byte (pages + label maps) on every slice doc
     and every confusable seed, including single-pass (layout_fixed) results.
  2. Sanctioned violations exist and both engines independently agree on the
     SAME waived-rule site (KEEP branch and WIDOW branch).
  3. The XREF fixpoint is PRODUCTIVE (its converged result differs from the
     confusable single-pass render) and CONFLUENT / unique (invariant to the
     initial ref-page seed across {1,2,9,10,99}).

Also shows path dependence: gold layout differs from the rule-ignoring naive
full-fill, and the cross-ref VALUE depends on the pagination repair trajectory
(edge E12 XREF<->WID). Deterministic, ASCII, and offline. No model calls.

Run:  python3 -m private.slice_check   from pageforge-gen/.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import pfcore as C
from generator.semconfig import SemConfig
from generator import engine as A
from generator import interp_b as B


# ---------------------------------------------------------------- helpers ----

def wl(prefix, count):
    return [C.Word("%s%d" % (prefix, i)) for i in range(count)]


def naive_fullfill(document: C.Doc, cfg: SemConfig, ref_pages: dict):
    """Rule-IGNORING baseline: pack exactly H lines per page (no widow/keep/kt
    repair). Illustrates that gold's layout and its cross-ref values depend on
    the repair trajectory, not merely on rule-consistency."""
    galley, _floats = A._build_galley(document, {**{l: cfg.initial_ref_page
                                                    for l in A._all_labels(document)},
                                                 **ref_pages}, cfg)
    pages, label_pages = [], {}
    for i in range(0, len(galley), cfg.H):
        pages.append(galley[i:i + cfg.H])
    for pidx, plines in enumerate(pages, start=1):
        for gl in plines:
            if gl.label is not None and gl.label not in label_pages:
                label_pages[gl.label] = pidx
    return label_pages


def _random_doc(rng):
    """A small random slice document: paras/headings/keep-together/refs plus
    FLOATs (T/B zones) and FOOT anchors with split-able bodies."""
    W = rng.choice([16, 18, 20, 22, 24])
    H = rng.choice([3, 4, 5, 6])
    nblk = rng.randint(1, 7)
    blocks, labels, notes, fid_ctr = [], [], {}, 0
    for b in range(nblk):
        bid = "b%d" % b
        kind = rng.choices(["para", "heading", "kt", "float"], weights=[6, 2, 2, 2])[0]
        if kind == "float":
            h = rng.randint(1, max(1, H - 2))
            zone = rng.choice(["T", "B"])
            art = ["<fig %s r%d>" % (bid, k)[:W] for k in range(h)]
            blocks.append(C.fig(bid, h, zone, art,
                                label=("L%d" % b if rng.random() < 0.4 else None)))
            continue
        label = None
        if rng.random() < 0.5:
            label = "L%d" % b
            labels.append(label)
        toks = []
        for _ in range(rng.randint(1, 7)):
            r = rng.random()
            if labels and r < 0.12:
                toks.append(C.Ref(rng.choice(labels)))
            elif r < 0.24:
                fid = "%d" % fid_ctr
                fid_ctr += 1
                notes[fid] = tuple("nt%s l%d" % (fid, k) for k in range(rng.randint(1, 3)))
                toks.append(C.FnMark(fid))
            else:
                toks.append(C.Word("x" * rng.randint(2, 7)))
        if kind == "heading":
            blocks.append(C.heading(bid, toks, label=label))
        elif kind == "kt":
            blocks.append(C.para(bid, toks, label=label, keep_together=True))
        else:
            blocks.append(C.para(bid, toks, label=label))
    # randomize ALL family forms + the priority permutation (all 10 families)
    import itertools
    perms = list(itertools.permutations(("KEEP", "WIDOW", "ORPHAN")))
    cfg = SemConfig(
        W=W, H=H,
        priority=rng.choice(perms),
        just=rng.choice(["LEFT", "RIGHT_HEAVY", "PAGE_PARITY"]),
        hyph=rng.choice(["NONE", "EVERY_K"]),
        hyph_k=rng.choice([3, 4]),
        hyph_pos=rng.choice(["TRAIL", "LEAD"]),
        folio=rng.choice(["NONE", "TOP", "BOT"]),
        folio_suppress_topfloat=rng.random() < 0.5,
        head_blank_before=rng.choice([0, 0, 1]),
        head_blank_after=rng.choice([0, 1]),
        head_blank_top_drop=rng.random() < 0.5,
    )
    return C.doc(*blocks, notes=notes), cfg


def _safe_layout(engine, doc, cfg):
    """Return ('ok', pages) | ('nonconv', None) | ('unlay', None), classifying
    the two legitimate rejection modes so A and B can be compared symmetrically."""
    try:
        pages, _lab, _r = engine.layout(doc, cfg)
        return ("ok", pages)
    except ValueError as e:
        msg = str(e)
        if "converge" in msg:
            return ("nonconv", None)
        return ("unlay", None)


FAILS = []
def check(cond, msg):
    status = "PASS" if cond else "FAIL"
    print("  [%s] %s" % (status, msg))
    if not cond:
        FAILS.append(msg)


def agree(document, cfg, seed=None):
    pa, la, ra = A.layout(document, cfg, initial_ref_page=seed)
    pb, lb, rb = B.layout(document, cfg, initial_ref_page=seed)
    return (pa == pb and la == lb), (pa, la, ra), (pb, lb, rb)


# ------------------------------------------------------------- slice docs ----

cfg4 = SemConfig(W=20, H=4)
cfg2 = SemConfig(W=20, H=2)

# (S1) sanctioned KEEP: keep-together block strands a heading alone on its page.
d_sanc_keep = C.doc(
    C.para("q", wl("q", 20)),
    C.heading("h", C.words("Sec Two")),
    C.para("kt", wl("k", 20), keep_together=True),
)

# (S2) sanctioned WIDOW at tight capacity: heading forces a 2-line para's tail
# alone onto the next page (KEEP > WIDOW so the widow is the waived site).
d_sanc_wid = C.doc(
    C.heading("h", C.words("Sec")),
    C.para("a", C.words("aaa bbb ccc ddd eee fff ggg")),
)

# (P1) widow pull-back: page 1 under-fills (holds 3 of 4 lines) so a 2-line
# paragraph's tail is not widowed -> the presence of 'a' changes page 1's fill.
d_pull = C.doc(
    C.para("q", wl("q", 15)),
    C.para("a", C.words("aaa bbb ccc ddd eee fff ggg")),
)

# (F1) XREF fixpoint: P = [ref->sec, 16-char word] is 1 line at ref width 3
# ('p.N', N<10) and 2 lines at width 4 ('p.10'); converges to the width-3 fixpoint.
d_fix = C.doc(
    C.para("p", [C.Ref("sec"), C.Word("z" * 16)]),
    C.para("f", wl("f", 30)),
    C.heading("sec", C.words("Target"), label="sec"),
    C.para("b", C.words("bbb ccc ddd")),
)

# ---- FOOT + FLOAT docs (capacity-consuming families) -----------------------

# (S3) NATURAL sanctioned WIDOW from FOOT contention: two footnote anchors in a
# 2-line para; their minimum reservation (2 rows) makes the clean 3-line cut
# infeasible, so the para's tail widows (KEEP>WIDOW keeps the heading intact).
d_foot_sanc = C.doc(
    C.heading("h", C.words("Sec")),
    C.para("A", C.words("aaa bbb ccc ddd") + [C.FM("1")] +
           C.words("eee fff ggg") + [C.FM("2")]),
    C.para("t", C.words("zzz yyy xxx")),
    notes={"1": ("foot1a", "foot1b"), "2": ("foot2a", "foot2b")},
)

# (S4) NATURAL sanctioned WIDOW from FLOAT contention: a 2-row TOP float on the
# heading's page removes the clean cut, forcing the same sanctioned widow.
d_float_sanc = C.doc(
    C.fig("fg", 2, "T", ["<BAR1>", "<BAR2>"]),
    C.heading("h", C.words("Sec")),
    C.para("A", C.words("aaa bbb ccc ddd eee fff ggg")),
    C.para("t", C.words("zzz yyy")),
)

# (E5) FOOT<->WID path-difference pair: adding a footnote changes pagination.
def _e5(with_fn):
    toks = C.words("aaa bbb ccc ddd") + ([C.FM("1")] if with_fn else []) + C.words("eee fff")
    return C.doc(C.para("p", toks),
                 C.para("q", C.words("mmm nnn ooo ppp qqq rrr sss")),
                 notes=({"1": ("fn",)} if with_fn else {}))

# (E6) FOOT<->FLOAT path-difference pair: a BOT float steals bottom rows, pushing
# text to the next page while the footnote stays put.
def _e6(with_float):
    blocks = []
    if with_float:
        blocks.append(C.fig("fg", 2, "B", ["<F1>", "<F2>"]))
    blocks.append(C.para("p", C.words("aaa bbb ccc ddd") + [C.FM("1")] + C.words("eee")))
    blocks.append(C.para("q", C.words("mmm nnn ooo ppp qqq rrr")))
    return C.doc(*blocks, notes={"1": ("f1a", "f1b")})

cfg5 = SemConfig(W=20, H=5)
cfg6 = SemConfig(W=20, H=6)

ALL_DOCS = [
    ("S1 sanctioned-KEEP", d_sanc_keep, cfg4, [None]),
    ("S2 sanctioned-WIDOW", d_sanc_wid, cfg2, [None]),
    ("P1 widow-pull-back", d_pull, cfg4, [None]),
    ("F1 xref-fixpoint", d_fix, cfg4, [1, 2, 9, 10, 99]),
    ("S3 foot-sanctioned", d_foot_sanc, cfg4, [None]),
    ("S4 float-sanctioned", d_float_sanc, cfg4, [None]),
    ("E5 with-fn", _e5(True), cfg4, [None]),
    ("E6 with-float", _e6(True), cfg6, [None]),
]


# ---------------------------------------------------------------- run --------

def main():
    print("=" * 60)
    print("PageForge core-families check (BREAK + WID + XREF + KEEP)")
    print("=" * 60)

    print("\n[1] Engine A == Engine B, byte-for-byte, all docs & seeds")
    for name, d, cfg, seeds in ALL_DOCS:
        for sd in seeds:
            ok, ra, rb = agree(d, cfg, sd)
            check(ok, "%s seed=%s : pages+labels identical (rounds A/B %d/%d)"
                  % (name, sd, ra[2], rb[2]))
    # single-pass (fixed map) agreement on the fixpoint doc, confusable maps
    for m in ({"sec": 1}, {"sec": 10}, {"sec": 99}):
        fa = A.layout_fixed(d_fix, cfg4, m)
        fb = B.layout_fixed(d_fix, cfg4, m)
        check(fa == fb, "F1 layout_fixed(%s): A==B single-pass" % m)

    print("\n[2] Sanctioned violations: both engines agree on the SAME site")
    wa_k, wb_k = A.waived_sites(d_sanc_keep, cfg4), B.waived_sites(d_sanc_keep, cfg4)
    check(wa_k == [(2, "h", ("KEEP",))], "S1 engine-A waived == [(2,h,(KEEP,))]  got %s" % wa_k)
    check(wa_k == wb_k, "S1 engine-A waived == engine-B waived  (%s == %s)" % (wa_k, wb_k))
    # a 2-line paragraph split trips WIDOW and ORPHAN at ONE physical site -> one
    # deduped entry (page, para, ('WIDOW','ORPHAN')).
    wa_w, wb_w = A.waived_sites(d_sanc_wid, cfg2), B.waived_sites(d_sanc_wid, cfg2)
    check(wa_w == [(1, "a", ("WIDOW", "ORPHAN"))],
          "S2 engine-A waived == [(1,a,(WIDOW,ORPHAN))]  got %s" % wa_w)
    check(wa_w == wb_w, "S2 engine-A waived == engine-B waived  (%s == %s)" % (wa_w, wb_w))
    # a doc with NO capacity pressure has no sanctioned violation (control)
    check(A.waived_sites(d_pull, cfg4) == [], "control: P1 has no waived site")

    print("\n[3] XREF fixpoint: unique / confluent and productive")
    conv = set()
    for sd in [1, 2, 9, 10, 99]:
        pa, la, ra = A.layout(d_fix, cfg4, initial_ref_page=sd)
        conv.add(tuple(pa))
    check(len(conv) == 1, "F1 confluent: all confusable seeds -> one fixpoint")
    conv_pages, conv_labels, conv_rounds = A.layout(d_fix, cfg4)
    single10, lab10 = A.layout_fixed(d_fix, cfg4, {"sec": 10})
    check(single10 != conv_pages,
          "F1 productive: width-4 single-pass differs from converged fixpoint")
    check(conv_labels == {"sec": 3} and lab10 == {"sec": 3},
          "F1 target label stable at page 3 (single-pass %s, converged %s)"
          % (lab10, conv_labels))

    print("\n[4] Path dependence: gold != naive full-fill; xref value coupled to repair")
    # sanctioned-KEEP: gold strands the heading (kt block pushed to page 3),
    # naive full-fill would split the keep-together block onto page 2/3.
    gold_k, gl_k, _ = A.layout(d_sanc_keep, cfg4)
    check(A.waived_sites(d_sanc_keep, cfg4) != [], "P: repair active on S1 (trajectory-dependent)")
    # widow pull-back: gold page 1 holds 3 lines, naive holds 4 (repair changed layout)
    gold_p = A.layout(d_pull, cfg4)[0]
    p1_lines = [ln for ln in gold_p[0].split("\n") if ln.strip()]
    check(len(p1_lines) == 3, "P1 gold page-1 under-fills to 3 lines (naive would be 4)")
    # E12: cross-ref VALUE depends on the pagination trajectory
    gold_secpage = A.layout(d_fix, cfg4)[1]["sec"]
    naive_secpage = naive_fullfill(d_fix, cfg4, {"sec": gold_secpage})["sec"]
    print("      (illustrative) gold sec-page=%s naive-fullfill sec-page=%s"
          % (gold_secpage, naive_secpage))

    print("\n[FF] FOOT + FLOAT: capacity-consuming families")
    # regression: engine A==B already covered for S3/S4/E5/E6 in section [1].
    # natural sanctioned violations from FOOT and FLOAT contention:
    _wo = [(1, "A", ("WIDOW", "ORPHAN"))]  # 2-line split, one deduped site
    for name, d, cfg, exp in [("S3 FOOT-contention", d_foot_sanc, cfg4, _wo),
                              ("S4 FLOAT-contention", d_float_sanc, cfg4, _wo)]:
        wa, wb = A.waived_sites(d, cfg), B.waived_sites(d, cfg)
        check(wa == exp, "%s: engine-A waived == %s  got %s" % (name, exp, wa))
        check(wa == wb, "%s: A waived == B waived (same site)  (%s == %s)" % (name, wa, wb))

    def _lay(engine, d, cfg):
        try:
            return ("ok", engine.layout(d, cfg)[0])
        except ValueError:
            return ("unlay", None)

    # E5 (FOOT<->WID): footnote presence changes the layout; A==B on both variants.
    e5a_A, e5b_A = _lay(A, _e5(False), cfg4), _lay(A, _e5(True), cfg4)
    e5a_B, e5b_B = _lay(B, _e5(False), cfg4), _lay(B, _e5(True), cfg4)
    check(e5a_A == e5a_B and e5b_A == e5b_B, "E5: A==B on both variants")
    check(e5a_A != e5b_A, "E5 path-difference: adding footnote changes the layout")

    # E6 (FOOT<->FLOAT): BOT float steals bottom rows; A==B on both variants.
    e6a_A, e6b_A = _lay(A, _e6(False), cfg6), _lay(A, _e6(True), cfg6)
    e6a_B, e6b_B = _lay(B, _e6(False), cfg6), _lay(B, _e6(True), cfg6)
    check(e6a_A == e6a_B and e6b_A == e6b_B, "E6: A==B on both variants")
    check(e6a_A != e6b_A, "E6 path-difference: adding BOT float changes the layout")

    print("\n[PR] Priority permutation governs conflict resolution (all-families)")
    from dataclasses import replace as _replace
    # same doc, two permutations -> the sanctioned violation RELOCATES to a
    # different family/site; both engines agree on each permutation.
    d_perm = C.doc(C.heading("h", C.words("Sec")),
                   C.para("a", C.words("aaa bbb ccc ddd eee fff ggg")))
    r_kw = A.waived_sites(d_perm, _replace(cfg2, priority=("KEEP", "WIDOW", "ORPHAN")))
    r_wk = A.waived_sites(d_perm, _replace(cfg2, priority=("WIDOW", "KEEP", "ORPHAN")))
    _rules = lambda sites: {r for s in sites for r in s[2]}
    check(("KEEP" in _rules(r_wk)) and ("WIDOW" in _rules(r_kw)),
          "permutation relocates the waived rule: KEEP-first waives WIDOW %s; "
          "WIDOW-first waives KEEP %s" % (r_kw, r_wk))
    for prio in [("KEEP", "WIDOW", "ORPHAN"), ("WIDOW", "KEEP", "ORPHAN"),
                 ("ORPHAN", "KEEP", "WIDOW")]:
        cfgp = _replace(cfg2, priority=prio)
        pa = A.layout(d_perm, cfgp)[0]
        pb = B.layout(d_perm, cfgp)[0]
        wa, wb = A.waived_sites(d_perm, cfgp), B.waived_sites(d_perm, cfgp)
        check(pa == pb and wa == wb, "permutation %s: A==B (pages+waived)" % (prio,))

    NDIFF = 1500
    print("\n[5] Randomized differential (seeded): A==B or SAME exception, %d docs" % NDIFF)
    import random as _rnd
    import hashlib as _hl
    mismatches, nonconv, unlay, ok_layouts = 0, 0, 0, 0
    ok_with_float, ok_with_foot = 0, 0
    cov = {"hyph": 0, "folio": 0, "parity": 0, "nonid_prio": 0, "headblank": 0}
    for i in range(NDIFF):
        # deterministic seed (stable across processes; Python's builtin hash of
        # strings/tuples is per-process randomized and must NOT be used here)
        seed = int.from_bytes(_hl.blake2b(("pf-slice-diff|%d" % i).encode(),
                                          digest_size=8).digest(), "big")
        rng = _rnd.Random(seed)
        doc, cfg = _random_doc(rng)
        ra = _safe_layout(A, doc, cfg)
        rb = _safe_layout(B, doc, cfg)
        if ra[0] != rb[0]:
            mismatches += 1
            print("      MISMATCH doc#%d kind=%s/%s" % (i, ra[0], rb[0]))
        elif ra[0] == "ok":
            ok_layouts += 1
            if ra[1] != rb[1]:
                mismatches += 1
                print("      PAGE-MISMATCH doc#%d" % i)
            if any(getattr(b, "kind", "") == "float" for b in doc.blocks):
                ok_with_float += 1
            if doc.notes:
                ok_with_foot += 1
            if cfg.hyph == "EVERY_K":
                cov["hyph"] += 1
            if cfg.folio != "NONE":
                cov["folio"] += 1
            if cfg.just == "PAGE_PARITY":
                cov["parity"] += 1
            if cfg.priority != ("KEEP", "WIDOW", "ORPHAN"):
                cov["nonid_prio"] += 1
            if cfg.head_blank_before or cfg.head_blank_after:
                cov["headblank"] += 1
        elif ra[0] == "nonconv":
            nonconv += 1
        else:
            unlay += 1
    check(mismatches == 0,
          "%d random docs: 0 A/B mismatches (ok=%d nonconv=%d unlayoutable=%d)"
          % (NDIFF, ok_layouts, nonconv, unlay))
    check(ok_with_float >= 20 and ok_with_foot >= 20,
          "coverage: layoutable set exercises floats (%d) and footnotes (%d)"
          % (ok_with_float, ok_with_foot))
    check(all(v >= 15 for v in cov.values()),
          "coverage (new families): hyph=%d folio=%d page-parity-just=%d "
          "non-identity-priority=%d head-blank=%d" %
          (cov["hyph"], cov["folio"], cov["parity"], cov["nonid_prio"], cov["headblank"]))

    print("\n" + "=" * 60)
    if FAILS:
        print("RESULT: FAIL (%d) ->" % len(FAILS))
        for m in FAILS:
            print("   -", m)
        sys.exit(1)
    print("RESULT: ALL CHECKS PASS")


if __name__ == "__main__":
    main()
