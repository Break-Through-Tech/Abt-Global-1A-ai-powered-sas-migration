# Local model comparison, October 18, 2026

Qwen3.5 9B passed one of four synthetic cases. Qwen3 4B passed none.
Both ran locally on the Windows evaluation machine. These results cover one frozen request
per case and model, with no repairs. They do not establish SAS-runtime or Program 0 parity.

## Protocol

The machine had an NVIDIA RTX 4070 Laptop GPU with 8 GiB VRAM and about 32 GiB RAM.
Ollama was updated from 0.12.6 to 0.40.6. The official Windows installer matched the release
SHA-256 and had a valid Ollama Inc. signature. Both downloaded models remain installed.

Each model received the same synthetic SAS, runtime contract, output schema, and explicit
settings: temperature 0, seed 42, context 4,096, maximum output 1,200 tokens, and thinking
disabled. For each case, the saved requests were identical after removing the model name.
Other model package defaults are captured in each model definition in the run reports.
No supplied project files, input rows, expected output values, or reference Python entered
the prompts. Expected results were handwritten from the documented SAS behavior in
[Test a local model](local-model-smoke.md).

The controller preserved the candidates, compiled them without executing them on the host,
and ran candidates that compiled in Docker. The host then applied the unchanged comparison
policy. One earlier 4B suite was a separate pilot and also passed zero of four cases; it is
retained separately. The table below uses the final comparison containing both models.

## Results

| Case | `qwen3:4b` | `qwen3.5:9b-q4_K_M` |
|---|---|---|
| Double scores | Ran, but converted `NA` and `NULL` identifiers to missing values. | Failed during execution: treated a scalar float as if it had a `.name` attribute. |
| Missing numeric comparison | Failed during execution because `os` was not imported. | Ran, but lost `NA` and `NULL` identifiers. |
| Arithmetic addition and `SUM` | Failed during execution because `os` was not imported. | Ran, but lost `NA` and `NULL` identifiers. |
| Grouped count and mean | Invalid Python syntax; execution did not start. | Passed all three output rows, including the group with only missing scores. |

Source inspection also found that the 9B missing-comparison candidate used pandas' usual
`NaN < 0` behavior, and its `SUM` candidate treated the SAS function as ordinary addition.
The validator stopped at missing comparison keys for those two candidates, so no numerical
comparison was reported for them. The original candidates remain unedited.

## Memory and observed timing

| Measurement | Qwen3 4B | Qwen3.5 9B |
|---|---:|---:|
| Ollama model allocation in VRAM | 2.96 GiB | 5.08 GiB |
| Layers offloaded to GPU | 37 of 37 | 32 of 33 |
| First request, including load | 15.46 s | 60.91 s |
| Load portion of first request | 12.68 s | 41.68 s |
| Subsequent request totals | 2.45 to 7.98 s | 8.66 to 10.41 s |

VRAM figures come from Ollama's model allocation report and exclude some driver and compute
overhead. The 9B model used some memory outside VRAM. Both requests used a context of 4,096.
These are observed timings, including unsuccessful candidates, rather than a speed benchmark.
The 4B pilot had already initialized its GPU kernels before the final comparison.

## Reproduce and audit

With both model tags installed, run this from the host Python environment:

```text
python -m sasguard.cli local-model-suite --model qwen3:4b --model qwen3.5:9b-q4_K_M
```

The final local index is
`reports/runs/local-model-suite-9b3e827f-d3de-4b85-8b63-01704686dcc5/report.json`.
It points to the eight retained attempt folders. Reports include requests, raw responses,
candidate hashes, model definitions, memory allocation, execution results, and comparisons.
Local run artifacts are ignored by Git; this document records the measured summary.

The exact model digests were:

* `qwen3:4b`: `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`
* `qwen3.5:9b-q4_K_M`: `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`

All eight attempts used controller SHA-256
`f12154861e314672910f3700139d69467e231589123b7f2ba6cb2bdceb9a1397`.
The seven candidates that reached Docker used the same image:
`sha256:c6660736e7e9aeea0b669634aa34e378fd1ca25cd6e0ddae7a3dc2b723133234`.

These observations support continuing local evaluation. They do not support choosing either
model as the team default yet. A coding-specific candidate or a separately recorded experiment
with SAS compatibility helpers would be a useful next comparison. Preserve this direct baseline
when testing those changes.
