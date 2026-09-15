# Program 1 Analysis | Average of Measure Scores

## Overview

Program 1 (`1 - First stage_Simple Average of Measure Scores_2025Jul.sas`) calculates the **five group (domain) scores** for each hospital. These five domains make up the foundation of the Overall Star Rating:

| Order | Domain |
|---|---|
| 1 | Mortality |
| 2 | Safety of Care |
| 3 | Readmission |
| 4 | Patient Experience |
| 5 | Timely and Effective Care |

For each domain, Program 1 counts how many measures are in the active domain measure list, then calls a shared macro, `%grp_score` (defined in `Star_Macros.sas`), to compute and save that domain's score for every hospital. All five domain scores are later combined in Program 2 into one final summary score and star rating.

| | |
|---|---|
| **Input** | `std_data_2025Jul_analysis` (produced by Program 0) |
| **Output** | One file per domain, with five files total |
| **Called macro** | `%grp_score`, from `Star_Macros.sas` |
| **Feeds into** | Program 2 (weighted average + star rating) |

---

## Domain-to-Measure Mapping

Program 0 excludes measures reported by 100 or fewer hospitals. For July 2025, no measures were excluded, so the domain measure counts below are the final counts used by Program 1.

Each included measure is assigned to one of the five domains.

### Mortality (7 measures)

| Measure |
|---|
| MORT_30_AMI |
| MORT_30_CABG |
| MORT_30_COPD |
| MORT_30_HF |
| MORT_30_PN |
| MORT_30_STK |
| PSI_4_SURG_COMP |

### Safety of Care (8 measures)

| Measure |
|---|
| COMP_HIP_KNEE |
| HAI_1 |
| HAI_2 |
| HAI_3 |
| HAI_4 |
| HAI_5 |
| HAI_6 |
| PSI_90_SAFETY |

### Readmission (11 measures)

| Measure |
|---|
| EDAC_30_AMI |
| EDAC_30_HF |
| EDAC_30_PN |
| OP_32 |
| READM_30_CABG |
| READM_30_COPD |
| READM_30_HIP_KNEE |
| READM_30_HOSP_WIDE |
| OP_35_ADM |
| OP_35_ED |
| OP_36 |

### Patient Experience (8 measures)

| Measure |
|---|
| H_COMP_1_STAR_RATING |
| H_COMP_2_STAR_RATING |
| H_COMP_3_STAR_RATING |
| H_COMP_5_STAR_RATING |
| H_COMP_6_STAR_RATING |
| H_COMP_7_STAR_RATING |
| H_GLOB_STAR_RATING |
| H_INDI_STAR_RATING |

### Timely and Effective Care / Process (12 measures)

| Measure |
|---|
| HCP_COVID_19 |
| IMM_3 |
| OP_10 |
| OP_13 |
| OP_18B |
| OP_22 |
| OP_23 |
| OP_29 |
| OP_8 |
| PC_01 |
| SAFE_USE_OF_OPIOIDS |
| SEP_1 |

Note: by the time Program 1 runs, the standardized measure-score variables used for domain scoring have a `std_` prefix (such as `std_MORT_30_AMI`) because Program 0 writes them this way before saving `std_data_2025Jul_analysis`.

---

## Available-Measure Counting and Weighting

The per-hospital counting and weighting both happen inside the `%grp_score` macro, not in Program 1 itself. Program 1 only counts how many measures are in each domain’s active measure list and passes that domain-level count into the macro as its fourth parameter.

| Term | What it means |
|---|---|
| Domain measure count | Number of measures in the active domain list for the release (such as 7 for Mortality in July 2025). This count is the same for every hospital within that release. |
| `total_cnt` | How many of those measures **this specific hospital** actually reported (non-missing). Varies hospital to hospital. |
| `measure_wt` | Equal weight per available measure: `1 / total_cnt`. |
| `score_before_std` | Simple average of the hospital's available measures. |

**How the average is calculated:** the macro sums only the hospital's non-missing measure values, then multiplies by the equal weight (`1/total_cnt`). Because missing measures are automatically skipped rather than treated as zero, the result is a true average over whatever the hospital actually reported, not an average dragged down by counting absent measures as zero.

### Example

| Hospital | Measures reported | `total_cnt` | `measure_wt` |
|---|---|---|---|
| A | All 7 Mortality measures | 7 | 1/7 ≈ 0.143 |
| B | Only 3 of 7 Mortality measures | 3 | 1/3 ≈ 0.333 |
| C | 1 of 7 Mortality measures | 1 | 1.0 |
| D | 0 of 7 Mortality measures | 0 | missing |

---

## Missing-Value Handling

If a hospital has zero available measures in a domain (such as `total_cnt = 0`), the averaging step is skipped entirely for that hospital.

| Field | Value when `total_cnt = 0` |
|---|---|
| `measure_wt` | Missing |
| `score_before_std` | Missing |
| `grp_score` | Missing |

None of these become `0`.

Hospitals with missing `score_before_std` values are also excluded from the non-missing values used by `PROC STANDARD` and `PROC MEANS` when the domain-level mean and standard deviation are calculated.

**Why this matters for the Python translation:** A hospital with no reported measures in a domain must end up with `NaN`, not `0`, in all three fields. Treating a missing domain score as `0` would incorrectly convert a missing value into an observed numeric score. This could affect later weighting and summary-score calculations.

---

## Group-Score Macro Trace

The same macro, `%grp_score`, runs once per domain. Only the measure list and output file name change between the five calls, but the underlying steps are identical every time.

| Step | What happens |
|---|---|
| 1 | For each measure in the domain, assign an availability flag of `1` when the hospital's value is non-missing and `0` when it is missing. |
| 2 | Sum the availability flags to calculate `total_cnt`, the number of non-missing measures available for that hospital. |
| 3 | If `total_cnt` is greater than zero, calculate the equal weight (`1/total_cnt`) and the simple average of available measures (`score_before_std`). |
| 4 | Use `PROC STANDARD` to standardize `score_before_std` across hospitals with non-missing `score_before_std` values and produce `grp_score`. This is the second standardization step. Hospitals with missing `score_before_std` remain missing. |
| 5 | Separately, use `PROC MEANS` to calculate the mean and sample standard deviation of `score_before_std` across hospitals with non-missing values. |
| 6 | Attach that overall mean and standard deviation to every hospital's row, so each hospital's record shows both its own values and the reference values used to standardize it. |
| 7 | Combine everything into one final file for the domain, matched up by hospital ID. |

The standard deviation used by the SAS procedures is the sample standard deviation, the same as `pandas.Series.std(ddof=1)` in a Python implementation. Preserving this behavior is important for numerical parity between the SAS and Python results.

Note: Because steps 1–7 are identical across all five domains, this single trace applies to every domain and the only thing that changes per call is which measures are fed in.

| # | Domain | Measures fed in |
|---|---|---|
| 1 | Mortality | The 7 Mortality measures |
| 2 | Safety of Care | The 8 Safety measures |
| 3 | Readmission | The 11 Readmission measures |
| 4 | Patient Experience | The 8 Patient Experience measures |
| 5 | Timely and Effective Care | The 12 Process measures |

---

## Standardization Stages

There are two separate standardization steps across the whole pipeline. One is in Program 0, and the other is in Program 1.

| | First standardization | Second standardization |
|---|---|---|
| **Where** | Program 0 | Program 1 (inside `%grp_score`) |
| **What's standardized** | Each individual measure score | The domain-level average (`score_before_std`) |
| **When it runs** | Once per measure, before Program 1 runs | Once per domain, across hospitals with non-missing `score_before_std`, inside the macro |
| **Result** | Standardized measure scores, mean 0 / std 1 | `grp_score`, mean 0 / std 1 across hospitals with non-missing domain averages |
| **Standard deviation** | Sample standard deviation | Sample standard deviation, equivalent to `std(ddof=1)` in pandas |
| **Extra step** | Some measures also have their sign flipped so a higher value always means better performance | N/A |

---

## Expected Output Artifacts

Program 1 produces **one file per domain**, so five files total.

| Domain | Output file |
|---|---|
| Mortality | `outcome_mortality.sas7bdat` |
| Safety of Care | `outcome_safety.sas7bdat` |
| Readmission | `outcome_readmission.sas7bdat` |
| Patient Experience | `ptexp.sas7bdat` |
| Timely and Effective Care | `process.sas7bdat` |

Important output columns include:

| Column | Description |
|---|---|
| `provider_ID` | Hospital identifier |
| `total_cnt` | Number of available measures the hospital reported in this domain |
| `measure_wt` | Weight applied to each available measure (`1 / total_cnt`) |
| `score_before_std` | Simple average of the hospital's available measures |
| `Mean` | Mean of non-missing `score_before_std` values across hospitals in this domain |
| `StdDev` | Sample standard deviation of non-missing `score_before_std` values across hospitals in this domain |
| `grp_score` | Final standardized domain score |
