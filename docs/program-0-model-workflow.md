# Program 0 model workflow

`model-program0` sends a checked Program 0 prompt to the Responses API, saves the
unchanged generated Python, runs it in isolated Docker, and compares all three outputs
with the supplied SAS binary references. Run the controller on the host with Python 3.11
or 3.12 and the project's locked dependencies. Docker Desktop must be running.

This implements the Program 0 experiment in #48 using the execution and validation
work from #47 and #44. It does not translate the full pipeline.

## Prepare the environment

Use the host environment described in [Development setup](development-setup.md).
Build the isolated runner from the repository root:

```text
docker build -f Dockerfile.runner -t sasguard-runner:local .
python -m sasguard.cli preview-program0-prompt --input-format sas7bdat
```

Read the saved `prompt.txt` and `contract.json` before sending them. The payload contains
Program 0 SAS, its macro dependency, input column names, and the execution contract.
It contains no input rows, reference output values, or human-reference Python.
The original preview remains a preparation record after execution.

Use `sas7bdat` to stage full-precision input from the original SAS input dataset.
The supplied CSV export loses bits in some decimals and can fail exact passthrough and
extrema checks. Selecting a different input format changes the experiment and is recorded.

## Run on Windows PowerShell

Read the key without placing its value in a command or file:

```powershell
$credential = Read-Host 'API key' -AsSecureString
$env:SASGUARD_API_KEY = [System.Net.NetworkCredential]::new('', $credential).Password
python -m sasguard.cli model-program0 reports/runs/PROGRAM0-PREVIEW --image sasguard-runner:local --repair-attempts 1
Remove-Item Env:SASGUARD_API_KEY
```

Replace `PROGRAM0-PREVIEW` with the directory printed by the preview command.

## Run on macOS zsh

```zsh
read -s 'SASGUARD_API_KEY?API key: '
export SASGUARD_API_KEY
python -m sasguard.cli model-program0 reports/runs/PROGRAM0-PREVIEW --image sasguard-runner:local --repair-attempts 1
unset SASGUARD_API_KEY
```

The default model is `gpt-6-luna`, with medium reasoning and at most 8,192 output tokens
per request. Use `--model` to select an exact model ID supported by the same API.
Invoking the command authorizes transmission of the reviewed payload and the requested
number of attempts. It does not infer authorization from the preview's pending fields.

By default there is one request and no repair. `--repair-attempts 1` permits at most
two requests total; the maximum allowed repair count is two. Provider errors and
incomplete or invalid responses stop without retrying. Usage is recorded as returned
by the provider. This command does not estimate price or enforce a dollar budget.

## What repair can see

The initial candidate is always retained as Attempt 0. A repair receives the preceding
code, the original prompt, and an automatically constructed aggregate diagnostic. The
diagnostic includes comparison counts, expected column names, missing column names,
and filenames with structural errors. It excludes provider IDs, raw reference values,
stdout, stderr, and exception text. Validator, hash, policy, and runner infrastructure
failures stop the workflow rather than asking the model to repair them.

This differs from the earlier local repair experiment, which used human-curated
diagnostics and explicit code hints. A passing earlier repair does not prove that this
automatic feedback will produce a passing repair.

Generated code runs only in Docker. The container receives the candidate, its input CSV,
and the runtime contract. It receives no API key, trusted output files, or validator.
Source, input, prompt, and controller hashes are checked between stages. Validation
policies remain fixed for the experiment. Changing the model's code manually creates a
different candidate and cannot retain the original generation attribution.

## Read the evidence and report

Each invocation creates a new ignored directory under `reports/runs/program0-model-*`:

```text
workflow.json
summary.md
attempt-0/
  attempt.json
  request.json
  response.json
  candidate.py
  repair-diagnostics.json     # Present when preparing an additional attempt
attempt-1/                   # Present only when a repair was requested and needed
```

Each attempt records generation, Docker execution, output collection, and SAS comparison
separately. It links the execution report and its hash. Repair records also link the
preceding attempt's hash. No files from an earlier experiment are overwritten.

Exit status is zero only when an attempt passes all three comparisons. Status 1 means
the recorded experiment failed or encountered an error. Status 2 means it could not
start, such as a missing credential or a changed preview.

Create the existing Abt technical summary and internal client handoff draft using the
workflow directory printed by the command:

```text
python -m sasguard.cli report-run reports/runs/PROGRAM0-MODEL
```

The report checks the model response, candidate bytes, and execution evidence before
identifying the code as model-generated. It records the model and repair count. A changed
generation record prevents a verified report. Generation failures without execution are
described in `workflow.json` and `summary.md` rather than an execution handoff.

These are local reproducibility records, not signed provider attestations. Human review
and client release approval remain unrecorded. A Program 0 pass does not establish
Program 1, Program 2, eligibility, clustering, or final CMS rating correctness.

The request format follows the provider's
[structured output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
