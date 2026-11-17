# Abt technical validation report

**Draft for Abt review**

Break Through Tech AI Studio · Abt Global 1A · SASGuard

**VERIFIED for the supplied CMS July 2025 release.** On November 16, 2026, the team replayed Programs 0, 1, and 2 in Docker from a clean checkout of `42c98db`. All ten outputs passed comparison with the supplied SAS reference files. The replay covered 4,566 hospitals, including 2,891 eligible for a rating. All star assignments matched exactly. Independent teammate replay and Abt release approval are pending.

## What ran

| Stage | Code origin | Docker execution | SAS comparison |
|---|---|---|---|
| 0. Measure standardization | Saved Luna candidate after two automatic repair attempts. | Exit 0. Used the protected July 2025 hospital input, staged as full-precision CSV. | 3/3 passed |
| 1. Domain scoring | Human-written Python reference, `reference_python/domain_scoring.py`. | Exit 0. Used the standardized output from this Program 0 run. | 5/5 passed |
| 2. Eligibility and star assignment | Saved Luna candidate with a manual `STRICT=1` correction applied to a copy. | Exit 0. Used the five domain outputs and standardized measures from this Python chain. | 2/2 passed |

The November 10 Luna runs used medium reasoning and allowed two repair attempts per program. Program 0 used 45,899 input and 9,177 output tokens across three requests. Program 2 used 58,481 input and 22,418 output tokens across three requests. Dollar cost was unrecorded. The November 16 replay made zero model requests. [Program 0 experiment](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/blob/42c98dbfd8a7013d52939db92b56fea6aa7c448f/docs/experiments/2026-11-10-program0-automatic-repair-v2.md) · [Program 2 experiment](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/blob/42c98dbfd8a7013d52939db92b56fea6aa7c448f/docs/experiments/2026-11-10-program2-luna-baseline.md)

## Comparison results

The host validator checked row and column counts, schema, missingness, keys and values against the supplied SAS files. The actual and expected dimensions below agreed. Every artifact had zero missing or extra keys, zero missing or extra columns, zero missingness mismatches, and zero cells outside its comparison rule. The national-average column count excludes the temporary row key the host uses for comparison.

| Program | Artifact | Rows | Columns | Alignment | Result |
|---|---|---:|---:|---|---|
| 0 | `LESS100_MEASURE` | 0 | 2 | `MEASURE_NAME` | Pass |
| 0 | `MEASURE_AVERAGE_STDDEV_2025JUL` | 5 | 49 | `_STAT_` | Pass |
| 0 | `STD_DATA_2025JUL_ANALYSIS` | 4,566 | 94 | `PROVIDER_ID` | Pass |
| 1 | `OUTCOME_MORTALITY` | 4,566 | 21 | `PROVIDER_ID` | Pass |
| 1 | `OUTCOME_SAFETY` | 4,566 | 23 | `PROVIDER_ID` | Pass |
| 1 | `OUTCOME_READMISSION` | 4,566 | 29 | `PROVIDER_ID` | Pass |
| 1 | `PTEXP` | 4,566 | 23 | `PROVIDER_ID` | Pass |
| 1 | `PROCESS` | 4,566 | 31 | `PROVIDER_ID` | Pass |
| 2 | `STAR_2025JUL` | 4,566 | 27 | `PROVIDER_ID` | Pass, 0 star mismatches |
| 2 | `NATIONAL_AVERAGE_2025JUL` | 1 | 9 | Single row | Pass |

IDs, rating decisions, eligibility, peer groups and counts use exact rules. Calculated fields use the fixed per-column policies, with absolute and relative tolerances of `1e-12` where configured. For those fields, the allowed difference is `1e-12 + 1e-12 × abs(SAS value)`. Program 0 statistic rows `N`, `MIN` and `MAX` use exact comparisons. Programs 1 and 2 passed separate exact checks for values copied from their actual inputs. The largest observed absolute cell difference was approximately `1.84e-13`. All 29 protected files passed integrity verification. [Comparison policies](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/tree/42c98dbfd8a7013d52939db92b56fea6aa7c448f/configs)

## Failure and correction

The original Program 2 candidate completed in Docker, and national averages matched SAS. The first remaining difference was in the `STAR` column. Two assignments differed, both in the five-domain peer group. The same two differences appeared when we reran the candidate with SAS intermediates. Correcting the percentile formula in isolation left the output identical to the original. Applying `STRICT=1` while recomputing second-pass centers kept distant observations out of the means and cleared both mismatches under both input conditions. The final star join still uses the absolute cluster ID to map an observation to its nearest cluster’s star. [STRICT experiment and replay](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/blob/42c98dbfd8a7013d52939db92b56fea6aa7c448f/docs/experiments/2026-11-16-program2-strict-replay.md)

## Reproduction and audit evidence

Use the project Python environment and the saved candidate pair from the restricted replay package. Start in a checkout of `42c98dbfd8a7013d52939db92b56fea6aa7c448f` with `sasguard-replay-inputs` beside it. For reproducibility, record the runner image ID and platform with the output. The recorded replay used a Windows host and Linux amd64 Docker runner with Python 3.11.18.

```text
docker build -f Dockerfile.runner -t sasguard-runner:replay .
python -m sasguard.cli verify-integrity
python scripts/replay_program2_strict.py ../sasguard-replay-inputs/program0-candidate.py ../sasguard-replay-inputs/program2-candidate.py --image sasguard-runner:replay
```

The script verifies both candidate hashes and the Program 2 policy hash. It runs the candidates through Docker and reads the SAS reference artifacts on the host. `summary.json` links the Program 0 and Program 1 reports, and `validation.json` within the same run directory gives the two Program 2 comparisons. All records are under `reports/runs/`. [Replay script](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/blob/42c98dbfd8a7013d52939db92b56fea6aa7c448f/scripts/replay_program2_strict.py) · [Validation tracking](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/issues/71)

| Evidence | SHA-256 |
|---|---|
| Docker runner image ID | `50903cf590be0dc3a6b3cc08ae3772d34d3d1ab555daada0fdff7c029796b5df` |
| Protected hospital input, `alldata_2025jul.sas7bdat` | `875b1ba9d299e611a58909533b8301d2776ea982ca75937b6746290ee837724f` |
| Project configuration, `cms_2025jul.yaml` | `d6e16a00a5cc86a2e36079d2dc59dd2ced072f50d4595e4a823575fe80c3a64a` |
| Protected-file manifest | `74d74ce25c33b0c7a1a7c2db73b763c806194b365556c6bb43461d94492b4ad0` |
| Program 0 comparison policy | `9cb24f3881d27e2fe4130b68df73ec8a4bd9a2ab7919cf970ffa37122a1c72a7` |
| Program 1 comparison policy | `8c53c20f65dd28c504c7adbb83fed29967489fa144d43e31bc49ceb6e35cab6b` |
| Program 2 comparison policy | `05af4a42413c5cedf3bad28a069530d0333f9b7599dc693a467629e3647e962f` |
| Program 0 candidate | `5c03a29162659ee102cecaa0eb889e4cbeaf410d3638b5c161c8032668be822b` |
| Program 1 human reference | `38cb81b81006bb50680dba6b1c9b2955b0b98474924ffb890182f695ec9893de` |
| Program 2 original Luna candidate | `77418712e677a0793e1cde1d04d69339e89c8adf89a6968fc4fd101b9532c01f` |
| Program 2 corrected candidate | `642269854ee25edfab56ab1a4958675be1eba895bfee2cc7629d465a2c6674f5` |
| Final star-rating CSV | `92daf9bb065b5b3d000336340aba7d137376961e914490924b7b8f5fd80fa4f3` |
| National-average CSV | `eb850aefa91cbf96b7bb2979fe03758dc39b594679cc5680289b7c97e793afb3` |

The source record for this draft is `program2-strict-replay-8703ccee-5c42-4eef-b54b-fa88d3c48872`. The stage reports retain full column lists, the other eight output hashes and the exact copied-input checks.

## Review and release status

| Review | Status |
|---|---|
| Team replay and deterministic validation | Complete for July 2025, 10/10 artifacts passed |
| Independent teammate replay | Pending Tony’s result in #71. Record date, OS, commit, image ID, passes by stage, star mismatches and protected-file check. |
| Abt technical review and approval to share with CMS | Pending. Abt will confirm the handoff fields and select any approved results file. |

The evidence applies to one supplied release and the hybrid chain above. Another CMS quarter and a fresh model repair of Program 2 remain unverified. The passing replay still uses the original percentile formula, so broader FASTCLUS behavior remains open. [FASTCLUS #69](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/issues/69) · [Model repair #70](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/issues/70) · [Reporting #52](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/issues/52)
