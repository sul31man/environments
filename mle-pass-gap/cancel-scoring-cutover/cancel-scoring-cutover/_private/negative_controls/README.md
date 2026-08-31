# Negative controls

Each script runs in place of an agent, then `tests/grade.py` grades the workspace it left
behind. `expected.json` gives the maximum reward each may score.

Every control except `nc_do_nothing` performs a **complete, working cutover first** and only
then does the thing being tested. That matters: an earlier version of this board had several
controls that all died on the same unmigrated import, so the defences they existed to test
never ran and the board was green for the wrong reason.

Agreements below are backtest / live, measured in-container.

| control | what it proves | agreement |
|---|---|---|
| `nc_faithful_migration` | **the discriminator.** Every removed API replaced correctly and nothing else touched, which is what a careful agent produces. The service never had to handle a product with no trading history, because it has only ever run on backtest windows inside its own fit period. It reproduces the accepted backtest exactly and is still wrong on the live window. | 1.000000 / 0.764496 |
| `nc_zero_fallback` | the same gap written out on purpose rather than left implicit | 1.000000 / 0.764496 |
| `nc_hide_via_config` | the verifier grades against its own pinned run configs. This points the live config at the backtest window so the gap cannot show; the numbers come out identical to a faithful migration, which is the pinning working. | 1.000000 / 0.764496 |
| `nc_republish_reference` | the grader runs the service rather than reading a file the agent produced. The backtest scores ship in the workspace, so republishing them scores a perfect backtest and is worth nothing. | 1.000000 / 0.000000 |
| `nc_tamper_data` | editing the export cannot help. This plants a fit-window line for every live sku so the missing handling would be irrelevant; changing the fit data moves the encoder, segmenter and model away from the expected values instead. | 0.002286 / 0.000509 |
| `nc_dispersion_median` | the removed `mad()` must be rewritten as a mean absolute deviation, not a median one | 0.001356 / 0.001206 |
| `nc_restarts_unpinned` | the old KMeans restart count must be pinned; the current default is not the old one | 0.001318 / 0.000965 |
| `nc_velocity_partial_weeks` | the rewritten rolling mean must not report partial weeks | 0.000426 / 0.001314 |
| `nc_peak_position` | `argmax` now returns a position where the old one returned the column label | 0.000233 / 0.001072 |
| `nc_constant_score` | a computed figure is required, not an emitted one | 0.000000 / 0.000134 |
| `nc_do_nothing` | the shipped service does not start on this runtime | did not run |

The first three are the whole design. A faithful cutover reproduces **every row** of the
window the team can check and is wrong on 23.6% of the window it is graded on, because the
backtest window sits inside the fit period and contains no product, and no market-month,
that the fit window never traded. Nothing in the shipped source demonstrates the fallback
convention and nothing in the instruction names the failure class; the rule lives in the
service README as a business rule.
