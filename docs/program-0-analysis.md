# Program 0 analysis: data and measure standardization

Program 0 is `0 - Data and Measure Standardization_2025Jul.sas`. It reads the July 2025 hospital input, selects measures with enough reported values, standardizes each measure, reverses measures for which lower raw values are better, and writes the analysis dataset used by Programs 1 and 2. This document describes the supplied SAS program and artifacts. It is not a claim that a Python translation of Program 0 has passed validation.

See the [artifact inventory](artifact-inventory.md) for all supplied files and the [Program 1 analysis](program-1-analysis.md) for the next stage.

## Inputs and session setup

Program 0 sets `&year=2025` and `&quarter=Jul`. Its hardcoded `PATH1`, `PATH2`, and `PATH3` values point to a Windows input directory, output directory, and macro directory. `HC.` names the input library and `R.` names the permanent output library. The repository holds the equivalent files under `data/Project_1/Starrating/`, `SAS Output/`, and `SAS Programs/`. The paths in the supplied source cannot be used unchanged in this checkout.

The input is `HC.Alldata_2025Jul`, supplied as `alldata_2025jul.sas7bdat` and `alldata_2025jul.csv`. It has 4,566 hospital rows and 93 columns. `PROVIDER_ID` is a six-character identifier and must remain a string, including leading zeros. Program 0 includes `Star_Macros.sas` before calling `%keep_hos`. The same SAS session must retain the included macros, domain tables, and macro variables for Programs 1 and 2.

The program defines `&MEASURE_MEAN` and `&MEASURE_ANALYSIS` for its two named permanent outputs. It also defines `&RESULTS` and `&NATIONAL_MEAN`, but Program 2 writes those later. Unprefixed intermediate datasets belong to SAS `WORK.` and are not supplied as permanent outputs.

## Processing order

| Stage | SAS operation | Result |
|---|---|---|
| Copy input | `DATA All_data_2025Jul` reads `HC.Alldata_2025Jul` | Working copy of the hospital data. |
| Count reported values | `PROC TABULATE` counts nonmissing values for every name in `&measure_all`; `PROC TRANSPOSE` makes one row per measure | `measure_volume_t` holds the reporting count in `COL1`. The program performs an earlier copy of this count before the exclusion logic, then repeats it for the final lists. |
| Exclude low-volume measures | `less100_measure` selects counts of 100 or fewer; `initial_data_2025Jul` conditionally drops their columns | `R.less100_measure` records exclusions. Only measures with counts above 100 enter the final lists. |
| Build final lists | `include_measure` and five domain tables select measures with counts above 100 | Macro variables hold active raw and `std_`-prefixed names. The domain tables remain in `WORK.` for Program 1. |
| Remove hospitals without measures | `%keep_hos` counts each row's nonmissing active measures and retains rows with `Total_m_cnt >= 1` | `initial_data_2025Jul` gains `Total_m_cnt`. |
| Save raw-score statistics | `PROC MEANS` reads the retained, unstandardized measures | `R.measure_average_stddev_2025Jul` contains N, MIN, MAX, MEAN, and STD for each of the 46 measures. |
| Standardize and orient | `PROC STANDARD mean=0 std=1` standardizes each active measure; a DATA step negates selected columns | All oriented measure scores have the intended higher-is-better direction. |
| Publish analysis data | Parallel SAS arrays copy the oriented values to `std_` columns; the output DATA step drops the original raw measure columns | `R.Std_data_2025Jul_analysis` feeds Programs 1 and 2. |

The first volume pass creates `include_measure0`, `&measure_in`, and `&measure_cnt` before exclusions. After exclusions, the program rebuilds those variables from `include_measure`. The later values are the ones used for hospital filtering, statistics, and standardization.

`PROC TRANSPOSE` supplies `_NAME_` and `COL1`. The DATA steps strip the `_N` suffix from `_NAME_` to make `measure_in_name` or `measure_name`, rename `COL1` to `freq` where needed, and construct `measure_in_std` by adding `std_`. These are working-table fields. The permanent exclusion artifact contains `measure_name` and `freq`.

## Active measures and domains

`&measure_all` names 46 active measures in five domains. Program 0 applies the `COL1 > 100` filter to each domain table. For the supplied July 2025 run, no measure fails this filter, so the final domain counts are 7 + 8 + 11 + 8 + 12 = 46.

| Domain | Count | Active raw measure names |
|---|---:|---|
| Mortality, `&measure_OM` | 7 | `MORT_30_AMI`, `MORT_30_CABG`, `MORT_30_COPD`, `MORT_30_HF`, `MORT_30_PN`, `MORT_30_STK`, `PSI_4_SURG_COMP` |
| Safety of Care, `&measure_OS` | 8 | `COMP_HIP_KNEE`, `HAI_1`, `HAI_2`, `HAI_3`, `HAI_4`, `HAI_5`, `HAI_6`, `PSI_90_SAFETY` |
| Readmission, `&measure_OR` | 11 | `EDAC_30_AMI`, `EDAC_30_HF`, `EDAC_30_PN`, `OP_32`, `READM_30_CABG`, `READM_30_COPD`, `READM_30_HIP_KNEE`, `READM_30_HOSP_WIDE`, `OP_35_ADM`, `OP_35_ED`, `OP_36` |
| Patient Experience, `&measure_PtExp` | 8 | `H_COMP_1_STAR_RATING`, `H_COMP_2_STAR_RATING`, `H_COMP_3_STAR_RATING`, `H_COMP_5_STAR_RATING`, `H_COMP_6_STAR_RATING`, `H_COMP_7_STAR_RATING`, `H_GLOB_STAR_RATING`, `H_INDI_STAR_RATING` |
| Timely and Effective Care, `&measure_Process` | 12 | `HCP_COVID_19`, `IMM_3`, `OP_10`, `OP_13`, `OP_18B`, `OP_22`, `OP_23`, `OP_29`, `OP_8`, `PC_01`, `SAFE_USE_OF_OPIOIDS`, `SEP_1` |

The Process code comment says "ALL 13Process measures", but the executable `IN` list has 12 names. `OP_2` and `OP_3B` are commented out, and the source says they were removed for 2025; `SAFE_USE_OF_OPIOIDS` was added. The log prints `&measure_cnt` as 46, the Program 1 Process table has 12 measures, and the published analysis dataset has 46 `std_` columns. Use the executable list, not the stale comment, for this release. SAS treats `OP_18b` in `&measure_all` and `OP_18B` in the domain list as the same variable name.

## Exclusion and hospital-count behavior

The reporting count is the number of hospitals with a nonmissing score for a measure, not the sum of its denominator column. A measure reported by exactly 100 hospitals is excluded. The program saves excluded names and counts in `R.less100_measure`, then drops those score columns from the working input and omits them from `&measure_in` and the domain lists.

For July 2025, `R.less100_measure` has zero rows and two columns. The SAS log prints a warning that `MEASURE_EXCLUDE` is unresolved because the SQL query returned no rows. `&NOBS` is set to zero and the `%if &NOBS>0` guard skips the `DROP`, so this warning does not change the result. A Python version must allow an empty exclusion list rather than treating it as an error.

`%keep_hos` counts nonmissing values across the final included measures for each hospital. It keeps rows with at least one reported measure and drops its temporary `C1` through `C46` flags. The supplied input and the published analysis dataset both have 4,566 rows. In the published output, `Total_m_cnt` ranges from 1 to 46, so the July 2025 run removed no hospitals at this step. This count is across all domains; Program 1 computes separate per-domain counts.

## Standardization, direction, and output columns

`PROC MEANS` writes statistics for the original scores before standardization or direction reversal. Its supplied output has five rows, identified by `_STAT_` values `N`, `MIN`, `MAX`, `MEAN`, and `STD`, and 49 columns: `_TYPE_`, `_FREQ_`, `_STAT_`, and 46 measure columns.

`PROC STANDARD mean=0 std=1` operates on each of the 46 included score columns across hospitals. For an ordinary nonconstant measure, the intended transformation is `(value - measure mean) / measure sample standard deviation`; missing scores stay missing. The subsequent DATA step negates measures whose lower raw value is better:

| Domain | Measures negated after standardization |
|---|---|
| Mortality | All 7 measures. |
| Safety of Care | All 8 measures. |
| Readmission | All 11 measures. |
| Patient Experience | None. |
| Timely and Effective Care | `OP_10`, `OP_13`, `OP_18B`, `OP_22`, `OP_8`, `PC_01`, `SAFE_USE_OF_OPIOIDS`. |

The other five Process measures keep their sign: `HCP_COVID_19`, `IMM_3`, `OP_23`, `OP_29`, and `SEP_1`. The `OP_3B` negation is commented out and does not execute.

The final DATA step creates `std_`-prefixed copies of the oriented scores and drops the original 46 score columns. It retains `PROVIDER_ID`, the non-score input fields such as denominators, and `Total_m_cnt`. The published `R.Std_data_2025Jul_analysis` has 4,566 rows and 94 columns, including exactly 46 `std_` score columns. Program 1 reads these columns to form domain scores; Program 2 also reads the analysis dataset for reporting eligibility.

## Macro variables and downstream dependencies

| Name | July 2025 role |
|---|---|
| `&measure_all` | The 46 candidate raw-score names. |
| `&measure_in` | The active raw-score names after the reporting-count filter. |
| `&measure_in_std` | Matching `std_`-prefixed output names. |
| `&measure_cnt` | Active score count, 46 for this release; sizes the SAS arrays and `%keep_hos` flags. |
| `&measure_exclude`, `&NOBS` | Names and count of measures with volume at most 100; `&NOBS=0` here. |
| `&measure_OM`, `&measure_OS`, `&measure_OR`, `&measure_PtExp`, `&measure_Process` | Active `std_` column lists passed to Program 1's `%grp_score` calls. |
| `&MEASURE_MEAN`, `&MEASURE_ANALYSIS` | Names of Program 0's permanent statistics and analysis datasets. |
| `&RESULTS`, `&NATIONAL_MEAN` | Output names defined here but used when Program 2 writes its results. |

Program 1 also reads the temporary `outcomes_mortality`, `outcomes_safety`, `outcomes_readmission`, `PtExp`, and `Process` tables to calculate domain measure counts. A standalone Python port should represent these lists and counts explicitly rather than depend on SAS session state.

## Permanent Program 0 artifacts

| Artifact in `SAS Output/` | Rows | Columns | Meaning |
|---|---:|---:|---|
| `less100_measure.sas7bdat` | 0 | 2 | Excluded measures and their reporting counts. |
| `measure_average_stddev_2025jul.sas7bdat` | 5 | 49 | Statistics for the 46 original score columns. |
| `std_data_2025jul_analysis.sas7bdat` | 4,566 | 94 | Hospital rows with oriented, standardized scores and `Total_m_cnt`. |

CSV copies of all three artifacts are supplied in `SAS Output CSV/`. The SAS binaries are the trusted reference for parity checks. The SAS log confirms the output dimensions; the published CSV headers confirm the 46 `std_` score columns and the five `_STAT_` rows.

## Questions for translation and later releases

1. How should a Python port reproduce `PROC STANDARD` if a future measure has zero variance or no nonmissing values? The July 2025 lists all have more than 100 reported values, but the zero-variance case still needs a focused SAS reference test.
2. If a future release excludes one or more measures, does the `PROC TABULATE` and `PROC TRANSPOSE` sequence retain the same name ordering and output schema? The current empty exclusion artifact does not exercise that branch.
3. Do the hardcoded domain membership and direction lists change in a later quarter? The source itself says to review those lists whenever measures are added or removed.

These are questions for a later translation or SAS access session, not reasons to change the supplied July 2025 artifacts.
