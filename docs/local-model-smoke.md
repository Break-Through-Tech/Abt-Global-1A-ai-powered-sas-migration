# Test a local model

This experiment sends a made-up SAS DATA step to a downloaded Ollama model, runs its
Python in the existing isolated Docker runner, and compares the result with a hand-written
oracle. It checks the local connection, the CSV input/output contract, identifiers,
missing-value semantics, and grouped calculations. It does not establish SAS-runtime parity or
complete the Program 0 model baseline in issue #48.

## Setup on macOS and Windows

Install Ollama natively and start its application. Keep the model outside Docker so Ollama
can use the machine's supported GPU. Install the host Python development environment
described in [Development setup](development-setup.md). Python 3.11 or 3.12 is required.
The controller calls `127.0.0.1:11434`; it does not expose Ollama to the network.
The generated-code runner still has no network access.

Check `ollama list` for an installed model. The command below uses `qwen3:4b`, which is
already downloaded on the initial Windows test machine. It does not download a model or
contact a paid API. Use `--model` to select another installed tag.

Build the runner once, or reuse an existing `sasguard-runner:local` image:

```text
docker build -f Dockerfile.runner -t sasguard-runner:local .
```

Run the controller from the repository root on the host, not inside the development container.
The same command works in macOS zsh and Windows PowerShell with the local environment active:

```text
python -m sasguard.cli local-model-smoke --model qwen3:4b
```

Without activating the environment, use `./.venv/bin/python` on macOS or
`.\.venv\Scripts\python.exe` in PowerShell in place of `python`.
Use `--image` if the local runner has a different name.

## Compare models

Run the same frozen cases once per installed model with this command:

```text
python -m sasguard.cli local-model-suite --model qwen3:4b --model qwen3.5:9b-q4_K_M
```

Use a current Ollama release for Qwen3.5. The 9B model was added in
[Ollama 0.17.5](https://github.com/ollama/ollama/releases/tag/v0.17.5).
Download the weights separately with `ollama pull qwen3.5:9b-q4_K_M`.
The Q4_K_M download is about 6.6 GB; working memory use is larger and depends on context.
The test records the native model's memory allocation in `ollama_runtime` for each attempt.

The suite produces a comparison index under `reports/runs/local-model-suite-<UUID>/report.json`.
It retains failed attempts and makes no repairs or retries. It unloads each model after its
cases finish so its allocation does not occupy GPU memory during the next model's tests.
For a comparison across models, run them on the same runtime version and machine.
The response records load time separately from generation time.

See [the October 18 comparison](local-model-comparison.md) for the observed Qwen3 4B and
Qwen3.5 9B results on the Windows evaluation machine.

| Case | Expected behavior |
|---|---|
| `double-score` | Double nonmissing scores, keep missing scores and textual identifiers. |
| `missing-comparison` | A standard missing numeric value satisfies `SCORE < 0` in SAS. |
| `sum-missing` | Arithmetic addition propagates missing values; `SUM` ignores missing arguments but returns missing when both are missing. |
| `grouped-mean` | Count nonmissing scores and average them by group, retaining an all-missing group's count of zero and missing mean. |

The additional expectations follow SAS documentation on
[numeric missing-value order](https://support.sas.com/documentation/cdl/en/lrcon/65287/HTML/default/p0tmoipp0ci6wkn0z27ev47sv0ov.htm),
[SUM](https://support.sas.com/documentation/cdl/en/lefunctionsref/63354/HTML/default/n0zxive1z1ctqin12w06c85jfigd.htm),
and [PROC MEANS missing values](https://support.sas.com/documentation/cdl/en/proc/65145/HTML/default/n026epq8bpz1f9n10oeb7zen7s1e.htm).
Their expected CSVs are handwritten and have not been executed in a SAS runtime.
Special SAS missing values such as `.A` are outside these fixtures.

To run one case separately, add `--case`, for example:

```text
python -m sasguard.cli local-model-smoke --model qwen3:4b --case sum-missing
```

## Optional helper condition

Build a fresh runner before the helper comparison. Older runner images may lack the
canonical CSV loader. This runner-specific build excludes host prototype modules, including
the synthetic expected results. It also excludes the unstaged compatibility module, so only
the helper condition receives it. Do not copy prototype modules into a candidate image.

```text
docker build -f Dockerfile.runner -t sasguard-runner:helpers-v1 .
```

Check the exact image before calling the model. In PowerShell:

```powershell
$env:SASGUARD_RUN_DOCKER_TESTS = "1"
$env:SASGUARD_TEST_RUNNER_IMAGE = "sasguard-runner:helpers-v1"
python -m pytest tests/integration/test_isolated_runner.py::test_staged_sas_helpers_run_in_existing_image -q
```

In macOS zsh:

```zsh
SASGUARD_RUN_DOCKER_TESTS=1 SASGUARD_TEST_RUNNER_IMAGE=sasguard-runner:helpers-v1 python -m pytest tests/integration/test_isolated_runner.py::test_staged_sas_helpers_run_in_existing_image -q
```

Run both conditions on that same image. Add `--with-sas-helpers` for the second condition:

```text
python -m sasguard.cli local-model-suite --image sasguard-runner:helpers-v1 --model qwen3:4b --model qwen3.5:9b-q4_K_M
python -m sasguard.cli local-model-suite --image sasguard-runner:helpers-v1 --model qwen3:4b --model qwen3.5:9b-q4_K_M --with-sas-helpers
```

See [the October 19 helper comparison](local-model-helper-comparison.md) for measured
results, retained failures, and the Boolean/numeric flag comparison limitation.

The current condition is `sas-helpers-v2`. Its CSV reader accepts both `Path` objects and
strings. The earlier `sas-helpers-v1` accepted only `Path` objects; its recorded results remain
separate. Changing helper code requires a new condition version and a new run directory.

The controller appends helper API instructions to the original user prompt and copies
`src/sasguard/compatibility.py` into the read-only candidate source as `sas_helpers.py`.
The candidate may import `read_sas_csv`, `sas_lt`, and `sas_sum`. The first uses our existing
canonical loader; the others implement ordinary numeric missing-value comparison and
multi-argument SUM. They do not implement all SAS semantics. Only the selected textual key
gets protection from CSV missing-value inference. Special missing values are unsupported.

Each report records `condition`, a distinct prompt version, and the staged helper's SHA-256.
The run still uses the same fixtures, generation settings, output contract, and host validator.
The model receives neither fixture rows nor expected results. The helpers do not validate
their own output. Without the flag, the original direct-mode request is unchanged and no
helper file is staged.

This changes both the available functions and the instructions. It cannot distinguish their
individual effects. These four cases already informed the helpers, so they are development
checks rather than held-out evidence of general translation quality. Use new cases and,
when available, SAS-generated reference outputs before drawing broader conclusions.

## Read the result

Every invocation saves a separate directory under `reports/runs/local-model-smoke-<UUID>/`.
These local artifacts are ignored by Git. The directory includes:

* `request.json`, with the full prompt, output schema, and generation settings;
* `response.json`, with the response, token counts, and model timing;
* `source/main.py`, containing the extracted candidate exactly as generated;
* the synthetic source, input CSV, comparison policy, and expected CSV;
* `output/adjusted.csv`, if the candidate produced it;
* `report.json`, with the model digest, Ollama version, file hashes, generation status,
  Docker execution result and image identity, and deterministic comparison.

The model receives the synthetic SAS and runtime contract. It receives no supplied project
files, input rows, expected output values, or human reference Python. Only the generated
source, synthetic input directory, and output directory are mounted in Docker. The host
reads the expected CSV after execution.

A passing report requires a completed structured model response, Python that compiles,
successful Docker execution, exactly one declared output file, and a passing comparison.
The comparison requires exact numeric agreement and strict missingness, with rows aligned by
the case's textual key, `PROVIDER_ID` or `GROUP`. Row-level fixtures include leading zeros and
literal `NA` and `NULL` identifiers. The default `double-score` prompt and options remain unchanged
from the initial experiment.

The policy does not enforce a full output dtype schema. In particular, its inferred exact
comparison accepts Boolean flags as equal to numeric 0/1. A passing report must not be
presented as proof of numeric flag types. A stricter schema check needs its own versioned
evaluation; do not change a recorded experiment's policy after seeing its outcomes.

Exit code 0 means these synthetic checks passed. Exit code 1 means the attempt failed and the
report should be inspected. Exit code 2 means the controller could not start. Failed attempts
are retained; the controller does not edit the candidate or retry it automatically.
`human_review` remains `not_recorded`, including on a passing run.

The request uses temperature 0, seed 42, a 4,096-token context, and a maximum of 1,200 generated
tokens. A fixed seed and model digest do not guarantee identical generations on different
hardware or runtime versions. Preserve the original candidate when comparing machines.
The local chat request allows five minutes for model loading and generation; metadata requests
allow 30 seconds. Cold starts can include GPU kernel initialization, so compare load time and
generation time separately. Model package defaults that are not explicitly overridden remain
recorded in the model definition.

Agree on the model, allowed project payload, and evaluation protocol in #46 before using
supplied SAS for #48. This synthetic smoke experiment does not settle those team decisions.

## Initial Windows attempt

On October 17, 2026, `qwen3:4b` with Q4_K_M quantization and Ollama 0.12.6 generated a
candidate in about 2.66 seconds. Docker executed it successfully in about 1.42 seconds.
The host validator rejected its output because pandas had converted the literal identifiers
`NA` and `NULL` into missing values. Specifying `dtype={'PROVIDER_ID': str}` did not prevent
the default CSV missing-value interpretation. This attempt had no repair or manual code edits.

The model digest was
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
The candidate SHA-256 was
`9044d7fedf557adaa2c949637a61faea65f52cb55d7ad3dc470a5f6cf272e2a8`.
These observations show one failure on this synthetic contract. They do not establish the
model's overall SAS translation accuracy. The test suite reproduces the lost-identifier
failure without calling the model.

API references: [Ollama chat](https://docs.ollama.com/api/chat) and
[installed-model metadata](https://docs.ollama.com/api/tags).
