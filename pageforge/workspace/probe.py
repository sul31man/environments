"""Phase-1 probe client (given to the agent; pure IPC, NO layout logic).

Usage from your Phase-1 exploration:

    from pageforge import pfcore as C
    from probe import probe
    doc = C.doc(C.para("p", [C.W("x" * 25)]))   # your own probe document
    pages = probe(doc)                            # reference rendered pages
    print("\n===PAGE===\n".join(pages))

You submit YOUR OWN documents and receive the reference engine's rendered pages
for them. Infer every hidden form from the outputs, then implement
`pageforge/engine.py` in Phase 2. The probe budget is finite; graded-corpus
documents are refused. The reference engine's source is not on this filesystem --
only its input/output behavior is observable, by probing.
"""
from __future__ import annotations
import json
import os
import socket

from pageforge import pfcore as C

SOCK = os.environ.get("PF_PROBE_SOCK", "/tmp/pf_probe.sock")
TASK_INDEX = int(os.environ.get("PF_TASK_INDEX", "0"))


class ProbeRefused(Exception):
    pass


def probe(doc, index=None):
    """Send a probe document to the oracle; return its rendered pages (list[str])."""
    req = {"index": TASK_INDEX if index is None else index, "doc": C.to_plain(doc)}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    try:
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    resp = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    if not resp.get("ok"):
        raise ProbeRefused(resp.get("error", "probe refused"))
    return resp["pages"]
