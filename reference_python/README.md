# Human-reference programs

This directory contains reference Python implementations derived directly from the
supplied SAS semantics for bounded comparison prototypes. These are the plan's
human-reference baselines, kept separate from model-backed translation experiments
and their generated outputs.

`mortality.py` reproduces the supplied Program 1 Mortality `grp_score` calculation from
the supplied Program 0 standardized SAS binary. It writes `OUTCOME_MORTALITY.csv` for
the trusted host controller to compare with the SAS binary. The trusted output is not
available to this program inside the isolated Docker runner. The controller snapshots
this script and the input into the run directory, verifies their hashes against the
original files, then runs those snapshots in Docker. The first run passed for all
4,566 rows and 21 columns.

Run it through the repository controller from the project root:

```sh
sasguard mortality-prototype --project-root . --image sasguard-runner:test
```

See [`docs/mortality-prototype.md`](../docs/mortality-prototype.md) for setup, the
column-level comparison policy, integrity checks, report contents, and scope limits.

## Domain scoring and Program 2

`domain_scoring.py` is the Program 1 human reference (five domain group scores).

`program2.py` is the Program 2 reference: weighted summary score, reporting eligibility,
per-peer-group K-means stars (reusing `sasguard.semantics` FASTCLUS helpers) and national
averages. It reads only the Program 1 CSVs and Program 0's `std_data_2025jul_analysis.csv`
and writes `star_2025jul.csv` and `national_average_2025jul.csv`.

Review status: not written by a team member; pending teammate review. The pipeline command
always labels it `helper_assisted_model_output`. A teammate review is recorded separately
with `--program2-reviewed-by "<name>"` and does not change that origin. On the real July 2025 chain it matched both SAS artifacts, with no
unresolved FASTCLUS behavior hit. See
[`docs/full-pipeline-validation.md`](../docs/full-pipeline-validation.md).

```sh
sasguard validate-pipeline --run-human-references --run-reference-program2
```
