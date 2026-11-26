# Program 2 SAS semantics references

These generic documentation notes were selected after the first Program 2 experiment.
They contain no hospital-specific values or target star assignments. A follow-up that
uses them is documentation-assisted and must be recorded separately from the original
source-only translation and automatic repair experiment.

## Percentiles

The SAS percentile definitions distinguish `n*p` from `(n+1)*p`. For definition 5, write
`n*p = j + g` with `j` the integer part. With one-based sorted observations, an integer
position uses the average of observations `j` and `j+1`; a noninteger position uses
observation `j+1`. Boundary positions use the observed extremes. Interpolation based
on `(n+1)*p` is definition 4. See the official
[UNIVARIATE percentile definitions](https://support.sas.com/documentation/cdl/en/procstat/68142/HTML/default/procstat_univariate_details14.htm).

## STRICT and cluster labels

`STRICT=s` restricts assignment by distance to the closest seed. It is not an option
that merely changes how an empty cluster's seed is replaced. An observation rejected
by this restriction has a negative cluster identifier in the output, and its absolute
value identifies the closest cluster. The supplied macro uses `STRICT=1`, then applies
`ABS(cluster)` before joining stars. See the official
[FASTCLUS options](https://support.sas.com/documentation/cdl/en/statug/67523/HTML/default/statug_fastclus_syntax01.htm).

## Iteration

FASTCLUS separates seed selection, optional DRIFT processing, iterative assignment and
center updates, and final assignment. The supplied macro does not request DRIFT. Exact
convergence behavior and seed-selection details still require care when translating
the procedure. See the official
[FASTCLUS background](https://support.sas.com/documentation/cdl/en/statug/63033/HTML/default/statug_fastclus_sect002.htm).

These references describe semantics. They do not establish that a particular generated
Python implementation matches SAS. The fixed host comparisons remain authoritative.
