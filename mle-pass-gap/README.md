# MLE Pass-Rate Gap: Fable 5 vs Qwen 3.8 Max

This section collects MLE (machine-learning engineering) tasks where **Qwen 3.8 Max scored at
least 25 percentage points lower than Claude Fable 5 on mean pass rate over 8 independent runs**.
Each task ships with its full environment, grader, solution, and the complete agent traces for
both models (console log, transcript, grader output, and run metadata per run).

## Results

Pass = grader reward of 1.0. Runs are independent rollouts of the same task.

| Task | Fable 5 | Qwen 3.8 Max | Gap |
|---|---|---|---|
| [engagement-scoring](engagement-scoring/) | 8/8 (100%) | 1/8 (12.5%) | 87.5 pts |
| [cancel-scoring-cutover](cancel-scoring-cutover/) | 4/8 (50%) | 0/8 (0%) | 50 pts |
| [fleet-risk-task](fleet-risk-task/) | 7/7 (100%)* | 1/8 (12.5%) | 87.5 pts |

\* Seven Fable runs were archived for fleet-risk-task; all seven passed.

Note on metric: pass@8 in the strict sense (at least one success in 8 attempts) is saturated on
two of these tasks for both models. The gap reported here is **mean per-run pass rate**, which is
the quantity that separates the models. On cancel-scoring-cutover, Qwen's pass@8 is 0.

Qwen's failed runs are genuine attempts, not harness failures: on engagement-scoring 7 of Qwen's
8 runs stalled (six consecutive turns without a tool call), and on cancel-scoring-cutover 2 of 8
stalled; the remaining failures ran to completion and scored 0 on the grader. Fable 5 recorded
zero stalled runs on all three tasks.

## Layout

Each task folder contains:

- the task definition (instruction, environment workspace, tests, grader, reference solution,
  and `_private/` negative controls used for verifier QA)
- a traces folder with per-run subfolders for `Fable 5` and `Qwen 3.8 max`:
  `console.log`, `transcript.json`, `grader.log`, `run.json` (reward, stop reason, token usage,
  cost estimate)

Models were run through the same harness with identical task presentation; `run.json` in each
run folder records the exact model ID, provider, step counts, and stop condition.
