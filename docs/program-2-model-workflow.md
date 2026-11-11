# Program 2 model experiment

`model-program2` generates standalone Python for the supplied Program 2 SAS, executes
it in isolated Docker, and compares the hospital star file and national averages with
the supplied SAS binary targets. The model cannot decide whether its translation passed.

## Inputs and scope

Program 2 consumes the five domain outputs from Program 1 and the standardized measure
table from Program 0. The model receives the SAS programs and macro dependency, input
column names, and an execution contract. Programs 0 and 1 provide the context needed
to resolve macro variables. The requested translation is Program 2 only.

No hospital rows, trusted Program 2 output values, expected hospital counts, or human
Python implementations are included in the prompt. The container receives six input
CSVs and the unchanged candidate. Target references and the validator remain on the host.

Select one input condition explicitly:

* `--upstream-chain` uses a saved, verified Program 0 to Program 1 Python chain. The host
  confirms its hashes, recomputes domain comparisons, and checks exact input preservation
  before staging the six CSVs unchanged. Program 1 remains human-reference Python.
* `--reference-inputs` uses the supplied SAS intermediates to evaluate Program 2 in
  isolation. The host stages full-precision CSV exports and records this distinct condition.

## Run

Use the host Python environment in [Development setup](development-setup.md), start
Docker, and build `Dockerfile.runner` if needed. Read the API key into the host environment.

PowerShell:

```powershell
$credential = Read-Host 'API key' -AsSecureString
$env:SASGUARD_API_KEY = [System.Net.NetworkCredential]::new('', $credential).Password
python -m sasguard.cli model-program2 --upstream-chain reports/runs/PROGRAM01-CHAIN --image sasguard-runner:local
Remove-Item Env:SASGUARD_API_KEY
```

macOS zsh:

```zsh
read -s 'SASGUARD_API_KEY?API key: '
export SASGUARD_API_KEY
python -m sasguard.cli model-program2 --upstream-chain reports/runs/PROGRAM01-CHAIN --image sasguard-runner:local
unset SASGUARD_API_KEY
```

Replace `PROGRAM01-CHAIN` with the verified chain directory. For a standalone control,
replace `--upstream-chain reports/runs/PROGRAM01-CHAIN` with `--reference-inputs`.
An exact Docker image ID can replace the tag for reproducibility.

The command uses `gpt-6-luna`, medium reasoning, at most 16,384 output tokens per request,
and at most two automatic repairs. `--repair-attempts 0` records only the direct baseline.
There are no automatic transport retries. Docker execution has a 120-second limit per
attempt, with no network access and read-only source and inputs.

## Fixed acceptance rules

`configs/program2-comparison-policies.json` is fixed before generation. Provider keys,
eligibility flags, available-measure counts, qualifying-group counts, peer-group labels,
and star assignments compare exactly. Missingness must match. Calculated domain scores,
redistributed weights, summary scores, and national averages use absolute and relative
tolerances of `1e-12`. Fixed base weights have zero tolerance.

Copied domain scores must also match the actual staged input exactly. This separate
check prevents a tolerance against SAS from hiding changes made to input scores.

The national-average dataset has one row and no natural key. Host verification adds a
temporary textual row index to both tables for the shared comparator. Extra rows fail;
the candidate must not add this reserved key to its CSV.

The host retains every computable artifact comparison. A malformed star file does not
erase a national-average result. Only aggregate schemas, mismatch counts, missingness
counts, affected column names, and fixed policies enter automatic repair feedback.
Raw row keys, reference values, logs, and exception messages are excluded. Execution
failures can expose an allowlisted exception class without its message.

An executable generic KMeans translation is not sufficient for a pass. FASTCLUS
initialization, updates, outlier behavior, ordering, and stars must produce matching
outputs under the fixed rules.

## Evidence

Each experiment creates a new ignored `reports/runs/program2-model-*` directory:

```text
program2-workflow.json
summary.md
messages.json
input/
attempt-0/
  attempt.json
  request.json
  response.json
  source/main.py
  execution.json
  validation.json
  diagnostics.json
  output/
```

Only stages that ran have corresponding files. Further attempts have separate
directories and parent hashes. Requests, responses, candidate bytes, execution records,
and validation records have saved hashes. Project, policy, source, input, and prompt
hashes are checked between stages. Usage is recorded; dollar cost is not estimated.

`summary.md` separates generation, execution, and SAS comparison. `validation.json`
contains artifact details and the input-copy comparison. These local records are not
signed provider attestations. They do not establish human review, client release
approval, or accuracy on other quarters. A hybrid chain retains the human Program 1
reference designation even if all Program 2 comparisons pass.

Exit status zero requires both target artifacts and the exact input-copy check to pass.
Status 1 means the recorded experiment failed or encountered an error; status 2 means
it could not start. Credentials and generated artifacts are excluded from Git.
