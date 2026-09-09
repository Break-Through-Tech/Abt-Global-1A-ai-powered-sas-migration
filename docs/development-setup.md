# Development setup

Docker is the canonical development environment for SASGuard. It provides one Python and
dependency environment across Windows, macOS, VS Code, and continuous integration.

## Windows with PowerShell

### Prerequisites

1. Install Git.
2. Install Docker Desktop and enable its WSL 2 backend.
3. Start Docker Desktop and wait until the engine reports that it is running.
4. Optionally install VS Code and the Dev Containers extension.

Open a new PowerShell window after installing Docker, then verify the installation:

```powershell
docker version
docker compose version
```

Clone and enter the repository:

```powershell
git clone https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration.git
Set-Location .\Abt-Global-1A-ai-powered-sas-migration
```

Build and verify the environment:

```powershell
docker compose build
docker compose run --rm sasguard sasguard version
docker compose run --rm sasguard ruff check .
docker compose run --rm sasguard ruff format --check .
docker compose run --rm sasguard mypy
docker compose run --rm sasguard pytest
```

## macOS with zsh

### Prerequisites

1. Install Git or the Xcode Command Line Tools.
2. Install Docker Desktop for the correct Apple Silicon or Intel architecture.
3. Start Docker Desktop and wait until the engine reports that it is running.
4. Optionally install VS Code and the Dev Containers extension.

Open a new terminal and verify the installation:

```zsh
docker version
docker compose version
```

Clone and enter the repository:

```zsh
git clone https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration.git
cd Abt-Global-1A-ai-powered-sas-migration
```

Build and verify the environment:

```zsh
docker compose build
docker compose run --rm sasguard sasguard version
docker compose run --rm sasguard ruff check .
docker compose run --rm sasguard ruff format --check .
docker compose run --rm sasguard mypy
docker compose run --rm sasguard pytest
```

## Start JupyterLab

This command works in PowerShell and zsh:

```bash
docker compose run --rm --service-ports sasguard jupyter lab --ip=0.0.0.0 --no-browser
```

Open the tokenized URL printed in the terminal. Port `8888` is published to the host. Stop
JupyterLab with `Ctrl+C`.

If port `8888` is already in use, stop the other process or change the host side of the port in
`compose.yaml`, for example from `8888:8888` to `8889:8888`.

## VS Code Dev Container

1. Open the cloned repository in VS Code.
2. Open the command palette.
3. Select **Dev Containers: Reopen in Container**.
4. Wait for the image build to complete.
5. Open a VS Code terminal and run `pytest`.

The container includes Python, Pylance, Ruff, and Jupyter extensions. It runs as the non-root
`sasguard` user.

## Container data protection

The repository is mounted at `/workspace`. The supplied `data/` directory is overlaid as a
read-only mount at `/workspace/data`. Code should write generated artifacts to a separate output
directory, never into supplied input or reference directories.

## Optional local Python environment

Docker remains the required verification environment. A local Python 3.11 environment may be
used for editor integration or quick development.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pytest
```

### macOS zsh

```zsh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pytest
```

## Common Docker commands

```bash
docker compose build
docker compose run --rm sasguard bash
docker compose run --rm sasguard pytest
docker compose down
```

Rebuild after changing project dependencies:

```bash
docker compose build --no-cache
```

## Troubleshooting

### The `docker` command is not found

Close and reopen PowerShell or the macOS terminal after installing Docker. If the problem remains,
confirm that Docker Desktop finished installing and that its command-line tools are on `PATH`.

### The Docker daemon is not responding

Open Docker Desktop and wait for the engine to finish starting. Then run `docker version`. A client
version without a server version means the engine is not ready.

### Dependencies appear out of date

Run `docker compose build --no-cache`, then rerun the checks. Do not install packages manually in a
running project container without adding them to `pyproject.toml`.

### A test cannot write inside `data/`

This is expected. The supplied data is intentionally mounted read-only. Update the code to write
temporary or generated output somewhere outside `/workspace/data`.
