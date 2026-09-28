# Isolated Generated-Code Runner

SASGuard executes generated Python in a dedicated Docker container with explicit access and
resource boundaries. The runner is intentionally described as an isolated execution runner. It is
not a fully hardened security sandbox and must not be exposed as a multi-tenant execution service.

## Access boundary

The runner receives exactly three host mounts:

| Container path | Purpose | Access |
|---|---|---|
| `/runner/source` | Generated Python | Read-only |
| `/runner/input` | Required input data | Read-only |
| `/runner/output` | Generated artifacts and result JSON | Read-write |

The default input mount is `data/Project_1/Starrating`. Neither `data/Project_1/SAS Output CSV`
nor `data/Project_1/SAS Output` is mounted. The cross-platform scripts reject source, input,
output, or result directories that overlap either trusted golden-output path. The Python
controller applies the same rule to every mounted path for each golden path supplied through
`forbidden_host_paths`.

The generated program receives only these useful environment variables:

```text
SASGUARD_INPUT_DIR=/runner/input
SASGUARD_OUTPUT_DIR=/runner/output
```

The worker constructs the child environment from a fixed allowlist. It does not forward API keys,
`.env` values, credentials, or arbitrary host variables.

## Docker restrictions

Every execution uses:

- no network namespace connectivity;
- a read-only container root filesystem;
- a non-root user;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- no shared IPC namespace;
- 1 CPU, 512 MB memory, 64 processes, and 256 open files by default;
- an internal execution timeout of 60 seconds by default;
- a host-side timeout and forced container cleanup as a fallback.

Generated code can create files only in `/runner/output`. Escaping output symlinks are reported as
policy violations and are not accepted as produced artifacts.

## Run generated code

Place an entry point at `generated/main.py`. It should read and write using the provided
environment variables:

```python
import os
from pathlib import Path

input_directory = Path(os.environ["SASGUARD_INPUT_DIR"])
output_directory = Path(os.environ["SASGUARD_OUTPUT_DIR"])

source = input_directory / "alldata_2025jul.csv"
destination = output_directory / "example.txt"
destination.write_text(f"Input exists: {source.exists()}\n", encoding="utf-8")
```

On Windows PowerShell:

```powershell
.\scripts\run-isolated.ps1
```

To select a different generated entry point or timeout:

```powershell
.\scripts\run-isolated.ps1 -Script program0.py -TimeoutSeconds 120
```

On macOS or Linux with zsh:

```zsh
./scripts/run-isolated.sh
```

To select a different generated entry point or timeout:

```zsh
SASGUARD_TIMEOUT_SECONDS=120 ./scripts/run-isolated.sh program0.py
```

The worker returns its result through the container's captured standard output. The trusted host
script writes that result to `reports/runner-results/execution-result.json` only after the
container has stopped. The result directory is separate from the writable artifact mount, so
generated code cannot see or alter the execution record. Both local report directories are ignored
by Git.

## Machine-readable result

The result records:

- a unique execution ID;
- status: `succeeded`, `failed`, `timed_out`, `policy_violation`, or `runner_error`;
- generated-process exit code when one exists;
- runtime in seconds;
- captured standard output and standard error;
- repository-relative produced output paths;
- detected output-policy violations.

`ExecutionResult` can be attached to a versioned `RunManifest` through
`RunManifest.with_execution_result()`.

## Verification

Unit tests run with the normal suite. Docker boundary tests require a built runner image and an
explicit opt-in:

```zsh
docker build --file Dockerfile.runner --tag sasguard-runner:test .
SASGUARD_RUN_DOCKER_TESTS=1 pytest -m docker_integration
```

GitHub Actions runs these integration tests in a separate job. They verify successful execution,
network denial, missing golden mounts, read-only source/input/root paths, secret isolation,
captured failures, timeout termination, and escaping-symlink detection.

## Limitations

- Docker isolation reduces risk but is not a formal security proof.
- Resource enforcement depends on the Docker engine and host platform.
- Captured output shares the container memory limit; intentionally excessive output can make a run
  fail before a structured result is written.
- The runner does not validate analytical correctness. Deterministic artifact comparison remains a
  separate step.
- Only trusted team members should control runner images, Docker settings, and host mount paths.
