"""Phase-1 probe oracle SERVER (out-of-shell isolation).

The deployability problem: in a live rollout the agent has a continuous shell, so
the probe oracle (engine A) cannot sit on the agent-readable filesystem -- the
agent would just read/import it. Solution (load oracle to memory, then purge):

  boot:  import engine A + generate all instances INTO THIS PROCESS's memory,
         start this socket server, then DELETE generator/ from disk at boot.
  live:  the agent queries the server over a unix socket via `workspace/probe.py`
         (a pure-IPC client with NO engine logic). It receives rendered pages for
         its OWN probe documents only. engine A's SOURCE is gone from disk; only
         this process holds it, in memory.

So isolation holds by construction: nothing to cat, nothing to import. The server
also enforces the probe budget and refuses graded-corpus documents.

Protocol: newline-delimited JSON over AF_UNIX.
  ->  {"index": <int>, "doc": <plain-doc dict>}
  <-  {"ok": true, "pages": [...]}  |  {"ok": false, "error": "..."}

# PAGEFORGE_ORACLE_SENTINEL_7b1e9f4a
"""
from __future__ import annotations
import json
import os
import socket
import threading

from . import pfcore as C
from . import engine as A
from .probe_oracle import ProbeOracle, ProbeError

SOCK_ENV = "PF_PROBE_SOCK"
DEFAULT_SOCK = "/tmp/pf_probe.sock"


class ProbeServer:
    def __init__(self, oracles, sock_path=None):
        # oracles: {index: ProbeOracle}
        self._oracles = oracles
        self.sock_path = sock_path or os.environ.get(SOCK_ENV, DEFAULT_SOCK)
        self._srv = None
        self._thread = None

    @classmethod
    def from_instances(cls, instances, budget=64, sock_path=None):
        oracles = {ins.index: ProbeOracle(ins.cfg, [d for d, _ in ins.corpus],
                                          budget=budget)
                   for ins in instances}
        return cls(oracles, sock_path=sock_path)

    def _handle(self, conn):
        buf = b""
        try:
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            req = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
            resp = self._answer(req)
        except Exception as e:  # noqa: BLE001
            resp = {"ok": False, "error": "bad request: %s" % e}
        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))

    def _answer(self, req):
        idx = req.get("index")
        oracle = self._oracles.get(idx)
        if oracle is None:
            return {"ok": False, "error": "unknown task index %r" % idx}
        try:
            doc = C.from_plain(req["doc"])
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "undecodable doc: %s" % e}
        try:
            pages = oracle.probe(doc)
            return {"ok": True, "pages": pages, "remaining": oracle.remaining()}
        except ProbeError as e:
            return {"ok": False, "error": str(e)}

    def serve_forever(self):
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.sock_path)
        self._srv.listen(16)
        while True:
            conn, _ = self._srv.accept()
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def start_background(self):
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        try:
            if self._srv:
                self._srv.close()
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except OSError:
            pass
