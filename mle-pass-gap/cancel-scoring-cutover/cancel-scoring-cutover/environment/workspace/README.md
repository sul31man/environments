# Return risk scoring service

Scores each order line for the risk that the customer sends it back, so the warehouse can
hold the riskiest lines for a picking check before they ship. It runs nightly against the
overnight export and publishes a score per line plus a hold flag.

    python3 run_scoring.py --config configs/reference.yaml --out out/reference

## Layout

    run_scoring.py        nightly entry point
    SPEC.md               what the service computes, and how
    configs/              run configuration, one file per scheduled run
    data/                 the overnight export
    src/riskscore/        the service
    reference/            the published scores from the accepted backtest
    tools/                helpers for comparing runs

## Data

`data/orders.csv.gz` is the order line export. `returns.csv.gz` carries credit notes
raised against earlier lines; the label is derived by matching a credit back to the order
line it cancels, within the window `labelling.window_days`. `catalogue.csv` and
`accounts.csv` are slow moving reference tables.

An account id is absent on guest orders, which is a little under a quarter of lines.

The catalogue and the trading footprint both turn over: products are listed and delisted
continuously and markets open and close through the year, so a live run routinely scores
lines whose product, or whose market in that month, the fit window never traded.

How the desk treats those lines depends on the quantity. A **count** of past activity is
simply zero where there was none. But any quantity the service **averages or spreads over
that history** is undefined rather than zero, and the rule the business signed off is that
it is carried at the **portfolio average**: the mean of that same quantity over the keys
that do have history. For the return rate itself that is the portfolio rate the encoder
already shrinks toward.

None of those averages may be carried at zero. A zero there reads to the warehouse as a
settled, low risk line and sends it out unvetted, which is the failure this model exists
to prevent.

## Runs

`configs/reference.yaml` is the accepted backtest. Its published output is in
`reference/scores_reference.csv` with the run summary beside it, and the service is
expected to reproduce it exactly.

`configs/current.yaml` is the live run for the current scoring period. It fits on the same
history and scores a later window.

`SPEC.md` is the contract the service is built to.
