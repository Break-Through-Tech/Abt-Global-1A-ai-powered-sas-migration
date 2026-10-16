# Golden artifact traces

SASGuard's golden trace summarizes deterministic comparisons over a declared artifact
dependency graph. It helps identify the earliest observed failures among the checkpoints
that a run actually compared. It is not an AI diagnosis and does not identify a SAS
statement or prove root cause.

## Graph and scope

The version 1 lineage model represents each artifact as an `ArtifactNode` with a canonical
uppercase SAS identifier and a tuple of parent artifacts. An `ArtifactLineage` contains
the nodes and schema version. Validation rejects duplicate names, duplicate parents after
canonicalization, unknown parents, self-dependencies, and cycles. Trace ordering is
deterministic, including when independent nodes have no dependency order.

The `trace_artifacts(lineage, comparisons, *, scope, supplied_reference_inputs=())`
function accepts an `ArtifactLineage`, zero or more `ArtifactComparison` results, a
nonblank scope label, and optional artifact names for explicitly supplied trusted inputs.
It returns a version 1 `GoldenTraceResult`. Comparisons and boundary names must refer to
known graph nodes. A node cannot appear as both a comparison and a supplied input.

The current CMS configuration is in
[`configs/cms-artifact-lineage.json`](../configs/cms-artifact-lineage.json). It declares
`ALLDATA_2025JUL` as the source, `LESS100_MEASURE` as its child, and both
`MEASURE_AVERAGE_STDDEV_2025JUL` and `STD_DATA_2025JUL_ANALYSIS` as children of those
first two artifacts. The five group outputs (`OUTCOME_MORTALITY`, `OUTCOME_SAFETY`,
`OUTCOME_READMISSION`, `PTEXP`, and `PROCESS`) depend on `STD_DATA_2025JUL_ANALYSIS`.
`STAR_2025JUL` depends on that standardized artifact and all five group outputs.
`NATIONAL_AVERAGE_2025JUL` depends on `STAR_2025JUL` and the five group outputs. This
graph records artifact dependencies declared for tracing. The measure-summary artifact
is an observational sibling of the standardized artifact, not an input consumed by
`PROC STANDARD`. Internal eligibility rules, weighted-score calculations, and peer
clustering do not produce separate verified artifact checkpoints in this graph.

The graph describes declared artifact dependencies. It does not model the internal
statements in a SAS program. In particular, a failed artifact indicates a mismatch at
that comparison checkpoint, not a causal defect in every declared parent or a specific
line of SAS code. Dependencies that share a parent remain independent branches in the
trace.

Each comparison has one of three checkpoint states:

- `passed`: a comparison was supplied and passed under its artifact comparison policy.
- `failed`: a comparison was supplied and found one or more mismatches or structural
  errors.
- `not_checked`: no comparison was supplied for that graph node.

A missing comparison stays `not_checked`; it never implies success. `scope_complete` is
true only when every non-boundary artifact in the lineage graph has a comparison.
`all_checked_passed` is true only when the run includes at least one comparison and every
provided comparison passes. These fields answer different questions. A partial trace can
have `all_checked_passed: true` while `scope_complete: false`.

An explicitly supplied trusted reference input is marked as a boundary. The trace records
that the run used the input, but the boundary is not a Python pass. It closes the upstream
part of a bounded check only where the controller explicitly declares it trusted. For
failure-frontier reasoning, the trace cuts incoming edges at that boundary while retaining
the declared parents in checkpoint metadata. Other unchecked upstream nodes remain visible
as unchecked. For a first-divergence artifact, `confirmed_within_scope` is true only when
all its effective ancestors were compared and passed, or are explicitly trusted
boundaries. This status describes the declared graph and the chosen boundary. It does not
establish correctness outside that boundary.

## First observed divergences

`first_divergences` contains the observed failed checkpoints that have no failed ancestor
in the effective graph after cutting edges at supplied input boundaries. It reports a
frontier, not a single winner. If two independent
branches fail, both failures appear. A failed descendant of another failed checkpoint is
not listed as a first divergence because its mismatch may follow the earlier observed
failure. The trace makes no causal claim about that relationship.

Each checkpoint reports its status, declared parents, and whether it was a supplied
reference input. For each first divergence, the trace reports unchecked upstream
artifacts, dependent artifacts, whether the artifact is confirmed within the declared
scope, and a diagnostic summary. Diagnostic summaries contain aggregate counts and error
measures only. They do not contain provider keys or IDs, key values, or expected raw
values. The separate comparison report may retain comparison details, so apply the
existing report and data handling rules to that file.

The serialized result has `checkpoints`, `first_divergences`, and
`not_checked_artifacts` collections, plus `scope_complete` and `all_checked_passed`
summary flags. A first-divergence diagnostic includes row and column counts, counts of
missing and extra keys, missing and extra columns, mismatched columns and cells,
missingness mismatches, and absolute-error summaries where available. It stores column
names to identify mismatches, but never key values.

## Mortality prototype trace

The Mortality controller records the full configured CMS graph but compares only
`OUTCOME_MORTALITY`. It marks the supplied `STD_DATA_2025JUL_ANALYSIS` Program 0 artifact
as a trusted boundary. The remaining graph nodes are `not_checked`. As a result,
`scope_complete` is false for the full graph, even when the Mortality comparison passes
and `all_checked_passed` is true. The latter means only that the provided Mortality
comparison passed.

The run writes `trace.json` beside `comparison.json` in its `reports/runs/mortality-<UUID>/`
directory. Before execution it writes a trace with all comparisons `not_checked`, then
replaces it after the Mortality comparison. Execution failures retain the unchecked trace
rather than inventing an analytical failure. The trusted controller freezes the configured lineage and checks its hash
alongside the relevant source hashes before and after execution. The trace contains no
raw comparison keys or expected output values. The trace does not imply that an
unexecuted SAS program was reproduced.

See [Mortality prototype](mortality-prototype.md) for the run setup and the limits of its
comparison.
