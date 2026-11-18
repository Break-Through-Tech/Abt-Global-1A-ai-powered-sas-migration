# Execute a Program 0 candidate

The host command stages a standalone Python candidate, runs it through the existing isolated
Docker runner, and collects the three Program 0 CSVs. It makes no model call. With `--validate`,
it calls the shared host-side validator after execution and collection.

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

To validate against SAS using the supplied SAS source input at full precision:

```text
python -m sasguard.cli run-program0-candidate generated/program0.py --input-format sas7bdat --validate
```

The default `--input-format csv` still copies the supplied CSV unchanged. In `sas7bdat` mode,
the host reads only the supplied `alldata_2025jul.sas7bdat` input and exports it to the staged
`alldata_2025jul.csv` using 17 significant digits. The candidate still receives the same CSV
filename and contract, not a SAS binary or any trusted output. Source input and staged CSV hashes
are recorded separately in `staging.json`; the manifest identifies the chosen original input.

The supplied CSV differs from the supplied SAS input in 9,494 cells across 15 numeric columns,
with maximum absolute difference about `1.11e-16`. Those small input-export differences can
change raw extrema, which the validator deliberately checks exactly. The reference Docker
control therefore uses the lossless SAS-input export. CSV-based failures are retained rather
than hidden by wider tolerances. Do not silently switch input sources between experiments.

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

Without `--validate`, the command exits with code 0 for `ready_for_validation`, 1 for recorded
execution or collection failures, and 2 for startup failures. With `--validate`, code 0 also
requires a passing SAS comparison. Validation failures and validator errors exit with code 1.
Human review remains `not_recorded`. The collection status stays separate from validation.
Successful execution and readable CSVs alone do not establish correct values or analytical schemas.

## Handoff to the shared validator

```python
from pathlib import Path
from sasguard.execution.program0 import (
    CandidateInputFormat,
    run_program0_candidate,
    validate_collected_program0,
)

result, report_path = run_program0_candidate(
    Path("."),
    Path("generated/program0.py"),
    input_format=CandidateInputFormat.SAS7BDAT,
    validator=validate_collected_program0,
)
print(result.execution_result, result.validation_status)
```

`result.artifacts` maps each filename to its path relative to the run directory, hash, row count,
and canonical column names. The validator should check the recorded hashes before comparing
those files, then apply its own artifact-specific schema, key, missingness, and numerical rules.
It can read trusted SAS artifacts on the host after the candidate container has stopped.

The local integration combines #53, #55, and corrected #58. These PRs still need team review
and merging. Its passing reference control is human-written, not a model-generated baseline.
The model-generated baseline remains tracked in #48.

## Validator adapter

The Python API accepts an optional `validator` callback. The CLI enables it only with `--validate`.
The callback runs on the host after successful execution, complete collection, and the post-run
protected-artifact check. It receives the resolved project root, output directory, and original
`filename -> SHA-256` mapping from collection. It must check these hashes before comparing values.
The adapter does not refresh hashes to accept changed outputs, read SAS references, or implement
numerical comparison rules.

Tony confirmed the proposed call on #44:

```python
validate_program0_outputs(project_root, output_directory, expected_sha256)
```

The implementation is `sasguard.verification.program0.validate_program0_outputs`.
Our callback uses `CandidateValidationResult(status=..., artifact_results=..., errors=...)`, where
`artifact_results` maps the three CSV filenames to the existing `ArtifactComparison` objects.
The wrapper `validate_collected_program0` converts the shared result without discarding its
per-file errors. `report.json` retains them in `validation_errors`, separately from a callback
exception in `validation_error`. Tests with fake callbacks do not establish SAS parity.

The adapter records these validation outcomes separately from execution and collection:

| Validation status | Meaning |
|---|---|
| `not_run` | No callback was supplied, or execution/collection did not qualify. |
| `passed` | The callback returned passing SAS comparisons for all three declared artifacts. |
| `failed` | At least one returned SAS artifact comparison failed. |
| `hash_mismatch` | The validator reported that a collected output changed. |
| `missing_outputs` | The validator reported a missing file after collection. |
| `malformed_outputs` | The validator could not read an output after collection. |
| `validator_error` | The callback raised an exception or returned inconsistent metadata/results. |

The candidate's collection `status` and `execution_result` do not change when validation fails.
A claimed pass with missing comparisons, a mismatched artifact name, or a non-SAS authority is
rejected. Callback errors never become numerical mismatches or passes. Human review remains
`not_recorded`. An existing validation result is not silently replaced by calling the adapter
again. The adapter returns a new report; `run_program0_candidate` saves that report as part of
the fresh run. It does not edit older run records.

Run the adapter tests without Docker or SAS execution:

```text
python -m pytest tests/test_program0_validation_adapter.py tests/test_program0_execution.py -q
```

The synthetic Docker tests exercise the callback handoff, saved report, and separation from
the execution manifest. They use stub validation results and synthetic CSVs, not trusted SAS
comparisons. They confirm that a real container can produce the files before a host callback
records its outcome. Runtime failures, timeouts, and rejected output paths must never invoke
that callback. These stub checks do not establish Program 0 numerical parity.

With `SASGUARD_RUN_DOCKER_TESTS=1` set in the host environment, run:

```text
python -m pytest tests/integration/test_program0_candidate_docker.py -q
```

`tests/integration/test_program0_validated_execution.py` is a separate real-data test. It runs
a standalone copy of the human Program 0 reference in Docker with the lossless input staging,
then checks all three outputs against SAS on the host. Four executable but wrong copies change
one statistic or skip a direction reversal; all must fail. A CSV-source control retains the
known export-precision failure. These are human controls, not model-generated translations.

```text
python -m pytest tests/integration/test_program0_validated_execution.py -q
```

## Save comparison evidence and summarize a run

The real validator wrapper now saves `validation_evidence` in `report.json`: policy snapshots,
exact statistic rows, source/configuration/loader hashes, trusted reference hashes, original
collected-output hashes, and the candidate hash. The wrapper checks those files before and after
comparison. It does not put reference rows or source code in that evidence object.

Use the reporting command on the saved run directory to create an internal handoff, technical
record, and privacy-limited JSON without rerunning code:

```text
python -m sasguard.cli report-run reports/runs/program0-candidate-<UUID>
```

See [Scoped run reports](scoped-run-reports.md). Older runs without comparison snapshots remain
readable but cannot establish current verification. Reports do not infer human authorship or
AI generation from a standalone candidate file or a missing model identifier.
