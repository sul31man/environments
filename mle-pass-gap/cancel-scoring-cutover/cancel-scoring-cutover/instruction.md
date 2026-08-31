The return risk scoring service is being moved onto a new runtime. The pipeline that runs
the service survived the move, but the modules that do the actual work did not: everything
under `src/riskscore/` that computes a feature, fits the segmentation or fits the model is a
stub that raises `NotImplementedError`.

Rebuild them so the service produces exactly what it produced before.

`SPEC.md` describes what the service is for and what each published quantity means, in the
terms the desk uses. It deliberately does not give formulas. Where a definition could be
written more than one way, the published reference run is the authority:

    reference/scores_reference.csv   what the service published, per line
    reference/feature_profile.csv    each feature summarised over that run
    reference/feature_sample.csv     each feature, row by row, for the first 500 lines

`configs/reference.yaml` is the run those were produced from, and a correct rebuild
reproduces all three exactly. `tools/profile_features.py` and `tools/sample_features.py`
produce the same two tables from your own run, and `tools/compare_scores.py` diffs two score
files.

`configs/current.yaml` is the live run for the current scoring period. It fits on the same
history and scores a later window, and it has no published output to compare against.

When you are done, both of these must run and both must be right:

    python3 run_scoring.py --config configs/reference.yaml --out out/reference
    python3 run_scoring.py --config configs/current.yaml   --out out/current

The pipeline, the config loader, the export reader, the design matrix, the checks and the
run summary are already in place and are not the work. Do not change the run configuration
or the data.
