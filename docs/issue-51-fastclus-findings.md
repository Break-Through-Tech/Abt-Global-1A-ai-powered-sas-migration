# Issue #51 — FASTCLUS Investigation Findings

## Overview

This investigation examines the one-dimensional FASTCLUS clustering process used in Program 2 of the CMS July 2025 Overall Hospital Quality Star Rating SAS pipeline.

The goal is to establish reference behavior and identify areas requiring further verification before implementing equivalent clustering in Python.

## Source Files

- `data/Project_1/SAS Programs/Star_Macros.sas`
- `data/Project_1/SAS Programs/2 - Second Stage_Weighted Average and Categorize Star_2025Jul.sas`
- `data/Project_1/SAS Output CSV/STAR_2025JUL.csv`

## Confirmed SAS Behavior

**1. Peer-group clustering**

Program 2 calls the `%kmeans` macro separately for hospitals with three, four, and five qualifying domains.

**2. Percentile-based initialization**

The macro calculates the 20th, 40th, 60th, and 80th percentiles of hospital summary scores and assigns hospitals to five intervals. It calculates each interval's median to create the initial seeds (`s33`).

**3. First FASTCLUS pass**

The first pass uses `MAXC=5`, `CONVERGE=0`, `MAXITER=1000`, and `SEED=s33`. Its resulting cluster centers are saved as `seeds2`.

**4. Second FASTCLUS pass**

The second pass reuses `seeds2` with `STRICT=1`, retaining the same maximum cluster count, convergence threshold, and iteration limit. The SAS source describes this as a measure to reduce potential outlier effects.

**5. Cluster ordering and star assignment**

Final cluster centers are sorted by ascending summary score. Stars are assigned sequentially from 1 to 5 based on this ordering, rather than the original cluster identifiers.

The source also applies `ABS(cluster)` before merging cluster assignments with star labels.

## Python Reference Probes

The `tests/test_fastclus.py` file contains 20 passing test cases covering:

- Eight percentile-boundary assignments, including a valid zero score
- Three missing-score cases: `None`, numeric `NaN`, and pandas `NA`; all remain unassigned
- Two median-initialization cases (odd and even counts)
- First-pass FASTCLUS configuration
- Second-pass configuration and seed reuse
- Two cluster-ordering and star-mapping cases
- Two synthetic outlier-sensitivity checks

These tests verify reference rules, source configuration, and illustrative statistical behavior. They do not establish numerical parity between SAS FASTCLUS and a Python clustering implementation.

**Combined Test Results**

The combined Program 2 verification suite passed all 44 tests across the following files:

- `tests/test_program2_eligibility.py`
- `tests/test_program2_weights.py`
- `tests/test_artifacts.py`
- `tests/test_fastclus.py`

These tests cover eligibility boundaries, domain-weight redistribution, reference artifact counts, and FASTCLUS reference behavior.

## Unresolved Questions

- Whether Python percentile calculations match the exact SAS `PROC UNIVARIATE` percentile definition, including ties and small datasets.
- Whether the initial seed dataset has the expected structure and ordering for every peer group.
- How SAS FASTCLUS updates centers and determines convergence compared with Python alternatives.
- The precise effect of `STRICT=1` on outliers, cluster assignments, and final centers.
- How signed cluster identifiers arise and how `ABS(cluster)` affects assignments.
- How empty clusters or tied final cluster means affect star assignment.

## Reference Artifact Verification

Separate tests in `tests/test_artifacts.py` confirmed the supplied SAS output contains:

- 2,891 rated hospitals
- 141 hospitals in the three-domain peer group
- 515 hospitals in the four-domain peer group
- 2,235 hospitals in the five-domain peer group

These checks establish reference counts, not exact clustering parity.

## Conclusion

The available SAS source establishes the initialization, two-pass FASTCLUS configuration, and cluster-to-star mapping workflow. Additional SAS execution or detailed intermediate artifacts are needed to confirm numerical clustering behavior and reproduce the results precisely in Python.

A generic K-means implementation should not be assumed equivalent to SAS FASTCLUS without further validation.
