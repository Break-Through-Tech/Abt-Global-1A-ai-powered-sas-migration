# Mortality prototype

This prototype checks a bounded reference Python reproduction of the supplied
Program 1 Mortality `grp_score` macro. It reads the supplied Program 0 standardized SAS
binary, `STD_DATA_2025JUL_ANALYSIS`, then compares the resulting Mortality artifact with
the trusted `OUTCOME_MORTALITY` SAS binary.

The comparison covers 4,566 providers and 21 columns, aligned by `PROVIDER_ID`:

- The seven standardized measure columns, seven availability flags (`C1` through `C7`),
  and `TOTAL_CNT` must match exactly.
- `MEASURE_WT`, `SCORE_BEFORE_STD`, `MEAN`, `STDDEV`, and `GRP_SCORE` use absolute and
  relative tolerances of `1e-12`. These tolerances are fixed in
  [`configs/mortality-comparison-policy.json`](../configs/mortality-comparison-policy.json)
  before the first execution. The strict tolerance allows for floating-point roundoff;
  passthrough measures are written to CSV with 17 significant digits to preserve their
  binary floating-point values on roundtrip.

The first Docker run passed the comparison for all 4,566 rows and 21 columns. This result
applies to the supplied cohort, reference implementation, and committed policy.

The reference computes the available-measure count, its reciprocal weight, the weighted
score before standardization, the cohort mean, the sample standard deviation (`ddof=1`),
and the standardized group score. All-missing rows remain in the output with zero flags
and count and missing computed scores. The prototype rejects a cohort without at least
two varying nonmissing scores.

This is the plan's human-reference baseline for one program stage. It is not a
model-backed translation experiment, a full pipeline run, or evidence of end-to-end
correctness. It does not establish that
the implementation reproduces every SAS semantic or handle degenerate cohorts as SAS
would. The comparison says only whether this implementation matches these selected
columns for the supplied cohort under the committed policy.

## Trust boundary and reports

The host controller verifies the protected-artifact manifest before and after the run.
It also checks the project configuration and comparison policy against the frozen hashes
in the trusted controller, before execution and validation. Changes to either file require
an explicit controller-baseline update and teammate review. Automatic repair must not
edit these trusted files or the controller.
It snapshots only `mortality.py` into `source/` and the Program 0 intermediate into `input/`.
It hashes the staged copies and checks them against the originals before execution. The
run manifest records hashes for the SAS programs, SAS macro, project configuration,
comparison policy, reference implementation, and input. It records execution details and
the reference source and artifact comparison after those results are available.
The trusted Mortality output is never mounted in Docker. The controller loads that output
and performs the comparison on the host after the container exits. The runner has no
network access and receives no host credentials through its environment.

Each run writes to a unique `reports/runs/mortality-<UUID>/` directory. It contains
`manifest.json`, `execution.json`, `comparison.json`, the staged `source/mortality.py`,
the staged input, and generated output. The comparison report records the requested
runner image tag and SHA-256 hashes for the trusted reference file and generated output.
The requested image tag is mutable and does not pin an image digest. Reports include the
selected policy and comparison results, but do not copy raw trusted-output rows into the
report. The generated output and staged input are local run artifacts and should be
handled according to the repository's data-handling requirements.

The comparison key is `PROVIDER_ID`. Input column names are normalized to uppercase by
the reference implementation, and duplicate names that collide after uppercasing are
rejected. The recorded hashes identify the files used in this run. They do not provide
broader gold-output provenance or prove that the supplied reference came from a particular
SAS execution.

## Run the prototype

Use Python 3.11 or 3.12 and Docker Desktop with its Linux engine running, or a Docker
Engine that can run Linux containers. From the repository root, create a development
environment and build the isolated runner image.

On macOS with zsh:

```zsh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
docker build -f Dockerfile.runner -t sasguard-runner:test .
sasguard mortality-prototype --project-root . --image sasguard-runner:test
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
docker build -f Dockerfile.runner -t sasguard-runner:test .
sasguard mortality-prototype --project-root . --image sasguard-runner:test
```

The command exits with status 0 when the comparison passes, 1 when it finds a mismatch,
and 2 when it cannot run. Both comparison outcomes include the report path. A report is
written under `reports/runs/` for successful Docker execution; setup, integrity, or
execution errors can stop before a comparison report exists.

## Optional Docker integration checks

The integration tests require the same runner image and Docker engine. They are opt-in.

On macOS with zsh:

```zsh
SASGUARD_RUN_DOCKER_TESTS=1 python -m pytest -m docker_integration
```

On Windows PowerShell:

```powershell
$env:SASGUARD_RUN_DOCKER_TESTS = "1"
python -m pytest -m docker_integration
Remove-Item Env:SASGUARD_RUN_DOCKER_TESTS
```

The opt-in suite includes a Docker replay regression for the Mortality comparison as well
as tests of the shared isolated runner. The replay checks that the supplied reference
continues to match the trusted artifact under the committed comparison policy.
