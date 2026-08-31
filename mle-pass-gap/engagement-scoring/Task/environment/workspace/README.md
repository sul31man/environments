# Engagement scoring service

Scores each incoming film rating for how strongly the member engaged with the film, so the
editorial desk can pick what to surface in next week's recommendations. It runs nightly
against the overnight export and publishes a score per rating plus a promote flag.

    python3 run_scoring.py --config configs/reference.yaml --out out/reference

## Layout

    run_scoring.py        nightly entry point
    SPEC.md               what the service computes, and how
    configs/              run configuration, one file per scheduled run
    data/                 the overnight export
    src/engagement/       the service
    reference/            the published output from the accepted backtest
    tools/                helpers for comparing runs

## Data

`data/ratings.csv.gz` is the rating export, one row per rating with the stars awarded and
the engagement flag derived from them. `data/members.csv` and `data/films.csv` are slow
moving reference tables.

Membership turns over constantly: a live run routinely scores ratings from members who have
never rated before, and occasionally films that have never been rated before.

## Runs

`configs/reference.yaml` is the accepted backtest. Its published output is in
`reference/scores_reference.csv`, with the feature profile, a row level feature sample and
the run summary beside it.

`configs/current.yaml` is the live run for the current scoring period. It fits on the same
history and scores a later window.
