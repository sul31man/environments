"""Process-isolated grading: run the agent's layout() in a subprocess that has
NO access to the oracle, in memory or on disk.

WHY THIS EXISTS
---------------
Importing the agent's package into the grader's own interpreter hands it the
grader's process. Deleting `generator/` from disk does not help: the oracle is
already loaded, so agent code can reach it through `sys.modules` -- and, even if
those entries are scrubbed, through the GC object graph via any live function's
`__globals__`. Either route returns the reference engine's own pages and scores
a perfect 1.0, while every disk-based isolation check still reports "isolated".

There is no in-process mitigation. The module objects are reachable by
construction, so the boundary has to be a PROCESS boundary. Isolation therefore
has two parts, and the disk half alone is not sufficient:

  disk    -- purge_oracle() removes generator/ so nothing can be read or imported
  process -- the agent's layout() runs here, where the oracle was never loaded

MECHANISM
---------
The agent's `pageforge` package is imported in a subprocess started with `-I`
(isolated mode: no PYTHONPATH, no user site-packages) whose `sys.path` is the
workspace plus the standard library. The worker REFUSES TO START if `generator`
is importable there -- fail-closed, checked with `importlib.util.find_spec`
after `invalidate_caches()`, not by a flag.

Nothing but plain data crosses the boundary. PageForge is already graded by
value, so this is nearly free: documents cross as `pfcore.to_plain()` output,
the config as a plain dict, and the worker returns `list[str]` rendered pages.
No object the agent touches holds a reference back into the grader.

The JSON line protocol runs over a PRIVATE duplicate of fd 1, with fd 1 itself
redirected to stderr before any agent code is imported. Agents print debug
output routinely; in-process that is harmless, and it must stay harmless here.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile

# Per-document wall-clock cap for the agent's layout(). A full 23-document
# corpus grades in ~0.05s, so this is ~200x headroom: it exists to stop a
# non-terminating agent from wedging grading forever, not to pressure honest
# code. On expiry the worker is killed and the document scores as empty --
# a hang must produce a score, not an indefinite stall.
DEFAULT_TIMEOUT = 10.0

# --------------------------------------------------------------------------
# The worker. Runs with the oracle unreachable; refuses to start otherwise.
# --------------------------------------------------------------------------
WORKER_SRC = r'''
import importlib, importlib.util, json, os, sys

WORKSPACE = sys.argv[1]

# The protocol owns a PRIVATE copy of fd 1; fd 1 itself is redirected to stderr
# before any agent code runs. Agents print diagnostics all the time -- that is
# normal, and in-process it is harmless -- so nothing the agent writes to stdout
# (including a raw os.write(1, ...)) may corrupt the JSON line protocol.
_PROTO_FD = os.dup(1)
os.dup2(2, 1)
PROTO = os.fdopen(_PROTO_FD, "w")
sys.stdout = sys.stderr


def _send(obj):
    PROTO.write(json.dumps(obj) + "\n")
    PROTO.flush()

# sys.path = workspace + stdlib ONLY. Drop this script's own directory, any
# inherited entry, and anything that could carry the oracle (site-packages
# included: a non-editable `pip install .` would otherwise put it there).
_stdlib = [p for p in sys.path
           if p and ("python3" in p or "lib-dynload" in p or p.endswith(".zip"))
           and "site-packages" not in p]
sys.path[:] = [WORKSPACE] + _stdlib

# FAIL CLOSED: if the oracle is reachable here, this sandbox is worthless.
importlib.invalidate_caches()
if importlib.util.find_spec("generator") is not None:
    _send({"fatal":
        "SANDBOX COMPROMISED: 'generator' importable inside the agent worker"})
    raise SystemExit(3)

pkg = importlib.import_module("pageforge")
agent_pfcore = importlib.import_module("pageforge.pfcore")
agent_engine = importlib.import_module("pageforge.engine")
agent_sem = importlib.import_module("pageforge.semconfig")


def _cfg(d):
    # JSON turns tuples into lists; SemConfig.priority must be a tuple again.
    return agent_sem.SemConfig(**{k: tuple(v) if isinstance(v, list) else v
                                  for k, v in d.items()})


def _layout(plain_doc, cfg_dict):
    doc = agent_pfcore.from_plain(plain_doc)
    pages = agent_engine.layout(doc, _cfg(cfg_dict))
    # normalise to plain page strings before they cross back
    return ["\n".join(p) if isinstance(p, (list, tuple)) else p for p in pages]


_send({"ready": True})

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    if req.get("op") == "__stop__":
        break
    try:
        out = {"ok": _layout(req["doc"], req["cfg"])}
    except Exception as e:
        out = {"err": "%s: %s" % (type(e).__name__, e)}
    _send(out)
'''


class SandboxError(RuntimeError):
    pass


class SandboxTimeout(RuntimeError):
    """The agent's layout() exceeded the wall-clock cap. The worker is dead by
    the time this is raised; the caller scores the document as empty."""


class Sandbox:
    """A live agent worker. One subprocess per grading run."""

    def __init__(self, workspace_dir, timeout=DEFAULT_TIMEOUT):
        self.timeout = timeout
        self._workspace = workspace_dir
        self._tmp = tempfile.mkdtemp(prefix="pf_sandbox_")
        script = os.path.join(self._tmp, "pf_worker.py")
        with open(script, "w") as fh:
            fh.write(WORKER_SRC)
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
        self.p = subprocess.Popen(
            [sys.executable, "-I", script, os.path.abspath(workspace_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env, cwd=self._tmp)
        # Startup is bounded too: agent module-level code runs at import, so a
        # loop there would otherwise hang before the first document.
        try:
            hello = self._readline(self.timeout)
        except SandboxTimeout:
            raise SandboxError(
                "agent worker did not start within %.1fs (module-level code in "
                "the agent package may not terminate)" % self.timeout)
        if not hello:
            err = self.p.stderr.read()[-800:]
            raise SandboxError("agent worker failed to start:\n%s" % err)
        msg = json.loads(hello)
        if "fatal" in msg:
            raise SandboxError(msg["fatal"])

    def _readline(self, timeout):
        """readline() with a deadline. Returns "" if the worker died. Raises
        SandboxTimeout (after killing the worker) if nothing arrives in time.

        select() on the pipe rather than a thread: the worker may be in a tight
        non-yielding loop, and there is nothing to interrupt it from inside."""
        if timeout is None:
            return self.p.stdout.readline()
        ready, _, _ = select.select([self.p.stdout], [], [], timeout)
        if not ready:
            self.p.kill()
            self.p.wait(timeout=5)
            raise SandboxTimeout(
                "agent layout() exceeded %.1fs -- worker killed" % timeout)
        return self.p.stdout.readline()

    def layout(self, plain_doc, cfg_dict):
        """Run the agent's layout() on one document. Returns list[str] pages.

        Raises RuntimeError if the agent's code raised, or SandboxTimeout if it
        did not finish in time -- the caller scores either as an empty result,
        exactly as the in-process path scores a raising agent."""
        req = {"op": "layout", "doc": plain_doc, "cfg": cfg_dict}
        try:
            self.p.stdin.write(json.dumps(req) + "\n")
            self.p.stdin.flush()
        except (BrokenPipeError, ValueError):
            raise SandboxError("agent worker is gone (previous call killed it)")
        line = self._readline(self.timeout)
        if not line:
            raise SandboxError("agent worker died: %s"
                               % self.p.stderr.read()[-400:])
        rep = json.loads(line)
        if "err" in rep:
            raise RuntimeError(rep["err"])
        return rep["ok"]

    def restart(self):
        """Replace a dead worker (e.g. after a timeout kill) so the remaining
        documents still get graded. One non-terminating document must not
        silently zero every document after it."""
        self.close()
        self.__init__(self._workspace, self.timeout)

    def close(self):
        try:
            if self.p.poll() is None:
                self.p.stdin.write(json.dumps({"op": "__stop__"}) + "\n")
                self.p.stdin.flush()
                self.p.wait(timeout=5)
        except Exception:
            pass
        finally:
            if self.p.poll() is None:
                self.p.kill()
            import shutil
            shutil.rmtree(self._tmp, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
