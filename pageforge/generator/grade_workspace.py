"""Grade-by-value adapter: run the agent's workspace `pageforge` package on the
instance's hidden corpus and compare RENDERED PAGES (plain strings) to the
reference.

Isolation is TWO boundaries, and the disk half alone is NOT sufficient:

  disk    -- purge_oracle() deletes generator/ so the oracle cannot be read or
             imported from the agent-reachable filesystem
  process -- the agent's layout() runs in a subprocess where the oracle was
             never loaded (generator/sandbox.py)

Importing the agent's package into the GRADER's interpreter hands it the
grader's process, where engine A is already resident: agent code can reach it
through sys.modules, or through the GC object graph if those entries are
scrubbed, and score a perfect 1.0 with the disk clean. `isolated=True` (the
default) closes that. `isolated=False` is a dev-only escape hatch -- it is how
the positive-control test proves the exploit really works -- and must never be
used to score a rollout.

Docs cross the boundary as plain data (pfcore.to_plain/from_plain), so no
cross-module isinstance is ever used.

# PAGEFORGE_ORACLE_SENTINEL_7b1e9f4a
"""
from __future__ import annotations
import importlib
import sys
from dataclasses import asdict

from . import pfcore as GP
from . import engine as A
# Imported EAGERLY, not inside _grade_isolated(): purge_oracle() deletes
# generator/ from disk at boot, so anything grading needs must already be
# resident in memory by then -- exactly like engine A above.
from .sandbox import Sandbox, SandboxError, SandboxTimeout


class _workspace_on_path:
    """Put ONE workspace on sys.path, import `pageforge` from it, and take the
    entry back off afterwards.

    Leaving entries behind is a correctness bug, not just untidiness: grading a
    second workspace in the same process would then resolve `pageforge` from
    whichever directory sits earliest on sys.path, so a CORRECT submission can
    score 0.0 because some earlier submission's directory is still there. The
    isolated path cannot hit this (fresh interpreter, sys.path = [workspace] +
    stdlib), but the dev hatch below must not be quietly wrong either."""

    def __init__(self, workspace_dir):
        self.dir = workspace_dir

    def _drop_pkg(self):
        for m in list(sys.modules):
            if m == "pageforge" or m.startswith("pageforge."):
                del sys.modules[m]

    def __enter__(self):
        self._added = self.dir not in sys.path
        if self._added:
            sys.path.insert(0, self.dir)
        self._drop_pkg()
        return importlib.import_module("pageforge")

    def __exit__(self, *exc):
        if self._added:
            try:
                sys.path.remove(self.dir)
            except ValueError:
                pass
        self._drop_pkg()          # never leave this workspace's modules cached
        return False


# NOTE: an `import_workspace_pkg()` helper used to live here. It left the
# workspace directory on sys.path, so grading a second workspace in the same
# process resolved `pageforge` from an earlier submission's directory and a
# CORRECT engine could score 0.0. It has been removed rather than deprecated --
# use `_workspace_on_path` above, which always takes its entry back off.


def _score(pairs) -> tuple:
    """pairs: iterable of (gold_pages, cand_pages). Both are list[str]."""
    tot_p = m_p = tot_d = m_d = 0
    for gold, cand in pairs:
        tot_p += len(gold)
        m_p += sum(1 for j in range(len(gold)) if j < len(cand) and cand[j] == gold[j])
        tot_d += 1
        m_d += 1 if cand == gold else 0
    page_frac = m_p / tot_p if tot_p else 0.0
    doc_frac = m_d / tot_d if tot_d else 0.0
    reward = 0.7 * page_frac + 0.3 * doc_frac
    return reward, {"page_frac": page_frac, "doc_frac": doc_frac}


# How many per-document timeouts to absorb (each costs a worker restart) before
# giving up and scoring the remainder empty. Bounds the worst case for a wholly
# non-terminating agent at ~MAX_TIMEOUTS * timeout instead of len(corpus) *
# timeout, while still letting an agent that stalls on one pathological document
# earn credit on all the others.
MAX_TIMEOUTS = 3


def _grade_isolated(workspace_dir: str, instance, timeout=None) -> tuple:
    """Default path: the agent's layout() runs in a process with no oracle."""
    cfg_dict = asdict(instance.cfg)
    pairs = []
    kw = {} if timeout is None else {"timeout": timeout}
    timeouts = 0
    with Sandbox(workspace_dir, **kw) as sb:
        for doc, _cat in instance.corpus:
            gold = A.layout(doc, instance.cfg)[0]
            if timeouts >= MAX_TIMEOUTS:
                pairs.append((gold, []))      # agent does not terminate; stop paying
                continue
            try:
                cand = sb.layout(GP.to_plain(doc), cfg_dict)
            except SandboxTimeout:
                # Non-terminating on THIS document: score it empty, then bring
                # the worker back so later documents still get a fair run.
                cand = []
                timeouts += 1
                if timeouts < MAX_TIMEOUTS:
                    sb.restart()
            except SandboxError:
                # The sandbox itself is broken or compromised. Never score this
                # as a plain zero -- that would hide a failed isolation boundary
                # behind a low reward.
                raise
            except RuntimeError:
                cand = []          # the agent's code raised -- score it as empty
            pairs.append((gold, cand))
    return _score(pairs)


def _grade_in_process(workspace_dir: str, instance) -> tuple:
    """DEV ONLY -- no process boundary. Agent code runs inside the grader, where
    the oracle is resident and reachable. Never use this to score a rollout."""
    pairs = []
    with _workspace_on_path(workspace_dir):
        agent_pfcore = importlib.import_module("pageforge.pfcore")
        agent_engine = importlib.import_module("pageforge.engine")
        agent_sem = importlib.import_module("pageforge.semconfig")
        acfg = agent_sem.SemConfig(**asdict(instance.cfg))

        for doc, _cat in instance.corpus:
            gold = A.layout(doc, instance.cfg)[0]
            adoc = agent_pfcore.from_plain(GP.to_plain(doc))
            try:
                cand = agent_engine.layout(adoc, acfg)
                cand = ["\n".join(p) if isinstance(p, (list, tuple)) else p
                        for p in cand]
            except Exception:
                cand = []
            pairs.append((gold, cand))
    return _score(pairs)


def grade_workspace(workspace_dir: str, instance, isolated: bool = True,
                    timeout=None) -> tuple:
    """Returns (reward, detail). reward = 0.7*page-match + 0.3*doc-match.

    isolated=True (default) runs the agent's layout() in a subprocess that cannot
    import the oracle. isolated=False is a documented dev-only escape hatch with
    NO process boundary -- see the module docstring.

    timeout: per-document wall-clock cap for the agent's layout(), in seconds
    (default sandbox.DEFAULT_TIMEOUT). Isolated grading only -- there is no way
    to interrupt a non-terminating call in-process."""
    if isolated:
        return _grade_isolated(str(workspace_dir), instance, timeout=timeout)
    return _grade_in_process(str(workspace_dir), instance)
