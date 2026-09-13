# SAS Final Scoring, Eligibility, Peer Grouping, and Clustering

## Overview

This document describes the behavior of the existing SAS implementation used to calculate final hospital summary scores, determine reporting eligibility, construct peer groups, and assign star ratings.

The process is:

1. Calculate standardized scores for each measure domain.
2. Combine available domain scores using CMS-defined weights.
3. Redistribute weights when a domain score is missing.
4. Determine whether a hospital meets the reporting requirements.
5. Place eligible hospitals into peer groups based on the number of qualifying measure groups.
6. Cluster hospitals within each peer group using SAS `PROC FASTCLUS`.
7. Map the resulting clusters to 1–5 star ratings.

---

## 1. Domain Scores and Weights

The five measure groups/domains are:

| Domain                              | Base Weight |
| ----------------------------------- | ----------: |
| Patient Experience                  |         22% |
| Outcomes – Readmission              |         22% |
| Outcomes – Mortality                |         22% |
| Outcomes – Safety                   |         22% |
| Timely and Effective Care / Process |         12% |
| **Total**                           |    **100%** |

The input to the final scoring stage is the standardized group score (`grp_score`) produced for each domain.

### How domain scores are calculated

For each domain, the SAS program:

1. Counts the available measures for the hospital.
2. Gives each available measure equal weight within that domain.
3. Calculates the average of the available measures.
4. Standardizes the resulting domain averages using a mean of 0 and standard deviation of 1.

Therefore, a missing individual measure does not automatically remove the entire domain. The domain score can still be calculated when at least one measure is available.

---

## 2. Weight Redistribution

The final summary score is a weighted average of the available standardized domain scores.

The SAS implementation first assigns the fixed CMS weights:

* Patient Experience = 0.22
* Readmission = 0.22
* Mortality = 0.22
* Safety = 0.22
* Process = 0.12

If a domain score is missing, that domain receives no weight. The remaining available domain weights are then divided by the total weight of the available domains.

Conceptually:

```text
redistributed weight =
    original domain weight
    --------------------
    total weight of available domains
```

This ensures that the weights of all available domains sum to 100%.

### Example

Suppose Safety is missing.

The available base weight is:

```text
22 + 22 + 22 + 12 = 78
```

The Mortality weight therefore becomes:

```text
22 / 78 ≈ 28.21%
```

The Process weight becomes:

```text
12 / 78 ≈ 15.38%
```

The same proportional redistribution is applied to every available domain.

The final summary score is then:

```text
Summary Score =
    Σ (redistributed domain weight × standardized domain score)
```

### Important implementation detail

The redistribution happens **only because a domain score is missing**. The SAS code does not simply assign equal weights to all available domains; it preserves the original CMS weight proportions.

---

## 3. Reporting Eligibility

Reporting eligibility is determined independently from the weight redistribution.

For each domain, SAS counts how many measures have non-missing values.

A domain is considered a **qualifying measure group** when it contains at least **3 available measures**.

The five domains checked are:

* Outcomes – Mortality
* Outcomes – Safety
* Outcomes – Readmission
* Patient Experience
* Timely and Effective Care / Process

### Eligibility rule

A hospital receives a reportable star rating when:

1. It has at least **3 qualifying measure groups**, and
2. At least **1 qualifying group is either Mortality or Safety**.

In Boolean form:

```text
Total qualifying groups >= 3
AND
(Mortality qualifying OR Safety qualifying)
```

A qualifying group means:

```text
number of available measures >= 3
```

### Eligibility examples

| Qualifying Groups | Mortality/Safety Qualifying? | Eligible? |
| ----------------: | ---------------------------- | --------- |
|                 3 | Yes                          | Yes       |
|                 4 | Yes                          | Yes       |
|                 5 | Yes                          | Yes       |
|                 3 | No                           | No        |
|                 2 | Yes                          | No        |

The SAS implementation first calculates the reporting indicator and then excludes hospitals where:

```text
report_indicator != 1
```

from the peer-group and star-rating process.

---

## 4. Peer-Group Construction

Only hospitals that meet the reporting criteria are included in peer grouping.

Hospitals are divided into three peer groups according to the number of qualifying measure groups:

| Peer Group   | Qualifying Measure Groups |
| ------------ | ------------------------: |
| Peer Group 1 |                         3 |
| Peer Group 2 |                         4 |
| Peer Group 3 |                         5 |

The SAS variable `cnt_grp` records these categories as:

```text
# of groups = 3
# of groups = 4
# of groups = 5
```

Each peer group is clustered separately.

This means hospitals with three qualifying groups are **not clustered together with hospitals having four or five qualifying groups**.

---

## 5. FASTCLUS / K-Means Behavior

The SAS implementation uses `PROC FASTCLUS` to divide hospitals into up to five clusters within each peer group.

The clustering variable is:

```text
summary_score
```

The process has **two FASTCLUS passes**.

### Pass 1: Quintile-based initialization

First, SAS calculates the 20th, 40th, 60th, 80th, and 100th percentiles of the summary score.

Hospitals are assigned to five percentile ranges:

```text
<= P20
P20–P40
P40–P60
P60–P80
> P80
```

The median summary score within each of these groups is then calculated.

These five medians are used as the initial cluster seeds for the first `PROC FASTCLUS` run.

The first pass uses:

```text
maxc=5
converge=0
maxiter=1000
```

Therefore:

* At most 5 clusters are created.
* Clustering continues until convergence rather than requiring a positive convergence threshold.
* Up to 1,000 iterations are allowed.

The resulting cluster centers are saved and used as the starting points for the second pass.

---

## 6. FASTCLUS Pass 2 and `strict=1`

The second FASTCLUS pass uses the cluster centers produced by Pass 1 as its initial seeds.

It again uses:

```text
maxc=5
converge=0
maxiter=1000
```

but additionally specifies:

```text
strict=1
```

The SAS comment states that `strict=1` is intended to avoid the potential effect of outliers on clustering.

Therefore, the migration should not treat the second pass as simply "run K-means again." The second pass begins from the centers generated by the first pass and applies SAS-specific `FASTCLUS` behavior.

The final cluster assignments from this second pass are used for star ratings.

---

## 7. Star Mapping

The cluster numbers generated by FASTCLUS do not directly represent star ratings.

Instead, the final cluster centers are sorted by their mean summary score.

The clusters are then mapped in ascending order:

```text
Lowest mean summary score  → 1 star
Next highest               → 2 stars
Next highest               → 3 stars
Next highest               → 4 stars
Highest mean               → 5 stars
```

This means that the numeric FASTCLUS cluster ID itself should **not** be interpreted as the star rating.

The star rating is determined by the **rank of the cluster's mean summary score**.

---

## 8. Python Migration Considerations

Several parts of the SAS implementation may not be reproduced exactly by a standard Python K-means implementation.

### 8.1 Quintile-median initialization

The initial cluster centers are not randomly selected.

SAS calculates percentile ranges and uses the median summary score within each range as the initial seed.

A Python implementation should explicitly reproduce this initialization if matching SAS behavior is required.

### 8.2 Two-pass clustering

The final clustering is not a single K-means run.

The process is:

```text
Quintile medians
      ↓
FASTCLUS Pass 1
      ↓
Pass 1 cluster centers
      ↓
FASTCLUS Pass 2 with strict=1
      ↓
Final clusters
```

A standard `sklearn.cluster.KMeans` call does not automatically reproduce this workflow.

### 8.3 `strict=1`

`strict=1` is SAS-specific FASTCLUS behavior and may not have a direct one-to-one equivalent in standard Python K-means implementations.

This behavior needs to be investigated before assuming that `sklearn.cluster.KMeans` will produce identical results.

### 8.4 Cluster-center reuse

Pass 2 explicitly uses the cluster centers from Pass 1.

The Python implementation therefore needs to preserve the exact relationship between the two clustering passes.

### 8.5 Cluster ordering and star assignment

FASTCLUS cluster IDs are not the final stars.

The implementation must:

1. Calculate the final cluster means.
2. Sort clusters by mean summary score.
3. Assign stars from lowest to highest mean.
4. Map each hospital's final cluster to that ordered star value.

### 8.6 Ties and fewer than five effective clusters

The code allows a maximum of five clusters, but the effective number of clusters may depend on the data and FASTCLUS behavior.

Edge cases that should be tested include:

* Fewer than five distinct summary scores.
* Duplicate percentile medians.
* Empty percentile groups.
* Fewer hospitals than requested clusters.
* Tied cluster means.
* Hospitals with identical summary scores.
* Outlier summary scores.

These cases may affect whether the Python implementation produces the same cluster and star assignments as SAS.

---

## 9. End-to-End Logic

Program 2 follows these steps to produce the final hospital star rating:

**Step 1 — Calculate the Final Summary Score**
The program combines the available standardized scores for the five measure groups using the CMS-defined weights. If a domain score is unavailable, its weight is removed and the remaining weights are proportionally redistributed. This produces a final `summary_score` for each hospital.

**Step 2 — Determine Reporting Eligibility**
The program counts the number of available measures in each domain. A domain qualifies when it contains at least 3 measures. A hospital is eligible for reporting when at least 3 domains qualify and at least one of the qualifying domains is Mortality or Safety.

**Step 3 — Create Peer Groups**
Eligible hospitals are separated into peer groups based on the number of qualifying domains. Hospitals with 3 qualifying groups, 4 qualifying groups, and 5 qualifying groups are clustered separately.

**Step 4 — Create Initial Cluster Seeds**
Within each peer group, the program calculates the 20th, 40th, 60th, 80th, and 100th percentiles of `summary_score`. It then calculates the median score within each percentile range and uses these medians as the initial cluster seeds.

**Step 5 — Run FASTCLUS**
The program runs `PROC FASTCLUS` using the initial seeds, with a maximum of 5 clusters and up to 1,000 iterations. The resulting cluster centers are saved for the second pass.

**Step 6 — Run FASTCLUS Again**
The second `PROC FASTCLUS` pass starts with the cluster centers from Step 5 and uses `strict=1`. The resulting cluster assignments and cluster centers are used for the final star-rating calculation.

**Step 7 — Assign Star Ratings**
The final clusters are ordered by their mean `summary_score`. The cluster with the lowest mean receives 1 star, and the cluster with the highest mean receives the highest star rating, producing the final 1–5 star rating.

This ordering is important for migration because **eligibility, peer grouping, and clustering are sequential steps rather than independent calculations**.

## Open Technical Questions

The following questions should be addressed when implementing the Python equivalent of the SAS clustering process: 

1. **FASTCLUS equivalence:**  
   Can the Python implementation reproduce the behavior of SAS `PROC FASTCLUS` closely enough to preserve the resulting star ratings?

2. **`strict=1` behavior:**  
   What specific effect does `strict=1` have on the SAS clustering process, and is there a comparable approach in Python?

3. **Cluster initialization and count:**  
   How should the Python implementation handle cases where the percentile-based initialization produces duplicate seeds or fewer than five distinct cluster centers?