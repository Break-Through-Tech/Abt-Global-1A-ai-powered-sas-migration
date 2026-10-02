# Program 0 Python translation

This is a human-written translation of the supplied July 2025 Program 0. It selects reported measures, removes hospitals with no active measures, calculates raw measure statistics, and produces the standardized analysis data used by Programs 1 and 2. The measure lists and direction rules come from the executable SAS program, not from its outdated Process-measure comment.

The translation function reads a hospital table and returns three tables. It does not open the trusted SAS outputs. A separate test reads those outputs and checks the result.

## Run it with Docker

The same commands work in PowerShell and macOS zsh from the repository root:

```sh
docker compose run --rm sasguard sasguard run-program0 --output-directory reports/runs/program0-2025jul
docker compose run --rm sasguard pytest tests/test_program0.py tests/integration/test_program0_reference.py
docker compose run --rm sasguard sasguard verify-integrity
```

The command writes `less100_measure.csv`, `measure_average_stddev_2025jul.csv`, and `std_data_2025jul_analysis.csv` in the chosen directory. It accepts only a subdirectory of `reports/runs` and refuses to overwrite existing outputs. Use a new directory name for another run. The supplied `data/` directory remains read-only in Docker.

## What has been checked

For the supplied July 2025 input, all 46 measures pass the reporting-count filter and all 4,566 hospitals remain. The Python outputs match the three trusted SAS artifacts in row and column counts, column order, provider IDs, and missingness. Excluded measures are empty in both versions. Raw counts, minima, maxima, and unchanged analysis columns match exactly. Means, sample standard deviations, and 46 standardized columns match with absolute and relative tolerances of `1e-12`. The largest observed absolute differences were about `1.1e-13` in the statistics table and `1.6e-13` in the analysis table.

These comparisons establish numerical parity for these three July 2025 outputs at that tolerance. They do not establish byte-identical files, a reusable SAS parser, an AI translation result, or parity for Programs 1 and 2. Synthetic tests cover the exclusion threshold, hospital removal, direction reversal, and invalid input schemas. Zero-variance measures are rejected because their SAS behavior has not been established for this case.
