# Development setup

Docker is the canonical development environment for SASGuard. It provides the same Python and
dependency versions for Windows, macOS, Linux, VS Code, and continuous integration.

## Prerequisites

- Git
- Docker Desktop or Docker Engine with Docker Compose
- VS Code with the Dev Containers extension, if using the VS Code workflow

## Docker Compose workflow

Build the image:

```bash
docker compose build
```

Run the test and quality checks:

```bash
docker compose run --rm sasguard pytest
docker compose run --rm sasguard ruff check .
docker compose run --rm sasguard ruff format --check .
```

Verify the command-line package:

```bash
docker compose run --rm sasguard sasguard version
```

Start JupyterLab:

```bash
docker compose run --rm --service-ports sasguard \
  jupyter lab --ip=0.0.0.0 --no-browser
```

Open the URL containing the access token printed in the terminal. The repository is mounted at
`/workspace`. The supplied `data/` directory is mounted read-only to prevent accidental changes.

## VS Code Dev Container workflow

1. Open the cloned repository in VS Code.
2. Run **Dev Containers: Reopen in Container** from the command palette.
3. Wait for the image build and dependency installation to finish.
4. Open a terminal in VS Code and run `pytest`.

The container installs the Python, Pylance, Ruff, and Jupyter extensions automatically.

## Optional local Python workflow

Python 3.11 is the supported local version. Create and activate a virtual environment, then run:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pytest
ruff check .
ruff format --check .
```

Local Python is supported for convenience, but all changes should also pass inside Docker before
a pull request is submitted.
