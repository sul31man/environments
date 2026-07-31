"""Deployable-isolation proof, offline (faithfully models the served container).

Reproduces the container lifecycle without any platform or a paid run:
  boot  -> import engine A + generate instances into THIS process's memory; start
           the real ProbeServer on a unix socket.
  purge -> rmtree the container's generator/ copy (engine A source gone from the
           agent-visible disk); workspace/ (incl. the pure-IPC probe client) stays.
  agent -> a subprocess with the container as its filesystem:
           (1) probes the oracle via workspace/probe.py -> receives pages (works);
           (2) cannot cat engine A source (purged);
           (3) cannot import generator.engine (purged);
           (4) is refused when probing a graded-corpus doc;
           (5) hits the probe budget.
The oracle process keeps engine A in memory; the agent reaches it ONLY through the
socket, which returns rendered pages -- never source. So A1-A7 hold by
construction: nothing on the agent's disk to leak.

Run:  python3 -m private.deploy_sim   from the package root.
"""
from __future__ import annotations
import os, sys, shutil, subprocess, tempfile, textwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import instance as I
from generator.probe_server import ProbeServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    print("=" * 64)
    print("PageForge -- deployable-isolation proof (offline container sim)")
    print("=" * 64)
    inst = I.generate(0, "eval")
    tmp = tempfile.mkdtemp(prefix="pf2_container_")
    sock = os.path.join(tmp, "probe.sock")

    # boot: oracle in THIS process's memory; start the real server
    server = ProbeServer.from_instances([inst], budget=3, sock_path=sock).start_background()

    # container filesystem: copy generator/ + workspace/, then PURGE generator/
    shutil.copytree(os.path.join(ROOT, "generator"), os.path.join(tmp, "generator"))
    shutil.copytree(os.path.join(ROOT, "workspace"), os.path.join(tmp, "workspace"))
    shutil.rmtree(os.path.join(tmp, "generator"))              # <- serve-time purge
    print("\n[purge] generator/ removed from the agent-visible container disk")

    # the agent runs inside the container (workspace on the path, socket + index set)
    agent = os.path.join(tmp, "agent.py")
    with open(agent, "w") as f:
        f.write(textwrap.dedent("""
            import os, sys
            from pageforge import pfcore as C
            from probe import probe, ProbeRefused
            # (1) a normal probe works
            pages = probe(C.doc(C.para("p", [C.W("x"*25)])))
            print("PROBE_OK", len(pages), repr(pages[0].split(chr(10))[0]))
            # (2) cannot read engine A source
            print("CAT", os.path.exists("generator/engine.py"))
            # (3) cannot import the oracle. Report WHERE it would resolve from
            # before trying, so an installed-copy leak diagnoses itself instead
            # of looking like a broken simulation.
            import importlib
            from importlib.machinery import PathFinder
            importlib.invalidate_caches()
            _spec = PathFinder().find_spec("generator", sys.path)
            if _spec is not None:
                print("IMPORT_REACHABLE_FROM", _spec.origin)
            try:
                import generator.engine  # noqa
                print("IMPORT UNEXPECTED_OK")
            except Exception as e:
                print("IMPORT_BLOCKED", type(e).__name__)
        """))
    env = dict(os.environ, PYTHONPATH=os.path.join(tmp, "workspace"),
               PF_PROBE_SOCK=sock, PF_TASK_INDEX="0")
    out = subprocess.run([sys.executable, agent], cwd=tmp, env=env,
                         capture_output=True, text=True)
    print("\n[agent subprocess -- filesystem = purged container]")
    for line in out.stdout.strip().splitlines():
        print("  " + line)
    if out.returncode != 0:
        print("  STDERR:", out.stderr.strip()[:300])

    # (4)+(5) corpus refusal + budget, over the raw socket (server-side properties,
    # using the server's own plain-data path).
    import json, socket as _socket
    from generator import pfcore as GC

    def raw_probe(plain_doc):
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.connect(sock)
        s.sendall((json.dumps({"index": 0, "doc": plain_doc}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(65536)
        s.close()
        return json.loads(buf.split(b"\n", 1)[0].decode())

    refused = not raw_probe(GC.to_plain(inst.corpus[0][0]))["ok"]
    print("\n[corpus refusal] refused a graded-corpus doc: %s" % refused)
    # budget=3: 1 used by the agent subprocess; exhaust the rest with normal probes.
    normal = GC.to_plain(GC.doc(GC.para("p", [GC.W("y" * 25)])))
    budget_hit = False
    for _ in range(5):
        if not raw_probe(normal)["ok"]:
            budget_hit = True
            break
    print("[budget] probe budget enforced after exhaustion: %s" % budget_hit)

    server.stop(); shutil.rmtree(tmp, ignore_errors=True)

    ok = ("PROBE_OK" in out.stdout and "CAT False" in out.stdout
          and "IMPORT_BLOCKED" in out.stdout and refused and budget_hit)
    print("\n" + "=" * 64)
    print("DEPLOYABLE ISOLATION: %s" % (
        "PASS (probe works via socket; engine A source unreadable + unimportable; "
        "corpus refused; budget enforced)" if ok else "CHECK FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
