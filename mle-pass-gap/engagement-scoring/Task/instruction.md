Five modules under `src/engagement/` are empty. Every function in them raises
`NotImplementedError`, and until they are written the service will not start.

Write them so it produces what it produced before, to the last decimal.

What it produced before sits in `reference/`. There are the published scores, one row per
rating, and beside them two views of the features behind those scores:
`feature_profile.csv` summarises each feature across the whole run, and
`feature_sample.csv` gives every feature row by row for the first 500 ratings. All three
came out of `configs/reference.yaml`.

`SPEC.md` says what each quantity is for. It is written the way the desk talks about its
own model, so it carries no formulas. Where a definition could reasonably go more than one
way, the published run is what settles it.

Two of the tools rebuild those same tables from your own run, which is the quickest way to
see which features are off:

    python3 tools/profile_features.py --config configs/reference.yaml
    python3 tools/sample_features.py  --config configs/reference.yaml

`tools/compare_scores.py` diffs two score files.

The other config, `configs/current.yaml`, is the live scoring period. Same fit window,
later ratings, and nothing published to check yourself against. Both runs have to work
when you are finished:

    python3 run_scoring.py --config configs/reference.yaml --out out/reference
    python3 run_scoring.py --config configs/current.yaml   --out out/current

Everything outside those five modules is already written and is not yours to redo. Leave
the configs and the data as they are.
