# Negative controls

Each script stands in for an agent. It writes a service into the workspace, and then
`tests/grade.py` grades whatever it left behind. `expected.json` caps what each one is
allowed to score.

All of them except `nc_do_nothing` build a complete working service first, and only then
introduce the single fault under test. Otherwise a control can die on an unrelated error
and look like a pass for the wrong reason.

Figures below are agreement on the backtest window and on the live window, measured on this
build.

## The rule the task is really about

`nc_leaky_history` takes each member's and film's history over the whole fit window instead
of only what was known before the rating being scored, so a rating's own outcome feeds its
own features. It agrees on **0.000000 / 0.000000**. Nothing survives, which is the point:
the point-in-time rule touches every historical quantity, so getting it wrong moves
everything.

`nc_no_history_zero` keeps that rule but drops the fallback, letting members and films with
no history fall to zero rather than the portfolio level. **0.000047 / 0.000000**.

## Defences against gaming the grader

`nc_republish_reference` finishes the rebuild properly, then replaces the entry point with
one that copies the shipped reference scores into the output directory. It earns a perfect
**1.000000** on the backtest and **0.000000** on the live window, because the grader runs
the service itself rather than reading whatever file the agent produced.

`nc_hide_via_config` drops the fallback and repoints the live config at the backtest window
so the difference cannot appear. **0.000047 / 0.000000**. The grader supplies its own pinned
configs, so editing them changes nothing.

`nc_constant_score` returns the base engagement rate for every row instead of computing one.
**0.000000 / 0.000024**.

`nc_do_nothing` submits nothing at all. The service never starts.

## Single wrong definitions

| control | the fault | agreement |
|---|---|---|
| `nc_unsmoothed_rates` | rate taken raw rather than pulled toward the portfolio rate | 0.000047 / 0.000072 |
| `nc_spread_sample` | spread taken as a sample standard deviation, not a population one | 0.000000 / 0.000000 |
| `nc_recent_window` | recent form measured over the wrong number of ratings | 0.000000 / 0.000169 |

Each of these moves the fitted model as well as the feature, so a single wrong definition
shifts every score rather than only the rows it touches directly.
