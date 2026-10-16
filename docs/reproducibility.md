# Reproducing a verified run

The Python execution controller records the exact local Docker image used for a run.
It resolves the requested tag to a `sha256:` image ID before running generated code.
Both the environment probe and the execution use that ID with `--pull never`.
A tag change between these commands cannot select a different image.

The probe runs without repository mounts, network access, or a writable root filesystem.
It reads Python and installed distribution versions from the trusted image before any
generated code runs. The host adds this metadata to `ExecutionResult.runtime_environment`.
It replaces any environment claim in the worker's output. If image inspection or the
probe fails, the controller returns `runner_error` without executing generated code.

## What to keep

A Mortality run saves these records under its unique `reports/runs/mortality-<UUID>/`:

- `manifest.json` records the host controller's Python version, operating system,
  architecture, and installed package versions in `controller_environment`.
- `execution.json` and the manifest's `execution_result` record the requested image,
  immutable local image ID, available repository digests, Docker platform, and container
  Python and package versions in `runtime_environment`.
- `comparison.json` repeats this runner metadata in `runner_environment` alongside
  the artifact hashes and comparison policy.
- `source_hashes` includes `pyproject.toml`, `uv.lock`, `requirements.lock`,
  `requirements-runtime.lock`, `Dockerfile`, and `Dockerfile.runner`.

Environment metadata contains no host filesystem paths, environment variables, credentials,
or data rows. Package names and versions describe the installed environment, not proof
that it matches the current lockfile. Old schema version 1 records without these optional
fields still load, but cannot establish their execution environment.

## Keep the exact image

An image ID identifies a local image, not a registry address. A locally built image may
have no repository digest. Keep an image archive if you need to replay it on another
machine with the same architecture. Keep it outside Git and follow the team's storage
and data-handling rules.

Replace the example ID below with `execution_result.runtime_environment.image_id` from
the saved manifest. Save that ID, not the tag, since the tag might have changed.

On Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force reports/runner-images | Out-Null
$runnerImageId = "sha256:<recorded-64-character-image-id>"
docker image save --output reports/runner-images/runner.tar $runnerImageId
docker image load --input reports/runner-images/runner.tar
sasguard mortality-prototype --image $runnerImageId
```

On macOS with zsh:

```zsh
mkdir -p reports/runner-images
runner_image_id='sha256:<recorded-64-character-image-id>'
docker image save --output reports/runner-images/runner.tar "$runner_image_id"
docker image load --input reports/runner-images/runner.tar
sasguard mortality-prototype --image "$runner_image_id"
```

The controller checks protected inputs and trusted policies for each replay. Keep the
corresponding code revision and input artifacts too. Using the same image does not make
a changed input or policy the same experiment.

## Dependency updates

`uv.lock` records the resolved dependency versions across supported Python versions and
platform markers. `requirements.lock` exports the development, notebook, and build
dependencies for pip. `requirements-runtime.lock` exports runtime dependencies.
The exports include distribution hashes. Do not edit generated lockfiles by hand.
Update `pyproject.toml`, regenerate the lock and exports, and review the dependency diff
before rebuilding. See the [uv export documentation](https://docs.astral.sh/uv/concepts/projects/export/)
for the export format.

The following update commands work in PowerShell and zsh inside an activated local
Python environment. `uv` is pinned to the version required by `pyproject.toml`.

```sh
python -m pip install uv==0.8.22
uv lock
uv export --locked --format requirements-txt --all-extras --all-groups --no-emit-project --output-file requirements.lock
uv export --locked --format requirements-txt --no-dev --no-default-groups --no-emit-project --output-file requirements-runtime.lock
```

`uv lock` keeps existing compatible pins. For an intentional package update, use
`uv lock --upgrade-package <package-name>` instead, then regenerate both exports.
Docker and CI use `--locked` so a stale lockfile causes an error instead of silently
selecting new dependency versions.

## Limits

Pinned Python package versions do not make a rebuild byte-for-byte identical. The Docker
base image still uses the mutable `python:3.11-slim` tag, and OS libraries, Python patch
versions, architecture, and numerical libraries can change. The saved runtime metadata
identifies those differences. Retaining the exact image avoids resolving that base tag
again for a replay on a compatible platform.

The metadata and ID-pinned execution apply to `DockerExecutionRunner` and the Mortality
CLI. The older Compose-based `run-isolated.ps1` and `run-isolated.sh` scripts do not yet
use that controller or attach its environment metadata. They use the locked runner build,
but should not be used to claim an image-identified verification run.

A matching environment is not evidence of analytical correctness. Deterministic artifact
comparison still decides whether the bounded transformation matches the supplied SAS
reference.
