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
