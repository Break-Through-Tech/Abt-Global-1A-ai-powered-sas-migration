# Supplied Artifact Inventory

This document inventories every artifact supplied for Project 1, the CMS Overall Hospital Quality
Star Rating pipeline (July 2025 release). All artifacts live under `data/Project_1/`.

These materials are protected. See [Contributing](../CONTRIBUTING.md#protected-project-materials):
do not modify them during translation, repair, or validation.

## Summary

- **29 files** were supplied: 3 SAS programs, 1 SAS macro library, 1 SAS log, 1 input dataset (as
  CSV and SAS binary), 10 golden outputs (each as SAS binary and CSV), 1 HTML results file, and
  1 PDF.
- **All 10 golden outputs are present.** Each CSV matches its SAS binary in row count and column
  names.
- **No artifacts are missing.** The SAS code writes exactly 10 permanent datasets, and all 10 were
  supplied.
- The pipeline runs **Program 0 → Program 1 → Program 2** in a single SAS session. The code, the
  log, and the supplied files all agree on this order.

## Folder layout

| Folder | Contents |
|---|---|
| `Starrating/` | Pipeline input: `alldata_2025jul` (CSV and SAS binary) |
| `SAS Programs/` | Programs 0, 1, and 2, the macro library `Star_Macros.sas`, and `SAS_Log.log` |
| `SAS Output/` | The 10 golden outputs as SAS binary datasets (`.sas7bdat`), plus `SAS Output.htm` |
| `SAS Output CSV/` | CSV copies of the 10 golden outputs |
| *(root)* | `StarRatings_SASPackDoc_Jul2025.pdf`, the CMS SAS pack documentation |

## Execution order

```text
alldata_2025jul (input)
   └─ Program 0 → less100_measure, measure_average_stddev_2025Jul, std_data_2025Jul_analysis
         └─ Program 1 → outcome_mortality, outcome_safety, outcome_readmission, ptexp, process
               └─ Program 2 (also reads std_data_2025Jul_analysis directly)
                     → star_2025Jul → national_average_2025Jul
```

### How SAS names map to folders

Program 0 assigns two library nicknames (lines 19–20):

- `HC.` points to the input folder (`Starrating/`).
- `R.` points to the output folder (`SAS Output/`). Every `R.` dataset is a golden output.

Datasets with no prefix are temporary (`WORK.`) and are not saved.

### Session dependencies

Programs 1 and 2 do not define their own paths, dataset-name variables, or macros. They rely on
session state created by earlier programs:

- **Macros:** the `%INCLUDE` of `Star_Macros.sas` (Program 0, line 22).
- **Temporary domain tables:** Program 0 builds `WORK` tables such as `outcomes_mortality`
  (lines 171–261) that list each domain's measures. Program 1 reads these tables to count the
  measures in each domain.
- **Measure-list variables:** Program 0 stores each domain's measure list in a macro variable,
  such as `&measure_OM`. Program 1 passes these to `%grp_score`.
- **Domain-count variables:** Program 1 creates `&measure_OM_cnt` and its counterparts. Program 2
  passes these to `%report` (lines 99–100).
- **Dataset-name variables:** `%LET` variables that name the output datasets (Program 0,
  lines 24–30):

| Variable | Resolves to |
|---|---|
| `&MEASURE_MEAN` | `R.measure_average_stddev_2025Jul` |
| `&MEASURE_ANALYSIS` | `R.Std_data_2025Jul_analysis` |
| `&RESULTS` | `R.Star_2025Jul` |
| `&NATIONAL_MEAN` | `R.national_average_2025Jul` |

All three programs must run in order in the same SAS session. Loading only the permanent
datasets is not enough to reproduce Program 1 or Program 2 in isolation.

### Evidence from the log

`SAS_Log.log` records each golden output as it is saved. The order and dimensions match the code
and the supplied files.

| Order | Log line | Dataset written | Rows | Cols |
|---|---|---|---|---|
| 1 | 309 | `R.LESS100_MEASURE` | 0 | 2 |
| 2 | 819 | `R.MEASURE_AVERAGE_STDDEV_2025JUL` | 5 | 49 |
| 3 | 928 | `R.STD_DATA_2025JUL_ANALYSIS` | 4566 | 94 |
| 4 | 1024 | `R.OUTCOME_MORTALITY` | 4566 | 21 |
| 5 | 1090 | `R.OUTCOME_SAFETY` | 4566 | 23 |
| 6 | 1158 | `R.OUTCOME_READMISSION` | 4566 | 29 |
| 7 | 1227 | `R.PTEXP` | 4566 | 23 |
| 8 | 1295 | `R.PROCESS` | 4566 | 31 |
| 9 | 1992, 2028 | `R.STAR_2025JUL` | 4566 | 27 |
| 10 | 2239, 2266 | `R.NATIONAL_AVERAGE_2025JUL` | 1 | 9 |

`STAR_2025JUL` and `NATIONAL_AVERAGE_2025JUL` each appear twice because Program 2 creates each one
and then rewrites it to add variable labels (lines 168 and 214). They are single outputs, not
duplicates.

## SAS programs and macros

| File | Purpose | Reads | Writes |
|---|---|---|---|
| `0 - Data and Measure Standardization_2025Jul.sas` | Counts hospitals reporting each measure, excludes measures reported by 100 or fewer hospitals, and standardizes measure scores to mean 0 and standard deviation 1 (`PROC STANDARD`, line 305) | `HC.alldata_2025jul` (line 51); loads `Star_Macros.sas` (line 22) | `less100_measure` (line 108), `measure_average_stddev_2025Jul` (line 296), `std_data_2025Jul_analysis` (line 363) |
| `1 - First stage_Simple Average of Measure Scores_2025Jul.sas` | Computes the five domain group scores for each hospital with `%grp_score`. See [Program 1 analysis](program-1-analysis.md). | `std_data_2025Jul_analysis` | `outcome_mortality` (line 43), `outcome_safety` (61), `outcome_readmission` (80), `ptexp` (101), `process` (121) |
| `2 - Second Stage_Weighted Average and Categorize Star_2025Jul.sas` | Combines domain scores into a weighted summary score, determines reporting eligibility (`%report`), assigns peer groups, clusters hospitals into 1–5 stars (`%kmeans`), and computes national averages | The five Program 1 outputs (lines 23–27, 199–203); `std_data_2025Jul_analysis` (line 99) | `star_2025Jul` (lines 160, 168), `national_average_2025Jul` (lines 206, 214) |
| `Star_Macros.sas` | Macro library: `keep_hos`, `grp_score`, `report`, `kmeans`, `nation_avg0`, `nation_avg_peer`, `nation_avg` | — | — |

## Input dataset

| File | Format | Rows | Cols | Key column | Purpose |
|---|---|---|---|---|---|
| `Starrating/alldata_2025jul` | CSV and SAS binary | 4566 | 93 | `PROVIDER_ID` (unique) | One row per hospital: raw scores for the 46 measures and their denominator columns |

`PROVIDER_ID` is a six-character string with leading zeros (for example, `010001`). It must be read
as a string, not an integer.

## Golden outputs (10)

Each output is supplied as a SAS binary in `SAS Output/` and a CSV in `SAS Output CSV/`. The
golden-output CSV names are uppercase. Rows and columns are identical within every pair.

| # | Dataset | Rows | Cols | Key column | Produced by | Purpose |
|---|---|---|---|---|---|---|
| 1 | `less100_measure` | 0 | 2 | `measure_name` | Program 0 | Measures reported by 100 or fewer hospitals, which are excluded. Empty for this release. |
| 2 | `measure_average_stddev_2025Jul` | 5 | 49 | `_STAT_` | Program 0 | `PROC MEANS` statistics (N, MIN, MAX, MEAN, STD) for each of the 46 original measure scores |
| 3 | `std_data_2025Jul_analysis` | 4566 | 94 | `PROVIDER_ID` | Program 0 | Standardized measure scores (`std_` prefix), denominators, and `Total_m_cnt`. Input to Programs 1 and 2. |
| 4 | `outcome_mortality` | 4566 | 21 | `PROVIDER_ID` | Program 1 | Mortality domain group score (`grp_score`) and its components |
| 5 | `outcome_safety` | 4566 | 23 | `PROVIDER_ID` | Program 1 | Safety of Care domain group score and its components |
| 6 | `outcome_readmission` | 4566 | 29 | `PROVIDER_ID` | Program 1 | Readmission domain group score and its components |
| 7 | `ptexp` | 4566 | 23 | `PROVIDER_ID` | Program 1 | Patient Experience domain group score and its components |
| 8 | `process` | 4566 | 31 | `PROVIDER_ID` | Program 1 | Timely and Effective Care domain group score and its components |
| 9 | `star_2025Jul` | 4566 | 27 | `PROVIDER_ID` | Program 2 | Final hospital results: domain scores, weights, summary score, measure-group counts, reporting indicator, peer group, and star rating |
| 10 | `national_average_2025Jul` | 1 | 9 | none (single row) | Program 2 | National average summary score (overall and for peer groups 3, 4, and 5), computed over hospitals with `report_indicator = 1`; and national average of each domain group score, computed over hospitals with `total_cnt >= 3` in that domain |

## Other artifacts

| File | Purpose |
|---|---|
| `SAS Programs/SAS_Log.log` | Record of one run of all three programs in a single session. It contains no errors and one warning (see below). |
| `SAS Output/SAS Output.htm` | SAS HTML results output from the run, containing printed `PROC MEANS` and `PROC FASTCLUS` results. It is a report, not a dataset or golden output. |
| `StarRatings_SASPackDoc_Jul2025.pdf` | CMS "Overall Hospital Quality Star Ratings: 2025 SAS Pack Software Documentation," July 2025 publication. Describes the methodology. |

## Integrity hashes

SHA-256 hashes of every supplied file. These match the protected-artifact manifest
(`configs/protected-artifacts.json`) from the integrity-check work in #16. That manifest is the
authoritative source for integrity checks; this table is for reference.

| File | SHA-256 |
|---|---|
| `SAS Output/SAS Output.htm` | `f9e547f402ffc150b9aef1b02acb060a83fb69707f33f122fe7c27f3064101d5` |
| `SAS Output/less100_measure.sas7bdat` | `a424dbffe6fb73b3a2abc71f3eb1709134442871007898804ad198ee51164047` |
| `SAS Output/measure_average_stddev_2025jul.sas7bdat` | `434b8635f069c6dffed520a696d9adc4fbd01635c341eb42a38532f33646ff92` |
| `SAS Output/national_average_2025jul.sas7bdat` | `a4af1745c6954cdc5bbdf63d4f62501126c481f749d695730c02cfbc765dd7fd` |
| `SAS Output/outcome_mortality.sas7bdat` | `73be203068780cf10aa9230a3dc95660158501994da13a53ea0d4c77c77eba3b` |
| `SAS Output/outcome_readmission.sas7bdat` | `7c603b36b1f0f9e7ec0da7d563bbe8add45009240e0e1053f649d79937913f76` |
| `SAS Output/outcome_safety.sas7bdat` | `efbc9df312466a5d75e6cae2d68bd670fcb81e129ffecf6ef06692fb21f2af0e` |
| `SAS Output/process.sas7bdat` | `ee0b801d45d4d4a6df90d5d0789b419ec65318977d40c5aec37ed06d85f12d77` |
| `SAS Output/ptexp.sas7bdat` | `71c08e710317289f92153b994a328bd7d040ba20891df12bca494bbf40994228` |
| `SAS Output/star_2025jul.sas7bdat` | `200981a22567980cd7140a93c7aa0040b40538f25b58666b098e2096307af1ad` |
| `SAS Output/std_data_2025jul_analysis.sas7bdat` | `a074615179148bb774494055c45aa858ab23600bafb9b0866bb325ec69afa015` |
| `SAS Output CSV/LESS100_MEASURE.csv` | `ae049a45f9cac954fc109a11d486f09a58c4d351825f55a23380f05cf8960a02` |
| `SAS Output CSV/MEASURE_AVERAGE_STDDEV_2025JUL.csv` | `2ce4671bf1254400fc145143c37b69fee5a894f7e6a232fb955014c5b9cf88f8` |
| `SAS Output CSV/NATIONAL_AVERAGE_2025JUL.csv` | `d54d9096208262755be6c5521cf9bbdc26c97289043fb2e0c30ffbb1da6e2f84` |
| `SAS Output CSV/OUTCOME_MORTALITY.csv` | `b34bb8115cdf5dfb1f10ea8d0c80864427f71c3879a79ea9655f78d12bd2545f` |
| `SAS Output CSV/OUTCOME_READMISSION.csv` | `85a3923eaca27556db1f8cd18b1f20a9f695691cd35716fbdabf7b8251e9217e` |
| `SAS Output CSV/OUTCOME_SAFETY.csv` | `81a3ae67fc5520288cf8cc48e1333da8736fbbbcd12b043fe258ee97c763af2c` |
| `SAS Output CSV/PROCESS.csv` | `cfd95aece34c96f87668245e0bde1f520a36318f9c807239234a89c4104a74e6` |
| `SAS Output CSV/PTEXP.csv` | `696aab68bef793e1ecbb57abaf9742c170388de553f3bc099382d797f7db651b` |
| `SAS Output CSV/STAR_2025JUL.csv` | `e53582492023cb2ebbd466acd25eab3ee2faea45788373a44127a8c4533a812a` |
| `SAS Output CSV/STD_DATA_2025JUL_ANALYSIS.csv` | `69ef8885e8500129247d65f709960a4ead9dfa81a1cd2f8ba16d8eeac1783a34` |
| `SAS Programs/0 - Data and Measure Standardization_2025Jul.sas` | `b02762a257a48740000a01792afc50a38f4ba1493a1e06dfcf940fb9f8046ece` |
| `SAS Programs/1 - First stage_Simple Average of Measure Scores_2025Jul.sas` | `68a6880f173ea19f0653ec3245f45cadc4c6801bd0f5d8e46b8c325ddfc53332` |
| `SAS Programs/2 - Second Stage_Weighted Average and Categorize Star_2025Jul.sas` | `7df4aad8fc0a61c0a571730972fa4190616268c94df844af730d5696e4927115` |
| `SAS Programs/SAS_Log.log` | `12a6caf15f62a29f1374295f992b98eb1a2dd813f9081d7db40581f83b242723` |
| `SAS Programs/Star_Macros.sas` | `1f9a62fd4b7a07f5acfa18e51946246bcd354e92cce2fb1136d2ec8a2ee67f2c` |
| `StarRatings_SASPackDoc_Jul2025.pdf` | `e1fdad0e4c9dbde43182005e888d044057fc0a7d19e3dca4104fe6562febab42` |
| `Starrating/alldata_2025jul.csv` | `8790aa7ef3b39a4724220ed84c52999b77b2c6c4ed8c19b2dc75e76cd62ebd90` |
| `Starrating/alldata_2025jul.sas7bdat` | `875b1ba9d299e611a58909533b8301d2776ea982ca75937b6746290ee837724f` |

## Findings

### Missing artifacts

None. Every dataset the code writes to `R.` was supplied, and every supplied golden output is
written by exactly one program.

### Duplicated artifacts

None unexpected. Each golden output is intentionally supplied twice (SAS binary and CSV), and each
pair matches in rows and columns.

### Inconsistencies and notes for implementers

1. **Hardcoded paths.** Program 0 sets `PATH1`–`PATH3` to `G:\breakthrough\...` Windows paths
   (lines 15–17). The folder names in those paths (`SAS output`, `SAS pack`) also differ from the
   repository layout (`SAS Output`, `SAS Programs`). The programs cannot run as supplied without
   editing these lines.
2. **Session state.** Programs 1 and 2 depend on macros and variables defined in earlier programs,
   so they cannot run on their own.
3. **Empty exclusion list.** `less100_measure` has 0 rows because no measure was reported by 100 or
   fewer hospitals in this release. This is expected. It also causes the log's only warning (line
   329, `MEASURE_EXCLUDE not resolved`), which Program 0 handles with a conditional drop
   (lines 118–131). A Python port must handle an empty exclusion list the same way.
4. **Hospitals without a star.** 1,675 of 4,566 hospitals have `report_indicator = 0` and a missing
   `star`. The 2,891 rated hospitals are distributed as 233 (1 star), 661 (2), 939 (3), 767 (4),
   and 291 (5). Missing stars are expected and are not data errors.
5. **Missing domain scores.** A hospital's `grp_score` is missing only when it has zero
   non-missing measures in that domain (`total_cnt = 0`). A score exists even with one or two
   measures; the three-measure threshold applies to reporting eligibility, not to score
   calculation. Non-missing counts: mortality 3,682; safety 3,390; readmission 4,322; patient
   experience 3,179; timely and effective care 4,544.
6. **Name casing.** Golden-output CSV file names are uppercase, while the input CSV
   (`alldata_2025jul.csv`) and all SAS binary file names are lowercase, and the code
   and column names use mixed case. SAS names are case-insensitive, so canonicalize to uppercase at
   ingestion, as described in [Contributing](../CONTRIBUTING.md#python-names-and-casing).
7. **Leading zeros.** `PROVIDER_ID` values have leading zeros and must be loaded as strings.
8. **Commented-out input.** Program 2 line 209 contains a commented-out dataset,
   `outcome_readmission_avg_DE`, which suggests an earlier version of the pipeline included an
   additional readmission average.