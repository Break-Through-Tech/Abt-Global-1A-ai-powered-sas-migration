# FASTCLUS seed selection and iteration

Python helpers that copy how SAS FASTCLUS picks starting seeds and updates cluster
centers in Program 2. They build on the helpers from PR #74 (`fastclus.py`).

These helpers are not connected to the model workflow. A model experiment that uses
them must be labeled helper-assisted and kept separate from the source-only baseline.

## What is confirmed and what isn't

Nothing here has been run on licensed SAS yet. "Documented" means the SAS docs say it.
"Inferred" means it follows from the docs but isn't stated directly. "Unresolved"
means the docs don't say, so the helper raises `UnresolvedSASBehavior`.

| Behavior | Status |
|---|---|
| First complete row is the first seed; missing rows are skipped | Documented |
| A new row becomes a seed if there's room and it's far enough from the others | Documented |
| SAS's two seed-replacement tests | Documented |
| Each round: assign to nearest seed, then move seeds to group averages | Documented |
| Stop when seeds stop moving (CONVERGE=0) | Documented |
| STRICT gives far-away hospitals a negative cluster number | Documented |
| Only the SEED= rows are used to pick seeds | Inferred |
| A replaced seed keeps its cluster number | Inferred |
| STRICT-excluded hospitals don't affect the averages | Inferred |
| Duplicate seed rows (the docs contradict each other) | Unresolved |
| A cluster that ends up empty | Unresolved |
| Hitting MAXITER before the seeds settle | Unresolved |
| A hospital exactly halfway between two seeds | Unresolved |

On the real July 2025 data, `program2_two_pass` (STRICT-excluded points leave the center
updates, signed labels, `abs()` star join) was run by the Program 2 reference through the
full pipeline: all three peer groups converged without ties, empty clusters or MAXITER, and
stars matched the supplied SAS artifact with 0 mismatches. That is consistent with July 2025
SAS outputs; the table above is unchanged because this is one data set, not SAS
documentation or a SAS run.

For Program 2, seed replacement probably never happens: each pass has at most five
different seed values and five clusters, so every value just becomes a seed. It
would only matter if two quintile medians were the same, which currently raises.

## How to use it

| Function | What it does |
|---|---|
| `select_initial_seeds(rows, maxc)` | Picks the starting seeds |
| `assign_nearest(scores, seeds, strict=None, on_tie=None)` | Puts each hospital in its nearest group |
| `run_fastclus(scores, seed_rows, maxc=..., maxiter=..., converge=..., strict=...)` | Runs one FASTCLUS pass |
| `program2_two_pass(scores)` | Runs both Program 2 passes and returns stars |

`on_tie` is where the equidistant rule will plug in once it's resolved.

## Open questions to test on licensed SAS

1. Duplicate seed rows: does SAS keep one seed or two?
2. Are extra seeds ever taken from the hospital data, not just the SEED= rows?
3. What happens to a cluster that loses all its hospitals?
4. If MAXITER is hit first, which centers does the macro reuse?
5. Do STRICT-excluded hospitals affect the averages?

## Sources

* [FASTCLUS Background](https://support.sas.com/documentation/cdl/en/statug/63962/HTML/default/statug_fastclus_sect002.htm)
* [FASTCLUS Background (9.2)](https://support.sas.com/documentation/cdl/en/statug/63033/HTML/default/statug_fastclus_sect002.htm)
* [PROC FASTCLUS statement options](https://support.sas.com/documentation/cdl/en/statug/63962/HTML/default/statug_fastclus_sect005.htm)
* Macro settings come from the team's Program 2 analysis doc; check them against `%kmeans` in `Star_Macros.sas`.

## Tests

Run `python -m pytest tests/test_fastclus_iteration.py`. The tests use small made-up
examples worked out by hand, not SAS output or real hospital data.