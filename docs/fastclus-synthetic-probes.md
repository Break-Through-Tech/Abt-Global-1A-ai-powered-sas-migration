# FASTCLUS synthetic probes

This adds small human-written helpers for the documented percentile and label rules
in Program 2. It does not implement FASTCLUS iteration or establish SAS parity. The
helpers are not wired into a model prompt, candidate, runner or validator. Issue #69
remains open, and the Program 2 baseline in #70 still has two incorrect stars.

## Evidence and tested cases

| Rule | Synthetic counterexample | Evidence |
|---|---|---|
| Unweighted PCTLDEF=5 | The 20th percentile of 10, 20, 30, 40, 50 is 15, not the result of linear interpolation. Integer n*p positions average adjacent observations. | SAS UNIVARIATE percentile definition 5 |
| Missing observations | None and numeric NaN do not contribute to percentiles or interval medians; zero remains an observed value. | SAS definition uses the nonmissing sample; supplied macro's explicit missing-score guard |
| Initial interval medians | Scores 1 through 10 produce medians 1.5, 3.5, 5.5, 7.5 and 9.5 in interval order even when input rows are reversed. | Supplied macro's upper-inclusive intervals and PROC MEANS by GRP |
| Empty intervals | Five ones and five twos occupy intervals 1 and 3. Do not invent a median or treat these GRP labels as FASTCLUS cluster identifiers. | Supplied interval conditions; subsequent seed selection remains separate |
| STRICT distance | Distance equal to 1 is accepted; the next representable value above 1 has a negative output ID under STRICT=1. | FASTCLUS rejects distances exceeding STRICT |
| Signed labels and stars | An outlier with cluster -2 has the same final star as cluster 2 after ABS and the center-order join. A low center can belong to cluster 5. | FASTCLUS output definition and supplied macro's ABS/ordered-center merge |

`percentile_definition5` accepts integer percentages, matching this macro's 20, 40, 60
and 80 requests. It uses integer n*percent arithmetic before division by 100. Thus a
58th percentile of 50 observations is not misclassified because binary 0.58*50 is just
below 29. This does not specify arbitrary fractional-percent or weighted SAS behavior.

The Python boundary rejects an all-missing sample, infinite values, zero-based cluster
IDs, unknown cluster mappings and tied final centers. Those rejections are deliberate
helper limits, not assertions that SAS raises the same errors. Missing assignments
remain unassigned. The helpers accept known nearest-cluster distances; they do not
choose between equidistant seeds or update centers.

## Source references

* [UNIVARIATE calculating percentiles](https://support.sas.com/documentation/cdl/en/procstat/63104/HTML/default/procstat_univariate_sect028.htm)
* [UNIVARIATE default PCTLDEF](https://support.sas.com/documentation/cdl/en/procstat/63104/HTML/default/procstat_univariate_sect008.htm)
* [FASTCLUS STRICT, SEED and REPLACE](https://support.sas.com/documentation/cdl/en/statug/63033/HTML/default/statug_fastclus_sect005.htm)
* [FASTCLUS output identifiers](https://support.sas.com/documentation/cdl/en/statug/63962/HTML/default/statug_fastclus_sect014.htm)
* `data/Project_1/SAS Programs/Star_Macros.sas`, `%kmeans`, unchanged.

SEED= supplies observations from which SAS selects initial seeds. The procedure's
default replacement behavior must not be silently changed to REPLACE=NONE. Stable
percentile medians alone do not establish the selected seed order, convergence,
center updates, empty-cluster behavior or the handling of equidistant observations.

## Checks and next step

Run `python -m pytest tests/test_fastclus_semantics.py` in the project environment.
These are Python regressions against hand-calculated documented cases, not outputs
captured from a SAS runtime. No hospital data or trusted rating values are fixtures.

`tests/sas/fastclus_synthetic_probes.sas` is a standalone synthetic SAS capture script.
Set `probe_dir` to an existing writable folder, then run it with licensed SAS. It saves
percentiles, interval medians, iteration seeds, centers, convergence records and final
signed assignments for normal and reversed seed-row order. A separate fixed-seed,
zero-iteration case isolates the STRICT boundary without changing the production
macro's default seed replacement. The script is not executed
by pytest and has not been run here. Retain its log and SAS version alongside any future
captured results before claiming runtime-confirmed behavior.

After SAS results resolve seed selection, ties and updates, compare a complete helper
against the fixed host validator. A new model experiment that receives human helpers
must be labeled helper-assisted and remain separate from the source-only baseline.
