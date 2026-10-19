# Execute a Program 0 candidate

The host command stages a standalone Python candidate, runs it through the existing isolated
Docker runner, and collects the three Program 0 CSVs. It makes no model call. Numerical comparison
against SAS is the separate validator tracked in issue #44.

## Candidate contract

The candidate must be one self-contained `.py` file. It may use the installed runner libraries,
including pandas and NumPy. Sibling Python files are not staged. Read the hospital input from:

```python
from pathlib import Path
import os

inputs = Path(os.environ["SASGUARD_INPUT_DIR"])
outputs = Path(os.environ["SASGUARD_OUTPUT_DIR"])
input_file = inputs / "alldata_2025jul.csv"
```

The staged input directory contains only the hospital CSV and `contract.json`. The contract
declares the input filename and columns, textual identifier handling, environment variables,
and required output filenames. It is derived from the input and fixed controller rules.
It contains no trusted output values or reference implementation.

Write exactly these CSV files in the output directory:

* `less100_measure.csv`
* `measure_average_stddev_2025jul.csv`
* `std_data_2025jul_analysis.csv`

Names match the human Program 0 reference in PR #53. The exclusion table may contain only its
header when no measure is excluded. Output files must have a nonblank header, unique column names
ignoring case, valid CSV quoting, and records with the same number of fields as the header.
No output symlinks, Windows reparse points, or extra files are accepted, apart from the worker's
`.tmp` directory. Reparse points are checked before resolving a path because a link created by
Linux Docker may not appear as a normal symlink to Python on the Windows host.

## Run on Windows or macOS

Use the host Python 3.11 or 3.12 environment from [Development setup](development-setup.md)
and start Docker. Build the runner if it is not already available:

```text
docker build -f Dockerfile.runner -t sasguard-runner:local .
```

The following command works in PowerShell and zsh with that environment active:

```text
python -m sasguard.cli run-program0-candidate generated/program0.py
```

Without activation, replace `python` with `.\.venv\Scripts\python.exe` in PowerShell or
`./.venv/bin/python` in zsh. Run from the repository root on the host, not inside the development
container. `--project-root` selects another checkout, `--image` selects an existing runner image,
and `--timeout-seconds` sets an execution timeout between 0.01 and 600 seconds.

Each invocation creates a fresh directory under `reports/runs/program0-candidate-<UUID>/`:

| Path | Contents |
|---|---|
| `source/main.py` | Byte-preserving copy of the selected candidate. |
| `input/` | Hospital CSV and input-derived contract. |
| `output/` | Candidate-produced files. |
| `manifest.json` | Source, input, and candidate hashes; controller environment; Docker execution result and image identity. |
| `staging.json` | Exact candidate byte hash, contract hash, and controller hash. |
| `report.json` | Execution/collection outcome and per-artifact paths, hashes, row counts, and columns. |

These local run folders are ignored by Git. The original candidate and previous runs are not
modified. Supplied artifact integrity is checked before staging and after execution.

Only `source/`, `input/`, and `output/` are mounted in Docker. Trusted SAS outputs, reference Python,
host credentials, and the report directory are not mounted. Generated Python has no network
access, a read-only source and input, and the runner's existing resource limits.
See [Isolated runner](isolated-runner.md) for those boundaries and their limitations.

## Interpret the report

| Status | Meaning |
|---|---|
| `syntax_error` | Candidate does not compile; Docker execution did not start. |
| `execution_failed` | Candidate exited with a nonzero code. |
| `timed_out` | Runner stopped the candidate at its timeout. |
| `runner_error` | Docker or the host controller could not complete execution/collection. |
| `policy_violation` | An escaped, symlinked, or undeclared output was detected. |
| `missing_outputs` | At least one declared CSV is absent. |
| `malformed_outputs` | At least one declared CSV is unreadable or violates the CSV transport contract. |
| `integrity_failed` | A protected supplied artifact changed after execution. |
| `ready_for_validation` | All three declared CSVs are readable and ready for host-side SAS comparison. |

The command exits with code 0 for `ready_for_validation`, 1 for recorded execution or collection
failures, and 2 for startup failures such as an invalid candidate path or a failed initial integrity
check. Every report keeps `validation_status` as `not_run` and `human_review` as `not_recorded`.
Successful execution and readable CSVs alone do not establish correct values or analytical schemas.

## Handoff to the shared validator

```python
from pathlib import Path
from sasguard.execution.program0 import run_program0_candidate

result, report_path = run_program0_candidate(Path("."), Path("generated/program0.py"))
if result.ready_for_validation:
    output_directory = report_path.parent / "output"
    # Pass output_directory to the host-side three-artifact validator from #44.
```

`result.artifacts` maps each filename to its path relative to the run directory, hash, row count,
and canonical column names. The validator should check the recorded hashes before comparing
those files, then apply its own artifact-specific schema, key, missingness, and numerical rules.
It can read trusted SAS artifacts on the host after the candidate container has stopped.

This branch provides the execution and collection side of #47. End-to-end integration and the
issue's final acceptance depend on #44. The model-generated baseline remains tracked in #48.
