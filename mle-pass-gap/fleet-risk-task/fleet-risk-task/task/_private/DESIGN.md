# fleet-risk-scoring - design note (NOT shipped)

Task 5. First one built under the standard where the weak arm needs 1/4 or 2/4, so the
design is aimed at the only build we own that landed in band: `engagement-scoring` at 9
stubs across 5 modules, which scored qwen 1/3.

## Why this shape

Four measured weak results across two tasks:

    cutover      46 stubs / 18 modules    qwen 0/3
    cutover      23 stubs /  8 modules    qwen 3/3
    engagement   19 stubs / 13 modules    qwen 0/3
    engagement    9 stubs /  5 modules    qwen 1/3

Size does not predict the outcome. What separates them is whether a rule that governs
everything survives the cut. Cutting cutover left transcription; cutting engagement left a
small surface plus point-in-time correctness, which cannot be shrunk away.

So: small mechanical surface, one rule that touches every row, stated in the spec and
visible in the published run.

## Substrate: BTS On-Time Performance, Jan to Mar 2024

US DOT, public domain. No redistribution or commercial restriction, which matters after the
MovieLens finding on `engagement-scoring`.

    1,651,689 flights, 5,781 aircraft, 110 columns available
    median 97 flights per tail, 10th percentile 24
    cancellation rate 3.73%, diversion 0.28%

Recurrence is ample for per-aircraft history features.

## The gate: label censoring, measured

The label is forward looking: did this aircraft suffer a cancellation within 3 days. A
flight in the last 3 days of the shipped data has no observable answer, so it must not be
trained on. Keep it and it is labelled negative by default.

Censored rows carry a base rate 25 times lower than observed rows, because their outcome
window is truncated:

    horizon   base rate   censored   observed base   censored base   ratio
    2 days      0.1098      6.17%       0.1168          0.0034       0.03
    3 days      0.1471      9.57%       0.1620          0.0064       0.04
    5 days      0.2079     15.84%       0.2447          0.0125       0.05
    7 days      0.2579     22.72%       0.3273          0.0217       0.07

(shares above are for a single month; over the full three months a 3-day tail is 3.48%.)

**Decisive against exact reproduction.** Training with the censored tail against training
without it, then scoring the same window:

    rows fitted     correct 1,594,186   wrong 1,651,689   (+57,503, 3.48%)
    agreement       0.000085
    mean abs diff   0.005501
    max abs diff    0.148839

Essentially every scored row moves. The grader threshold is 0.999 agreement, so a wrong
training set fails outright. One rule, and it shifts the fitted model rather than only the
rows it touches, which is the property that made point-in-time work.

**Discoverable by diligence, not insight.** The published run report carries `rows_fitted`.
Train on the tail and that number does not match. No hidden information, which is what
CONTRIBUTING requires and what separates a 1/3 from a 0/3.

## Chosen parameters, all measured

    carriers       WN, AA, DL, OO   (three mainline, one regional)
    rows           974,960          matches engagement-scoring's proven 1M
    aircraft       3,178            median 97 flights each
    horizon        3 days
    data shipped   2024-01-01 .. 2024-03-31
    censored tail  after 2024-03-28, 33,711 rows, 3.46% of the fit window
    label base     0.0824           better conditioned than cutover's 0.0217

Carrier subset chosen by measurement. The four largest carriers give a 0.0629 base rate
because big operators cancel less; swapping UA for the regional OO lifts it to 0.0824 at
the same row count, and makes carrier a genuinely informative feature rather than noise.

## Gate confirmed on the shipped subset

    rows fitted     correct 941,249   wrong 974,960   (+33,711)
    agreement       0.000106
    mean abs diff   0.005963
    max abs diff    0.137990

3.46% of training rows contaminated moves 99.99% of scored rows past 1e-6. The grader
threshold is 0.999, so a wrong training set fails outright.

## Open build decisions

- **Data size.** 1.65M rows is larger than either shipped task (367k and 1M). Needs either
  two months, a carrier subset, or a column trim to land near the 11MB the other tasks ship
  and keep the run under about a minute at 2 vCPU.
- **Windows.** Backtest and live to be chosen by measurement, not picked.
- **Secondary hazards available on this substrate**, as plainly stated work rather than
  second gates: cancelled flights carry no arrival time, the delay-cause columns are
  null-means-zero, and local HHMM times wrap past midnight.

## Shipped export, built

    flights.csv.gz     962,976 rows   18.1 MB   operated flights, the rows that get scored
    groundings.csv.gz   11,984 rows    0.1 MB   cancellation events, tail and timestamp
    fleet.csv            3,178 rows             aircraft register, operator and home station
    stations.csv           275 rows             airport reference

Cancelled flights are not in the flight log. They appear only as groundings, so the label
has to be derived by matching groundings back to the flights that precede them, the way
`cancel-scoring-cutover` derives returns from credit notes. Nothing is minted.

## Windows, measured

    fit               2024-01-01 .. 2024-03-31    962,976 rows before censoring
    censored tail     after 2024-03-28            33,648 rows, 3.49%
    reference score   2024-02-05 .. 2024-02-06     20,606 rows, 2,740 aircraft
    current score     2024-03-18 .. 2024-03-21     45,567 rows, 2,871 aircraft
    labelling window  3 days

Window sizes deliberately track the two tasks that were accepted: cutover scored 23,590 and
37,303, engagement scored 21,280 and 41,442. Both scored windows sit inside the fit period,
which is fine here because the gate shifts the fitted model rather than the scored rows, so
it moves every score in both runs.

## Module layout, target

Mirrors `engagement-scoring` at 9 stubs across 5 modules, the only build we own that landed
in band. Plumbing ships working so the service runs several steps before the first stub,
which is what separated engagement's 1/3 from cutover's 0/3, where the very first call in
the pipeline was a stub and the weak arm died on it.

    given     config, io_layer, pipeline, assemble, report, validate,
              calendar_feats, fleet_profile, station_profile, route_feats,
              model, portfolio
    stubbed   observation (the censoring gate), tail_history, station_history,
              reliability, recent

## Fleet sampled to 60%, to protect the weak arm from the clock

The first build shipped all 962,976 flights and ran in 44.5s per config. Profiling where
that went:

    read flights        4.5s
    attach_label       16.4s   the per-aircraft label search
    features and fit   ~24s

That is **1.6x `engagement-scoring`'s ~28s**, and both diagnostic tools rebuild the whole
pipeline, so every profile check costs a full run. A weak model that spends its budget
probing could exhaust 150 steps on wall clock rather than on difficulty, which reads as 0/4
and is exactly the outcome the current standard fails.

Worse, 16.4s of that is the oracle's own label search. An agent's first attempt at the same
thing is often a row-wise `apply`, which is far slower still. Shrinking the data is the only
mitigation that helps whatever the agent writes, rather than only helping gold.

    fleet share    rows      tails   est run
    100%           962,976   3,178    44.5s
     70%           679,652   2,224    31.4s
     60%           578,195   1,906    26.7s   <- chosen
     50%           479,461   1,589    22.2s

Sampling is on **whole airframes** with a fixed seed, so no aircraft carries a truncated
history. Three months, four carriers and the temporal structure are all preserved; only the
number of tails drops. 1,906 aircraft at a median 97 legs each is still ample for
per-aircraft history features.

## A dead code path found by the board, and removed

The first full board failed on one control: `nc_zero_fallback` scored **1.0**, meaning the
fault it introduced had no effect. The profile said why:

    f_tail_is_new         mean 0.000000   std 0.000000
    f_station_pair_known  mean 1.000000   std 0.000000

Both scored windows sit inside the fit period, so every aircraft and every station is
already known. The cold-start fallback could never fire. That made three things wrong at
once: two features carried no information, `SPEC.md` section 5 stated a rule the published
run cannot exercise, and the control testing that rule proved nothing.

This is the same fault as `cancel-scoring-cutover`'s section 4, caught here by the board
rather than by a reviewer.

Fixed by deleting the dead surface rather than by contriving a window that exercises it:
the two features are gone (40 down to 38), section 5 now documents only the **-1** marker
for airframes never grounded, which does fire, and the control is dropped. The task keeps
exactly one rule that decides the outcome, which is the design.

**Three features remain constant on the backtest and that is fine.** `f_month`, `f_week` and
`f_is_weekend` do not vary across four consecutive weekdays in one month, but unlike
`f_tail_is_new` their computation is fully exercised: they come from each row's own
timestamp, and a wrong implementation changes the whole fit window and therefore every
published score. A constant feature is only a problem when it hides an unexercised branch.

## An answer key left in the workspace by my own testing

The pre-packaging audit found `environment/workspace/out/` still present, holding:

    out/reference/scores.csv    the backtest, which is published anyway
    out/current/scores.csv      the live window, which is not

The second one is the complete answer to the half of the grading the agent cannot see. It
got there from the very first manual run during the build, `run_scoring.py --out
out/reference`, and it survived every later rebuild because the artefact script stages into
a temporary tree and never touched the workspace copy.

Nothing in the board would have caught it. The board grades a staged copy, and a correct
answer sitting in the workspace does not change what the pipeline computes. It would have
shipped.

Guarded three ways rather than one, because remembering not to leave it is not a control:

- `environment/.dockerignore` excludes `workspace/out/**`
- the Dockerfile refuses to build if `/workspace/target/out` exists
- `rebuild_artifacts.py` clears `out/` and every `__pycache__` before it syncs

Verified after the fix: nothing verifier-side is reachable from the workspace, and the
published backtest shares **zero** flight ids with the 40,381 rows the grader holds back.

The general lesson: a leak audit has to look for what the build process leaves behind, not
only for what the design puts there. The design never put `out/` in the workspace; a test
run did.

---

# Rebuild after the 4/4 rejection

The first evaluation came back weak 4/4 with difficulty soundness 1/5 and long-horizon
qualification 2/5. Both findings are the same defect seen from two sides, and the traces say
what it was.

## What the traces show

All four runs solved it, in 55, 87, 90 and 95 steps. The 55-step run is the clearest.

It read the workspace, probed the export for about forty steps, then wrote three modules and
ran this:

    python3 tools/sample_features.py --config configs/reference.yaml --out /tmp/sample_mine.csv
    bad cols: [('f_dest_prior_flights', 498, 60.0),
               ('f_dest_grounding_rate', 396, 0.00018),
               ('f_recent_grounding_rate', 392, 0.012988)]

Three of the nine definitions were wrong. The shipped sample named all three, and one rewrite
later:

    bad cols: NONE

The other three runs did the same thing, referring to the sample or the profile 41, 54 and 61
times each. The task was not asking the model to infer nine definitions from a prose spec. It
was asking it to fit nine columns against a published answer key, one column at a time, with
per-row feedback on every attempt.

Three separate copies of that key shipped:

    reference/feature_sample.csv    500 rows x 38 exact feature values
    reference/feature_profile.csv   count, nulls, mean, std, min, p25, p50, p75, max
    reference/run_report.json       feature_spread, the per-feature standard deviation

Any one of them collapses the task. All three are gone. What remains is
`reference/scores_reference.csv` and the run summary, which is the honest version of the
re-run-and-compare contract: the signal is end-to-end and joint, so a single wrong definition
shows up as a failed run rather than as a named column.

## The second half: nothing to correct against

The same run also printed this, at step 97:

    current rows: 40381 unseen tails: 0 unseen origins: 0 unseen dest: 0

The agent checked and found the live window exercised nothing the backtest did not. That is
the dead path recorded further up this note, and deleting the two constant features closed
the symptom without closing the hole: once the backtest matched, the run was over. There was
no act, observe, correct depth after the first correct run because there was nothing left to
be wrong about.

The export ends on the same day the fit window did, which is why both scored windows had to
sit inside the fit period. Fixed by shortening the fit window rather than by minting data:

    fit               2024-01-01 .. 2024-02-15
    backtest score    2024-02-05 .. 2024-02-08    inside the fit window, published
    live score        2024-03-25 .. 2024-03-31    six weeks past the end of it

Measured on the live window against that fit:

    rows                47,096
    unseen aircraft        581 rows across 24 tails
    unseen origin            9 rows
    unseen route           323 rows

## Censoring re-anchored so it survives the shorter fit window

The observation rule dropped flights within the labelling horizon of the **export** end. With
the fit window no longer running to the export end, that rule stops removing anything and
`rows_fitted` stops being a puzzle.

It is now anchored on whichever of the two ends first, which is the more defensible rule
anyway: SPEC section 1 already says everything is learned from the fit window only, so a
flight whose outcome is settled after the fit window ends cannot be labelled from what the
service is allowed to read. The old behaviour is the special case where the two coincide.

    rows_fitted   262,881 of 281,152 in the window

The agent has to work out which of the two ends binds. `rows_fitted` settles it, so it is a
search with a published target rather than a guess.

## The discriminator, measured

`nc_zero_fallback` is back, and this time it is not dead. It builds the service correctly and
then drops an unseen aircraft to zero on every quantity instead of standing it at the fleet
level:

    backtest 1.000000    live 0.987218

That is the property the task was missing. A build can be perfect on the only window the
agent can check and still fail on the one it cannot. 581 rows out of 47,096 is 1.2%, and the
gate is 0.999.

## Made discoverable, not hidden

Difficulty soundness also fails when the answer is not fairly discoverable, so the rule the
live window tests is now stated. SPEC section 5 covers both cases in words and no formulas:
a quantity measured over history a leg does not have stands at the fleet-wide level, counts
are the exception and record zero, and time since the last grounding keeps the -1 marker.

## Ordered checkpoints, so progress is observable

Removing the per-feature key would leave a single all-or-nothing gate, which is difficulty
without depth. The run summary now carries the stage-level figures instead, none of which is
a feature definition:

    rows_scored          the score window selection
    label_rate_scored    the two-feed label join, on rows censoring does not touch
    rows_fitted          the observation rule
    tails_fitted         the fit set, cross-checked a second way
    mean_score           the model
    watch_rate           the threshold

`label_rate_scored` is the useful addition: the scored window is never censored, so it
validates the label join on its own, ahead of and independently of the observation rule. The
chain is label, then censoring, then nine definitions, then the model, and each link reports
before the next one can be judged.

## Stubs

Unchanged at 9 across 5 modules. Lesson 57 holds: size does not move the weak arm. What moved
here is that the answer is no longer published alongside the question.

Function docstrings are no longer copied into the skeletons either. `tail_history.history`
was shipping "Per aircraft: how much it flew, how often it was grounded, and how recently",
which is three of the six columns it has to produce.

## Live rank quality is the regime, not the window

The grader reports rank quality alongside agreement. It is informational; reward is exact
reproduction on both windows and nothing else. On this build it reads:

    backtest   AP 0.850329   AUC 0.998337
    live       AP 0.024708   AUC 0.582348

Groundings are not spread evenly. Mid-January carries about 1,900 a week and late February
carries 44, so the weekly label rate runs from 0.010 to 0.336 across the export. The fit
window is dominated by the January cluster and the live window sits six weeks past it, with
every aircraft, station and recent-form quantity still anchored at the fit end because
SPEC section 1 says the service learns from the fit window only.

Checked against the alternatives before keeping it, fitting once and scoring three windows:

    2024-03-10 .. 03-16   label 0.0953   unseen 0.78%   AUC 0.5489
    2024-03-18 .. 03-24   label 0.0477   unseen 0.93%   AUC 0.4626
    2024-03-25 .. 03-31   label 0.0180   unseen 1.35%   AUC 0.5823   <- kept

All three sit near chance, so this is the substrate rather than a bad pick, and the one kept
has both the best rank quality and the widest unseen coverage. It does not touch grading: the
agent has to reproduce the oracle's numbers whatever those numbers rank like, and the
controls separate on the live window at 0.031 to 0.987 against a 0.999 gate.

---

# Third rejection: the difficulty was pinned, not discovered

Weak went 3/4, 4/4, 2/4 across three evaluations. The 2/4 was not the concept getting
harder; two of those attempts timed out. Two blockers, and they are the same defect.

## What the review found

The evidence below is quoted from the reviewer's report, not from traces read here; the
traces on disk are the earlier 4/4 set. What is measured on this bench is in the next
section.

The published summary carried four scalars that between them settled both ambiguous
decisions in the task:

    rows_fitted         262881      the censoring cutoff
    label_rate_fitted   0.115432    the label interval convention
    label_rate_scored   0.010598    the same convention, a second way
    tails_fitted        1880        the fit set, a second way

Per the report, run-03 solved it in 16 steps for $0.32, printing a match search:

    dep+w<=fit_hi 262881 / dep+w<fit_hi 262881 / all 281152

read off which candidate hit the published number, and locked it in. It did the same with
`label_rate_fitted` to pick the boundary convention. No reasoning about what the rule meant,
just scalar matching against numbers handed over up front.

**Two of those four scalars were mine, added one round earlier.** I put `label_rate_scored`
and `tails_fitted` in as stage-level checkpoints, on the reasoning that an aggregate is not a
feature definition and so cannot be an answer key. That reasoning was wrong. An aggregate
that stands in one-to-one correspondence with a binary convention **is** the answer to that
convention, and a scalar is a cheaper thing to match against than a column.

## The fix, and the measurement that says it holds

All four are gone. What remains in the summary is derivable from the published scores file
itself, so it pins nothing:

    fit_window, score_window, rows_scored, watch_rate, mean_score

SPEC section 3 no longer names a number to reproduce. It states the principle and stops.

The requirement was that each decision still has to surface through the gradable output, or
removing its scalar makes it undiscoverable rather than discoverable. Both do, measured on
this build:

    nc_keep_censored     backtest 0.699077   live 0.029578    30% of scored rows move
    nc_label_boundary    backtest 0.754443   live 0.162795    25% of scored rows move

So a wrong cutoff and a wrong interval convention each visibly corrupt the reproduction. The
agent has to build it, run it, read the disagreement off `compare_scores.py`, form a
hypothesis and try again. That is the act, observe, correct loop the second blocker asked
for, and it now sits on the only channel that is left.

`nc_label_boundary` is new. The convention it breaks was previously pinned by
`label_rate_fitted`, so there was nothing to control for.

**The censoring boundary itself is unambiguous and that is deliberate.** All three plausible
boundary conventions select the same 262,881 rows, because no flight departs exactly on the
edge. Only the presence or absence of censoring changes anything, so the agent is not being
asked to guess between indistinguishable variants.

## The reviewer's non-blocker, and why it is worth more than that

The note was that `HistGradientBoostingClassifier` at 262,881 rows triggers
`early_stopping='auto'`, so reproduction to 1e-3 leans on thread-count and BLAS determinism.

`climate-normals` proved that concern is real and worse than it looks. Two mathematically
correct implementations of a trailing window differed by **4.3e-14**, because pandas carries
an incremental running sum and a hand-rolled version recomputes each slice. A binned model
bins on those values, one of them crossed a bin edge, and the reproduction fell from 1.0 to
**0.0508** with a maximum score difference of 0.267. Correlation stayed at 0.985. The task
was grading floating-point summation order rather than the rule.

I assumed fleet was safe because its features are groupby counts and means that come out
bit-identical across implementations. Measured, that assumption is wrong. Comparing the
assembled design matrices from the three shipped solutions:

    gold vs alt    206,938 of 9,989,478 cells differ   max abs diff 5.55e-17
    gold vs alt2   206,938 of 9,989,478 cells differ   max abs diff 5.55e-17

Fleet is not exact either. It differs by about one ULP where `climate-normals` differed by
about eight hundred, and at that size no value happened to land on a bin edge. Both alternates
still reproduce at 1.0, so the task is sound today, but it is sound **by margin rather than by
construction**, and the margin is not something the design controls.

That is worth stating plainly rather than filing as a curiosity. An agent whose aggregation
order differs a little more than these two do is not guaranteed the same luck.

Switched off here (`early_stopping=False`), which removes the validation-split dependence the
reviewer named and one source of run-to-run variation. It does not remove the binning
sensitivity, which is inherent to a tree model on continuous features. Recorded rather than
hidden: if a future evaluation shows an unexplained near-miss on this task, this is the first
thing to check, and the fix is the one `climate-normals` now uses, a smooth estimator whose
output moves by 1e-10 when its input moves by 1e-14.
