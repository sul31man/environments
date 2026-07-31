"""Two-phase adapter, end-to-end offline (no model or platform).

Demonstrates the full two-phase loop on a real eval instance:

  PHASE 1 (discovery): the agent probes the oracle with its OWN docs and recovers
    hidden facets from the outputs. We show (a) a real facet recovered by probing,
    (b) the oracle REFUSES a graded-corpus doc, (c) the call budget is enforced.

  PHASE 2 (implement + grade): the agent's engine is graded on the hidden corpus
    with the oracle PURGED. We show (a) a faithful engine scores 1.0, (b) the NEW
    isolation cheat -- an engine that reaches for the oracle at grade time -- fails
    (ModuleNotFoundError) and scores 0, exactly as it would in the served container.

Run:  python3 -m private.phase_demo   from the package root.
"""
from __future__ import annotations
import sys, os, importlib, builtins
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import replace

from generator import instance as I
from generator import grade as G
from generator import engine as A
from generator import pfcore as C
from generator import interp_b as _B    # a self-contained correct engine, bound
from generator.probe_oracle import ProbeOracle, ProbeError


# ---------------------------------------------------------------------------
# PHASE 1
# ---------------------------------------------------------------------------
def phase1(inst):
    print("[PHASE 1 -- discovery via probe oracle]")
    oracle = ProbeOracle(inst.cfg, [d for d, _ in inst.corpus], budget=64)

    # (a) recover a real facet: probe a long word, read the hyphenation period k
    #     from the fragment length on line 1.
    probe = C.doc(C.para("p", [C.W("x" * 25)]))
    pages = oracle.probe(probe)
    line1 = pages[0].split("\n")[0].rstrip()
    frag = len(line1.rstrip("-"))
    recovered_k = frag if frag in (2, 3, 4) else (frag % 4 or 4)
    ok_k = (inst.cfg.hyph == "NONE") or (frag % inst.cfg.hyph_k == 0)
    print("  probe(long word) -> line1=%r  fragment=%d  hyph_k(true)=%d  consistent=%s"
          % (line1, frag, inst.cfg.hyph_k, ok_k))

    # (b) soundness: the oracle REFUSES a graded-corpus document.
    corpus_doc = inst.corpus[0][0]
    refused = False
    try:
        oracle.probe(corpus_doc)
    except ProbeError as e:
        refused = True
        print("  probe(graded-corpus doc) -> REFUSED: %s" % e)

    # (c) budget is enforced.
    small = ProbeOracle(inst.cfg, [], budget=2)
    small.probe(probe); small.probe(probe)
    exhausted = False
    try:
        small.probe(probe)
    except ProbeError as e:
        exhausted = True
        print("  budget=2 -> 3rd probe blocked: %s" % e)
    print("  probes used this episode: %d / 64" % oracle.calls)
    return ok_k and refused and exhausted


# ---------------------------------------------------------------------------
# PHASE 2
# ---------------------------------------------------------------------------
class _BlockOracle:
    """Import hook that simulates the served container: generator.* (the oracle)
    is PURGED, so any Phase-2 attempt to import it fails."""
    BLOCK = ("generator.engine", "generator.interp_b", "generator.probe_oracle",
             "generator.instance", "generator")

    # PEP 451 protocol (Python 3.4+). This is the one that matters: the legacy
    # find_module/load_module pair below was REMOVED in Python 3.12, so on any
    # current interpreter a hook without find_spec is silently ignored -- the
    # simulated purge would do nothing and the oracle-reader cheat would import
    # the reference engine and score 1.0.
    def find_spec(self, name, path=None, target=None):
        if name in self.BLOCK:
            raise ModuleNotFoundError(
                "No module named %r (oracle purged in Phase 2)" % name)
        return None

    # Legacy protocol, retained for Python < 3.4 only.
    def find_module(self, name, path=None):
        return self if name in self.BLOCK else None

    def load_module(self, name):
        raise ModuleNotFoundError("No module named %r (oracle purged in Phase 2)" % name)


def _grade_with_oracle_purged(agent_layout, inst):
    """Grade an agent layout fn on the hidden corpus with the oracle unreachable.
    We DON'T purge the in-process reference used for the gold comparison; we block
    the AGENT's ability to re-import the oracle (that is what the container purge
    does to the agent's code)."""
    hook = _BlockOracle()
    sys.meta_path.insert(0, hook)
    # EVICT cached oracle modules so a fresh import must consult the hook (this is
    # what the container purge does to the agent's code). Held references (G's
    # captured engine, the faithful agent's bound _B) keep working; only NEW
    # imports of the oracle fail.
    saved = {m: sys.modules.pop(m) for m in list(sys.modules) if m in _BlockOracle.BLOCK}
    try:
        reward, _ = G.score(agent_layout, inst.corpus, inst.cfg)
        return reward
    finally:
        sys.meta_path.remove(hook)
        sys.modules.update(saved)


def faithful_agent(doc, cfg):
    """A faithful agent engine, self-contained (bound before Phase 2, no re-import
    of the oracle) -- exactly like a workspace engine that implements layout itself."""
    return _B.layout(doc, cfg)[0]


def oracle_reader_agent(doc, cfg):
    """The NEW isolation cheat: try to call the oracle at grade time."""
    O = importlib.import_module("generator.engine")   # purged in Phase 2 -> raises
    return O.layout(doc, cfg)[0]


def phase2(inst):
    print("\n[PHASE 2 -- implement + grade, oracle purged]")
    faithful = _grade_with_oracle_purged(faithful_agent, inst)
    print("  faithful agent (independent engine) reward = %.4f  (expect 1.0)" % faithful)

    def cheat(doc, cfg):
        try:
            return oracle_reader_agent(doc, cfg)
        except Exception:
            return []      # exactly what the grader sees when the import fails
    cheat_reward = _grade_with_oracle_purged(cheat, inst)
    # confirm the import genuinely fails under the purge
    raised = False
    hook = _BlockOracle(); sys.meta_path.insert(0, hook)
    for m in list(sys.modules):
        if m in _BlockOracle.BLOCK:
            del sys.modules[m]
    try:
        oracle_reader_agent(inst.corpus[0][0], inst.cfg)
    except ModuleNotFoundError as e:
        raised = True
        print("  oracle-reader cheat at grade time -> %s" % e)
    finally:
        sys.meta_path.remove(hook)
    print("  oracle-reader cheat reward = %.4f  (expect 0.0)" % cheat_reward)
    return abs(faithful - 1.0) < 1e-9 and cheat_reward < 0.05 and raised


def main():
    print("=" * 64)
    print("PageForge -- two-phase adapter, end-to-end offline")
    print("=" * 64)
    inst = I.generate(0, "eval")
    p1 = phase1(inst)
    p2 = phase2(inst)
    print("\n" + "=" * 64)
    ok = p1 and p2
    print("TWO-PHASE: %s" % ("PASS (discovery works; oracle refuses corpus + "
          "budget enforced; faithful=1.0; oracle-reader cheat purged->0)"
          if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
