# SAS helper experiment, October 19, 2026

This experiment compares direct translation with tested helper functions on the same four
synthetic cases. The expected results are handwritten from SAS documentation, not generated
by a SAS runtime. These checks do not establish Program 0 or full-pipeline correctness.

## Results under the unchanged comparison policy

| Model | Direct control | Helper v1 | Helper v2 |
|---|---:|---:|---:|
| `qwen3:4b` | 0 of 4 | 2 of 4 | 2 of 4 |
| `qwen3.5:9b-q4_K_M` | 1 of 4 | 0 of 4 | 3 of 4 |

V2 results by case:

| Case | Qwen3 4B | Qwen3.5 9B |
|---|---|---|
| Double scores | Invalid Python string; execution did not start. | Passed. |
| Missing numeric comparison | Passed under this policy, but wrote Boolean flags. | Passed with numeric flags. |
| Arithmetic addition and SUM | Passed. | Passed. |
| Grouped count and mean | Lost the GROUP column when writing a grouped index. | Ran, but counted all rows instead of nonmissing scores. Two COUNT cells differed. |

The 9B grouped-count failure is a regression from its direct candidate, which passed that
case. Helpers did not make every translation better. The 4B double-score candidate still
contained explanatory text inside an unfinished Python string.

The 4B missing-comparison pass needs a qualification. Its CSV contains `True` and `False`,
not numeric 1 and 0. The policy's inferred exact comparison accepts Python's Boolean/numeric
equality. This pass does not prove the output has SAS-compatible numeric flag types.
The policy was not relaxed or changed after observing these results. A stricter, versioned
numeric output schema should be the next validation step.

## Protocol

Both models ran locally on the same Windows RTX 4070 Laptop machine with Ollama 0.40.6.
The tags and model digests are unchanged from the
[October 18 comparison](local-model-comparison.md). Each condition used one generation per
case and model, with temperature 0, seed 42, context 4,096, maximum output 1,200 tokens,
thinking disabled, and the same JSON output schema. No generated candidate was edited.

The direct requests matched the original eight baseline request files byte-for-byte.
The helper conditions appended the same API guidance and staged a read-only `sas_helpers.py`.
The functions preserve a textual CSV key, implement ordinary numeric missing-value ordering,
and evaluate multi-argument SUM. No fixture rows, expected results, or project data entered
the prompts. Execution stayed in Docker; validation stayed on the host with the original
fixtures and comparison policy.

Both conditions used the immutable Docker image
`sha256:97776ac8035988410d74a0725b45ea5c377dbde7d569c04c384bf192aeeb046a`.
Its Python version was 3.11.16, with pandas 2.3.3. A runner-specific ignore file excludes the
host prototype modules and their expected results from the image build. It also excludes
the unstaged compatibility module, so only the helper condition gets that module.
The Docker integration test checks these exclusions and exercises the staged helper APIs.

## Development failures retained

The first pilot used an older `sasguard-runner:local` image without the shared CSV loader.
It is retained as an invalid environment pilot, not used to score the helper comparison.
The corrected image passed the integration test before the direct and helper runs below.

On that corrected image, helper v1 passed two cases with Qwen3 4B and none with Qwen3.5 9B.
All four 9B candidates passed string paths to `read_sas_csv`, but the helper only accepted
`Path` objects. This was an interface limitation in our helper. V2 accepts both, and has a
separate version, helper hash, and run. The prompt, fixtures, settings, and comparison policy
were not changed for v2. V1 remains in Git at commit `442c209` and in the retained run folders.
All eight v2 requests and generated candidates matched their v1 counterparts byte-for-byte.
The changed helper implementation resolved the path failures without edits to generated code.

These are development cases that already informed the helpers. The experiment changes both
instructions and available functions relative to direct translation, so it does not isolate
their individual effects. Add unseen cases and SAS-generated reference outputs before using
these scores to judge general translation quality or select the team's default model.

## Audit records

All paths below are local, ignored run artifacts under `reports/runs/`. The index files point
to each attempt's request, raw response, candidate, execution record, and comparison.

| Run | Index directory |
|---|---|
| Original October 18 direct baseline | `local-model-suite-9b3e827f-d3de-4b85-8b63-01704686dcc5` |
| Invalid old-image helper pilot | `local-model-suite-83269ff9-10a5-4168-9db2-60217410b76e` |
| October 19 direct control | `local-model-suite-916433b5-8419-413b-988e-5112073ae5d9` |
| Helper v1 | `local-model-suite-be38663d-45f8-4fa2-8de8-e06bb9da6ba7` |
| Helper v2 | `local-model-suite-1c01d985-6807-4da6-bf0e-f2ae9e9cd701` |

Append `/report.json` to each directory. The October 19 direct and v1 controller SHA-256 was
`33d4af34701977bb62b4de7f14b664d521deeea5866405a401cfb51d5b2c52d5`.
The v2 controller SHA-256 is
`51c22194f9f3e389fdbf3de7766e53c7c96496eb0892ed002b6584446b8e7b97`.
The helper hashes are:

* V1: `f4499a993a387f400eb4280c72c2e457b2bb207b52c6005b69a10fc95f4e2708`
* V2: `001020083b561159f0722c4b609eeb460d9ad8a243cf9b6f39651cccaf8eaba3`

See [Test a local model](local-model-smoke.md#optional-helper-condition) for the build,
image check, and commands for PowerShell and zsh.
