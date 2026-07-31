"""PageForge shared core: document AST + rendering primitives.

GIVEN to the agent in the full build (identical copy). Contains only data
types and pure rendering helpers shared by every engine. Engines A and B build
their OWN internal galley/page representations from this AST; they share only
the INPUT model and the output contract (list[str] pages + label->page dict), so
their agreement is a genuine differential (see docs/SEMANTICS.md sec 7).

NOTE: this module is GIVEN to the agent (copied into the workspace), so it must
NOT carry the oracle canary -- the canary lives only in purged oracle-logic files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass(frozen=True)
class Word:
    """A literal ASCII word token (no spaces)."""
    text: str


@dataclass(frozen=True)
class Ref:
    """A cross-reference token; renders to 'p.<page-of-label>' (SEMANTICS sec 2)."""
    label: str


@dataclass(frozen=True)
class FnMark:
    """A footnote anchor token; renders as '^<id>' and anchors doc.notes[id]."""
    fid: str


Token = Union[Word, Ref, FnMark]

FN_PREFIX = "^"


@dataclass(frozen=True)
class Block:
    """A document block. kind is 'para' or 'heading'. label is optional and unique.

    keep_together (KEEP family, SEMANTICS sec 5): all of the block's galley lines
    must lie on a single page (hard, non-waivable constraint).
    """
    bid: str
    kind: str
    tokens: tuple
    label: Optional[str] = None
    keep_together: bool = False

    @property
    def is_heading(self) -> bool:
        return self.kind == "heading"


@dataclass(frozen=True)
class Float:
    """Out-of-flow block (SEMANTICS sec 5b). Produces no text galley lines."""
    bid: str
    h: int
    zone: str          # 'T' or 'B'
    art: tuple         # h fixed ASCII rows
    label: Optional[str] = None
    kind: str = "float"

    @property
    def is_heading(self) -> bool:
        return False


@dataclass(frozen=True)
class Doc:
    blocks: tuple
    notes: tuple = ()   # tuple of (fid, tuple(body_rows)); footnote bodies

    def notes_map(self) -> dict:
        return {fid: rows for (fid, rows) in self.notes}


# ---- construction helpers (used by fixtures / generator) --------------------

def W(text: str) -> Word:
    return Word(text)


def R(label: str) -> Ref:
    return Ref(label)


def para(bid: str, tokens, label: Optional[str] = None,
         keep_together: bool = False) -> Block:
    return Block(bid=bid, kind="para", tokens=tuple(tokens), label=label,
                 keep_together=keep_together)


def heading(bid: str, tokens, label: Optional[str] = None) -> Block:
    return Block(bid=bid, kind="heading", tokens=tuple(tokens), label=label)


def fig(bid: str, h: int, zone: str, art, label: Optional[str] = None) -> Float:
    return Float(bid=bid, h=h, zone=zone, art=tuple(art), label=label)


def FM(fid: str) -> FnMark:
    return FnMark(fid)


def doc(*blocks, notes=None) -> Doc:
    return Doc(blocks=tuple(blocks), notes=tuple((notes or {}).items()))


def words(s: str):
    """Convenience: turn a plain string into a list of Word tokens."""
    return [Word(w) for w in s.split()]


# ---- rendering --------------------------------------------------------------

def token_text(tok: Token, ref_pages: dict) -> str:
    """Render one token to its literal string given the current label->page map.

    A Ref to a label not yet in the map renders as 'p.1' by the caller's
    convention (the caller seeds the map for every label before round 1).
    """
    if isinstance(tok, Word):
        return tok.text
    if isinstance(tok, FnMark):
        return FN_PREFIX + tok.fid
    # Ref
    return "p." + str(ref_pages[tok.label])


def token_width(tok: Token, ref_pages: dict) -> int:
    return len(token_text(tok, ref_pages))


def pad_line(text: str, width: int) -> str:
    """Left-align and right-pad (or hard-truncate, which the slice never needs)."""
    if len(text) > width:
        return text[:width]
    return text + " " * (width - len(text))


def to_plain(document: "Doc") -> dict:
    """Serialize a Doc to plain JSON-able data (for grade-by-value across the
    agent boundary: the grader and the agent rebuild identical docs via
    from_plain, so no cross-module isinstance is ever needed)."""
    def tok(t):
        if isinstance(t, Word):
            return ["w", t.text]
        if isinstance(t, Ref):
            return ["r", t.label]
        return ["f", t.fid]
    blocks = []
    for b in document.blocks:
        if isinstance(b, Float):
            blocks.append({"kind": "float", "bid": b.bid, "h": b.h, "zone": b.zone,
                           "art": list(b.art), "label": b.label})
        else:
            blocks.append({"kind": b.kind, "bid": b.bid, "label": b.label,
                           "keep_together": b.keep_together,
                           "tokens": [tok(t) for t in b.tokens]})
    return {"blocks": blocks, "notes": [[k, list(v)] for (k, v) in document.notes]}


def from_plain(data: dict) -> "Doc":
    def tok(t):
        if t[0] == "w":
            return Word(t[1])
        if t[0] == "r":
            return Ref(t[1])
        return FnMark(t[1])
    blocks = []
    for b in data["blocks"]:
        if b["kind"] == "float":
            blocks.append(Float(bid=b["bid"], h=b["h"], zone=b["zone"],
                                art=tuple(b["art"]), label=b["label"]))
        else:
            blocks.append(Block(bid=b["bid"], kind=b["kind"],
                                tokens=tuple(tok(t) for t in b["tokens"]),
                                label=b["label"], keep_together=b["keep_together"]))
    return Doc(blocks=tuple(blocks), notes=tuple((k, tuple(v)) for (k, v) in data["notes"]))


def render_pages(page_line_lists: List[List[str]], width: int, height: int) -> List[str]:
    """Turn a list of pages (each a list of line-texts) into rendered page strings.

    Every page is padded to exactly `height` lines of exactly `width` columns.
    """
    out = []
    for lines in page_line_lists:
        padded = [pad_line(t, width) for t in lines]
        while len(padded) < height:
            padded.append(" " * width)
        if len(padded) > height:  # defensive; pagination guarantees <= height
            raise ValueError("page exceeds height: %d > %d" % (len(padded), height))
        out.append("\n".join(padded))
    return out
