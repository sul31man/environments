"""Process isolation: agent code must not reach the oracle from inside the grader.

Deleting generator/ from disk does NOT establish this. When the agent's package
is imported into the grader's interpreter, the oracle is already in memory and
reachable through sys.modules -- and, if those entries are removed, through the
GC object graph via any live function's __globals__. Either route scores a
perfect 1.0 while every disk-based isolation check still reports "isolated".

These tests are TWO-CONDITION by design: each exploit is asserted to genuinely
WIN without the defence before it is asserted to LOSE with it. A defence tested
only against an exploit never observed to succeed proves nothing -- the exploit
may simply be broken.

Run:  python3 -m pytest private/leak_test/ -q        (from the package root)
"""

import os
import shutil
import sys
import textwrap
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
if ENV_ROOT not in sys.path:
    sys.path.insert(0, ENV_ROOT)

from generator import instance as I            # noqa: E402
from generator import grade_workspace as GW    # noqa: E402

# The shipped stub scores 0.0; a blocked exploit must land at/below this.
FLOOR = 0.05

# An agent engine that never implements layout(): it delegates to the oracle
# found in the grader's own process -- sys.modules first, GC graph if scrubbed.
EXPLOIT_ENGINE = textwrap.dedent('''
    import sys, gc
    from dataclasses import asdict


    def _mod(name):
        m = sys.modules.get(name)
        if m is not None:
            return m
        for o in gc.get_objects():                  # sys.modules scrubbed?
            if type(o).__name__ == "module" and \\
                    getattr(o, "__name__", "") == name:
                return o
        return None


    def layout(doc, cfg):
        import pageforge.pfcore as APC
        O, GPC, GSC = (_mod("generator.engine"), _mod("generator.pfcore"),
                       _mod("generator.semconfig"))
        if O is None or GPC is None or GSC is None:
            return []
        odoc = GPC.from_plain(APC.to_plain(doc))    # our doc -> oracle's classes
        ocfg = GSC.SemConfig(**asdict(cfg))         # cfg arrives fully populated
        return O.layout(odoc, ocfg)[0]
''')


@pytest.fixture
def exploit_workspace(tmp_path):
    ws = tmp_path / "ws"
    shutil.copytree(os.path.join(ENV_ROOT, "workspace"), ws)
    (ws / "pageforge" / "engine.py").write_text(EXPLOIT_ENGINE)
    return str(ws)


def test_oracle_reader_actually_works_in_process(exploit_workspace):
    """POSITIVE CONTROL. Without process isolation this exploit really does win.

    If this ever stops passing, the test below proves nothing -- it would be
    measuring a broken exploit rather than a working defence."""
    inst = I.generate(0)
    reward, _ = GW.grade_workspace(exploit_workspace, inst, isolated=False)
    assert reward > 0.95, (
        "the in-process oracle-reader no longer succeeds (%.3f); the isolation "
        "test below is now unfalsifiable" % reward)


def test_oracle_reader_is_blocked_by_the_sandbox(exploit_workspace):
    """THE DEFENCE. The same exploit, graded isolated, scores the floor."""
    inst = I.generate(0)
    reward, _ = GW.grade_workspace(exploit_workspace, inst, isolated=True)
    assert reward <= FLOOR, "oracle reached from inside the sandbox (%.3f)" % reward


def test_isolated_is_the_default(exploit_workspace):
    """Isolation must not depend on the caller remembering a keyword."""
    inst = I.generate(0)
    reward, _ = GW.grade_workspace(exploit_workspace, inst)   # no isolated=
    assert reward <= FLOOR, (
        "default grading is not isolated (%.3f) -- a caller that omits the "
        "keyword scores a cheating agent as correct" % reward)


def test_sandbox_refuses_to_start_if_oracle_importable(tmp_path):
    """FAIL CLOSED: a worker that can import the oracle must not run at all."""
    from generator.sandbox import Sandbox, SandboxError
    ws = tmp_path / "ws"
    shutil.copytree(os.path.join(ENV_ROOT, "workspace"), ws)
    # plant an importable `generator` package inside the agent's own workspace
    plant = ws / "generator"
    plant.mkdir()
    (plant / "__init__.py").write_text("")
    (plant / "engine.py").write_text("def layout(*a, **k):\n    return ([], {})\n")
    with pytest.raises(SandboxError, match="SANDBOX COMPROMISED"):
        Sandbox(str(ws)).close()


def test_sandbox_is_faithful_for_the_stub():
    """The sandbox must not change the score of non-cheating code."""
    inst = I.generate(0)
    ws = os.path.join(ENV_ROOT, "workspace")
    a, _ = GW.grade_workspace(ws, inst, isolated=True)
    b, _ = GW.grade_workspace(ws, inst, isolated=False)
    assert abs(a - b) < 1e-9, "sandbox changed the stub's score (%.6f vs %.6f)" % (a, b)


def test_hanging_agent_times_out_instead_of_wedging_grading(tmp_path):
    """A non-terminating layout() must produce a SCORE, not an indefinite stall.

    `timeout` used to be accepted and stored but never enforced, so `while
    True: pass` hung grading forever -- worse than useless, because the
    parameter implied a protection that did not exist."""
    inst = I.generate(0)
    ws = tmp_path / "ws_hang"
    shutil.copytree(os.path.join(ENV_ROOT, "workspace"), ws)
    (ws / "pageforge" / "engine.py").write_text(textwrap.dedent('''
        def layout(doc, cfg):
            while True:
                pass
    '''))
    from generator.sandbox import Sandbox, SandboxTimeout
    from generator import pfcore as GP
    from dataclasses import asdict
    doc = inst.corpus[0][0]
    with Sandbox(str(ws), timeout=2.0) as sb:
        t0 = time.time()
        with pytest.raises(SandboxTimeout):
            sb.layout(GP.to_plain(doc), asdict(inst.cfg))
        assert time.time() - t0 < 10, "timeout did not fire promptly"


def test_hang_does_not_zero_the_documents_after_it(tmp_path):
    """One non-terminating document must not silently zero every later one:
    the worker is killed, then restarted for the rest of the corpus."""
    inst = I.generate(0)
    ws = tmp_path / "ws_hang_first"
    shutil.copytree(os.path.join(ENV_ROOT, "workspace"), ws)
    b_src = open(os.path.join(ENV_ROOT, "generator", "interp_b.py")).read()
    b_src = "\n".join(l for l in b_src.splitlines()
                      if "PAGEFORGE_ORACLE_SENTINEL" not in l)
    (ws / "pageforge" / "interp_b.py").write_text(b_src)
    # Hang on ONE specific document, identified by a CONTENT HASH -- not by call
    # count (the worker restarts after a timeout, so per-process counters reset
    # and a count-based trap hangs on every document) and not by block id (bids
    # restart per document, so 'hd0' matches most of the corpus).
    import hashlib
    from generator import pfcore as _GP
    victim = hashlib.md5(
        repr(_GP.to_plain(inst.corpus[0][0])).encode()).hexdigest()
    (ws / "pageforge" / "engine.py").write_text(textwrap.dedent('''
        import hashlib

        from . import pfcore as C
        from .interp_b import layout as _b

        VICTIM = %r


        def layout(doc, cfg):
            if hashlib.md5(repr(C.to_plain(doc)).encode()).hexdigest() == VICTIM:
                while True:
                    pass
            return _b(doc, cfg)[0]
    ''' % victim))
    r, detail = GW.grade_workspace(str(ws), inst, isolated=True, timeout=2.0)
    # the hung document is lost; every other document still grades correctly
    assert r > 0.5, ("a single hanging document collapsed the whole grade "
                     "(%.4f, %s)" % (r, detail))
    assert r < 1.0, "the hanging document should not have scored"


def test_fully_hanging_agent_is_bounded(tmp_path):
    """An agent that never terminates must not cost len(corpus) * timeout.

    Restarting the worker after every timeout would let a pathological
    submission stretch one grade to minutes; the timeout budget caps it."""
    inst = I.generate(0)
    ws = tmp_path / "ws_all_hang"
    shutil.copytree(os.path.join(ENV_ROOT, "workspace"), ws)
    (ws / "pageforge" / "engine.py").write_text(textwrap.dedent('''
        def layout(doc, cfg):
            while True:
                pass
    '''))
    from generator.grade_workspace import MAX_TIMEOUTS
    t0 = time.time()
    r, _ = GW.grade_workspace(str(ws), inst, isolated=True, timeout=1.0)
    elapsed = time.time() - t0
    assert r == 0.0
    budget = MAX_TIMEOUTS * 1.0 + 10          # + generous restart/startup slack
    assert elapsed < budget, (
        "non-terminating agent cost %.1fs; expected under %.1fs with a "
        "%d-timeout budget" % (elapsed, budget, MAX_TIMEOUTS))


def test_grading_two_workspaces_in_one_process(tmp_path):
    """A correct submission must score 1.0 even if another workspace was graded
    first in the same process.

    The in-process path used to leave each workspace on sys.path, so a later
    grade resolved `pageforge` from an EARLIER submission's directory -- a
    correct engine scoring 0.0. Isolated grading cannot hit this (fresh
    interpreter per run); the dev hatch must not either."""
    inst = I.generate(0)
    b_src = open(os.path.join(ENV_ROOT, "generator", "interp_b.py")).read()
    b_src = "\n".join(l for l in b_src.splitlines()
                      if "PAGEFORGE_ORACLE_SENTINEL" not in l)

    def mk(name, engine):
        ws = tmp_path / name
        shutil.copytree(os.path.join(ENV_ROOT, "workspace"), ws)
        (ws / "pageforge" / "interp_b.py").write_text(b_src)
        (ws / "pageforge" / "engine.py").write_text(engine)
        return str(ws)

    good = mk("good", "from .interp_b import layout as _b\n\n\n"
                      "def layout(d, c):\n    return _b(d, c)[0]\n")
    bad = mk("bad", "def layout(d, c):\n    return []\n")

    for isolated in (True, False):
        assert GW.grade_workspace(good, inst, isolated=isolated)[0] > 0.99
        assert GW.grade_workspace(bad, inst, isolated=isolated)[0] == 0.0
        after, _ = GW.grade_workspace(good, inst, isolated=isolated)
        assert after > 0.99, (
            "isolated=%s: correct submission scored %.4f after another "
            "workspace was graded first" % (isolated, after))


def test_agent_stdout_does_not_break_the_sandbox(tmp_path):
    """An honest agent that prints debug output must grade normally.

    The worker speaks a JSON line protocol; if that shared stdout with the
    agent, a single print() would crash grading for a NON-cheating submission.
    Printing is harmless in-process, so it has to be harmless here too."""
    inst = I.generate(0)
    ws = tmp_path / "ws_print"
    shutil.copytree(os.path.join(ENV_ROOT, "workspace"), ws)
    (ws / "pageforge" / "engine.py").write_text(textwrap.dedent('''
        import os, sys


        def layout(doc, cfg):
            print("debug: %d blocks" % len(doc.blocks))
            sys.stdout.write("more chatter\\n")
            os.write(1, b"raw fd-1 write\\n")
            return []
    '''))
    a, _ = GW.grade_workspace(str(ws), inst, isolated=True)
    b, _ = GW.grade_workspace(str(ws), inst, isolated=False)
    assert abs(a - b) < 1e-9, "printing changed the score (%.6f vs %.6f)" % (a, b)


def test_sandbox_is_faithful_for_a_correct_solution(tmp_path):
    """The real check on faithfulness: a CORRECT engine must score 1.0 through
    the sandbox, identically to in-process. A boundary that quietly corrupts
    documents or the config would show up here and nowhere else."""
    inst = I.generate(0)
    ws = tmp_path / "ws_gold"
    shutil.copytree(os.path.join(ENV_ROOT, "workspace"), ws)
    # engine B: an independent correct implementation, vendored as the agent's
    # own code (it must not import `generator` -- that is the whole point).
    src = open(os.path.join(ENV_ROOT, "generator", "interp_b.py")).read()
    # strip the oracle canary: it must never appear in an agent-visible file
    src = "\n".join(l for l in src.splitlines()
                    if "PAGEFORGE_ORACLE_SENTINEL" not in l)
    (ws / "pageforge" / "interp_b.py").write_text(src)
    (ws / "pageforge" / "engine.py").write_text(textwrap.dedent('''
        from .interp_b import layout as _b


        def layout(doc, cfg):
            return _b(doc, cfg)[0]
    '''))
    a, _ = GW.grade_workspace(str(ws), inst, isolated=True)
    b, _ = GW.grade_workspace(str(ws), inst, isolated=False)
    assert a > 0.99, "correct solution did not score 1.0 through the sandbox (%.4f)" % a
    assert abs(a - b) < 1e-9, "sandbox changed a correct score (%.6f vs %.6f)" % (a, b)
