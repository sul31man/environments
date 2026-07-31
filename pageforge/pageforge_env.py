"""PageForge -- framework-agnostic environment adapter (NO platform wrapper).

Two-phase episode:
  Phase 1 (discovery): the agent submits its OWN documents to a probe oracle and
    infers the hidden per-instance layout semantics from the returned rendered
    pages. The forms are interdependent (see private/discovery_chain.py) -- a
    task-forced 15-30 step discovery chain.
  Phase 2 (implement + grade): the agent implements
    workspace/pageforge/engine.py::layout(doc, cfg) -> list[str] to the discovered
    semantics; graded by exact rendered-page match on a hidden corpus, with the
    oracle source purged from disk.

This module exposes the environment as plain functions so it can be driven by ANY
harness. It has NO external dependencies beyond the Python stdlib. Reference
end-to-end drivers (all stdlib-only, no platform):
    python3 -m private.phase_demo     # full loop: probe -> implement -> grade
    python3 -m private.deploy_sim     # container-lifecycle isolation proof
    python3 pageforge_env.py          # this file: quick self-contained demo

Integration points for a host harness:
  - generate(index)                      -> an Instance (hidden cfg + graded corpus)
  - spec_text(cfg)                       -> the prompt shown to the agent (Phase 1)
  - serve_probe_oracle(indices)          -> a ProbeServer (unix socket; the agent's
                                            Phase-1 channel; refuses corpus docs,
                                            enforces a probe budget)
  - grade_workspace(workspace_dir, inst) -> (reward, detail)  [Phase 2]
  - purge + assert_isolated(env_dir)     -> serve-time oracle isolation (fail-closed)
"""
from __future__ import annotations
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

ENV_DIR = Path(__file__).resolve().parent
WORKSPACE = ENV_DIR / "workspace"
sys.path.insert(0, str(ENV_DIR))

from generator import instance as I                 # noqa: E402
from generator import grade_workspace as _grade            # grade-by-value (no platform dep)

EVAL_COUNT = I.EVAL_COUNT
EVAL_NAMESPACE = I.EVAL_NAMESPACE
PROBE_BUDGET = 64
PROBE_SOCK = os.environ.get("PF_PROBE_SOCK", "/tmp/pf_probe.sock")


@lru_cache(maxsize=None)
def generate(index, namespace=EVAL_NAMESPACE):
    """Deterministic per-instance generation (blake2b seeded)."""
    return I.generate(index, namespace)


def spec_text(cfg) -> str:
    """Phase-1 prompt: discloses ONLY structure (grid, document model, which
    families are active). No form/value is disclosed; all are discovered by
    probing."""
    L = ["PageForge instance (layout semantics are HIDDEN -- discover by probing).",
         ""]
    L.append("Page grid: %d columns x %d content lines (monospace, exact-match "
             "graded)." % (cfg.W, cfg.H))
    L.append("Document model (build probes + your engine with `pageforge.pfcore`): "
             "blocks are paragraphs/headings; tokens are words, cross-references "
             "(REF), footnote marks; floats and footnotes exist.")
    L.append("ACTIVE families whose FORMS are NOT given: line breaking, "
             "hyphenation, justification, widow/orphan/keep (with a priority "
             "order), floats, splittable footnotes, folio, heading spacing, "
             "cross-reference fixpoint.")
    L.append("")
    L.append("PHASE 1 (discovery): `from probe import probe` then `probe(doc)` with "
             "your OWN documents; you get the reference rendered pages for that doc. "
             "Infer every hidden form. Forms are INTERDEPENDENT -- some are "
             "unobservable until you have pinned others. Budget: %d probes; "
             "graded-corpus documents are refused; the reference engine's source is "
             "not on disk." % PROBE_BUDGET)
    L.append("PHASE 2 (implement): edit workspace/pageforge/engine.py::layout(doc, "
             "cfg) -> list[str] to the forms you discovered, then submit. Grading is "
             "on hidden documents; the probe oracle is not available in Phase 2.")
    return "\n".join(L)


def serve_probe_oracle(indices, budget=PROBE_BUDGET, sock_path=PROBE_SOCK):
    """Start the Phase-1 probe oracle for the given task indices. Returns a running
    ProbeServer (unix socket). It answers the agent's OWN probe documents, REFUSES
    graded-corpus documents, and enforces the probe budget."""
    from generator.probe_server import ProbeServer   # imports engine A into memory
    instances = [generate(i) for i in indices]
    return ProbeServer.from_instances(instances, budget=budget,
                                      sock_path=sock_path).start_background()


def grade_workspace(workspace_dir, inst, isolated=True, timeout=None):
    """Phase-2 grade: run the agent's workspace `pageforge` layout() on the hidden
    corpus and compare rendered pages by exact string equality.
    reward = 0.7*page-match + 0.3*doc-match. Returns (reward, detail).

    isolated=True (DEFAULT, and the only setting valid for scoring) runs the
    agent's code in a subprocess where the oracle was never loaded. Purging the
    disk is not sufficient on its own: an in-process agent reaches the resident
    engine A through sys.modules or the GC object graph and scores 1.0.
    isolated=False is a dev-only escape hatch -- never use it for a rollout."""
    return _grade.grade_workspace(str(workspace_dir), inst, isolated=isolated,
                                 timeout=timeout)


def oracle_on_disk(env_dir=ENV_DIR) -> bool:
    g = Path(env_dir) / "generator"
    return (g / "engine.py").exists() or (g / "probe_server.py").exists()


def oracle_importable() -> bool:
    """Would a FRESH interpreter be able to import `generator`? A different
    question from oracle_on_disk(): a non-editable `pip install .` copies the
    package into site-packages, where it survives the purge of the source tree.

    Uses PathFinder, NOT importlib.util.find_spec: find_spec consults sys.modules
    first, and the serving process has the oracle legitimately loaded, so it
    would report "importable" forever after boot. PathFinder answers only from
    the search path, which is what the agent's fresh subprocess actually sees.
    Caches are invalidated first -- the path finder otherwise reports a spec for
    a directory that has already been deleted."""
    import importlib
    from importlib.machinery import PathFinder
    importlib.invalidate_caches()
    try:
        return PathFinder().find_spec("generator", sys.path) is not None
    except (ImportError, ValueError):
        return False


def assert_isolated(env_dir=ENV_DIR):
    """FAIL-CLOSED serve-time isolation check, on BOTH boundaries the oracle can
    cross: the agent-reachable disk, and the import path."""
    if oracle_on_disk(env_dir):
        raise RuntimeError("PF FAIL-CLOSED: oracle source present on disk -- purge "
                           "generator/ before serving a scored task.")
    if oracle_importable():
        raise RuntimeError(
            "PF FAIL-CLOSED: 'generator' is still importable after the purge "
            "(most likely a non-editable `pip install .` copied it into "
            "site-packages). Uninstall it, or serve from the source tree "
            "without installing -- the no-install path is fully supported.")


def purge_oracle(env_dir=ENV_DIR):
    """Serve-time hardening: after the oracle is loaded to memory (probe server
    started), delete generator/ private/ docs/ from the agent-reachable disk. The
    agent then reaches the oracle ONLY through the socket. Fail-closed."""
    for d in ("generator", "private", "docs"):
        shutil.rmtree(Path(env_dir) / d, ignore_errors=True)
    assert_isolated(env_dir)


# Optional: a deterministic isolation-attack prompt a host can run as a check task.
LEAKPROBE_PROMPT = (
    "ISOLATION PROBE. Run each command and paste FULL output:\n"
    "  1) cat generator/engine.py\n"
    "  2) python3 -c 'import generator.engine; print(\"IMPORTED\")'\n"
    "  3) find / -name 'engine.py' -o -name 'probe_server.py' 2>/dev/null\n"
    "  4) python3 -c 'import importlib.util; print(importlib.util.find_spec(\"generator\"))'\n"
    "Expected after purge: 1-2 fail; 3 finds only the workspace stub; 4 prints None."
)


if __name__ == "__main__":
    # Self-contained demo: generate an instance, serve the probe oracle, do one
    # discovery probe, and grade the workspace stub. No platform / network needed.
    from generator import pfcore as C
    print("PageForge -- standalone self-check")
    inst = generate(0)
    print("  instance 0: grid %dx%d, corpus=%d docs (cfg HIDDEN from the agent)"
          % (inst.cfg.W, inst.cfg.H, len(inst.corpus)))
    srv = serve_probe_oracle([0])
    # simulate a Phase-1 probe (what the agent's workspace/probe.py does over the socket)
    from generator.probe_oracle import ProbeOracle
    oracle = ProbeOracle(inst.cfg, [d for d, _ in inst.corpus], budget=PROBE_BUDGET)
    pages = oracle.probe(C.doc(C.para("p", [C.W("x" * 25)])))
    print("  phase-1 probe(long word) -> line 1 = %r" % pages[0].split("\n")[0])
    srv.stop()
    reward, _ = grade_workspace(WORKSPACE, inst)
    print("  phase-2 workspace-stub reward = %.3f (expect 0.0)" % reward)
    print("  reference end-to-end driver: python3 -m private.phase_demo")
