# PageForge

A **task-forced long-horizon**, tool-using coding environment: a two-phase episode
where the agent must first **discover** a hidden per-instance layout spec by
**probing** an oracle, then **implement** an ASCII typesetting/pagination engine to
the discovered semantics, graded by exact rendered-page match on a hidden corpus.

The env **withholds the per-instance cfg + semantics** and exposes them only through
a Phase-1 probe channel that feeds back results redirecting the next action, which
FORCES the four long-horizon conditions (verified across real frontier rollouts).

## Frontier model results

| Model | Mean reward | 95% CI | Strict pass@1 |
|---|---:|---:|---:|
| GPT-5.5 | **0.550** | [0.44, 0.66] | **0/12** |
| Opus 4.8 | **0.316** | [0.19, 0.45] | **0/12** |

Gold scores **1.0** and the strict-pass threshold is **0.95**. The broad 0.00–0.69 reward range shows a dense gradient even though neither model completes a strict solve.

**Framework-agnostic package.** No platform wrapper, no third-party dependencies --
pure Python stdlib. Drive it from any harness via [`pageforge_env.py`](pageforge_env.py)
(plain functions: `generate` / `spec_text` / `serve_probe_oracle` / `grade_workspace`
/ `purge_oracle`). The composition core (engine A/B, corpus, grader) is validated by
the offline proof suite below.

**Start here:** [`docs/WRITEUP.md`](docs/WRITEUP.md) -- what it is, task-forced
long-horizon verification, soundness battery, difficulty-by-construction, and the
full capability signal.

- [`docs/DESIGN.md`](docs/DESIGN.md) -- architecture: the 10 interacting families, oracle, grading
- [`docs/SEMANTICS.md`](docs/SEMANTICS.md) -- normative semantics of the composition core
- [`docs/SOUNDNESS.md`](docs/SOUNDNESS.md) -- soundness receipt: FAR 0/100, FRR 0/25, differential oracle, difficulty
- [`docs/ISOLATION.md`](docs/ISOLATION.md) -- oracle isolation: recorded leak probe on a deployed container

## The two phases

- **Phase 1 (discovery):** `from probe import probe; probe(doc)` returns the
  reference rendered pages for the agent's OWN document. The cfg and semantics are
  hidden; the agent infers every form by probing. Facets are interdependent
  (unobservable until prerequisites are pinned) -> a 15-30 step forced chain. Budget
  is finite; graded-corpus docs are refused; the oracle source is not on disk.
- **Phase 2 (implement + grade):** edit `workspace/pageforge/engine.py` to the
  discovered semantics; graded by exact rendered-page match on the hidden corpus,
  with the probe oracle purged.

## Run (offline, no dependencies or API key)

```bash
python3 pageforge_env.py             # standalone self-check: generate -> probe -> grade
python3 -m private.slice_check       # composition core: A==B differential oracle
python3 -m private.full_check           # full-scale (50): core + discovery chain + OOD + gate
python3 -m private.discovery_chain   # deep/chained discovery: masking edges + 21-probe accounting
python3 -m private.phase_demo        # two-phase adapter end-to-end
python3 -m private.deploy_sim        # deployable isolation (container lifecycle)
python3 -m private.soundness         # FAR/FRR cheat battery + regrade + difficulty
python3 -m private.phase_soundness      # two-phase: faithful=1.0, oracle-reader-at-grade fails closed
python3 -m private.ood_proxy         # OOD via fair-familiar proxy (0/50 pass)
python3 -m pip install pytest && python3 -m pytest private/leak_test/ -q   # process isolation, two-condition
```

Verified on CPython 3.9, 3.11 and 3.12. Everything except the `pytest` line is
stdlib-only and needs no install; run from the package root.

## Layout

```
pageforge_env.py   framework-agnostic adapter: generate / spec_text / serve_probe_oracle / grade_workspace / purge
generator/         engine A (reference) + engine B (independent differential oracle) + enumerator + grader
                   + probe_oracle/probe_server (Phase-1 in-memory oracle over a unix socket)
                   + sandbox: process-isolated grading (agent code runs with no oracle)
workspace/         agent package: pfcore/semconfig + engine.py stub + probe.py (pure-IPC Phase-1 client)
private/           offline proofs (stdlib only): slice_check, full_check, discovery_chain, phase_demo,
                   deploy_sim, soundness, phase_soundness, ood_proxy
                   + check_trace_isolation: the isolation receipt -- audits a recorded
                     leak-probe trace from a deployed container (takes <trace.txt>)
                   + leak_test/: two-condition process-isolation tests (pytest)
docs/              WRITEUP, DESIGN, SEMANTICS, SOUNDNESS, ISOLATION
```

**Serving model (any harness).** Boot: load the oracle to memory and start the probe
server, then `purge_oracle()` deletes `generator/`,`private/`,`docs/` from disk so the
agent reaches the oracle ONLY through the socket (fail-closed via `assert_isolated`).
Phase 2 grades the workspace with the oracle source gone. `private/deploy_sim.py`
demonstrates the full container lifecycle offline.
