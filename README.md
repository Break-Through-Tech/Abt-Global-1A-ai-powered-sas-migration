# SASGuard

SASGuard is a verification-guided, AI-assisted system for migrating legacy SAS analytics
pipelines to Python. The project is being developed for the Break Through Tech AI Studio Fall
2026 program in partnership with Abt Global.

Our primary case study is the CMS July 2025 Overall Hospital Quality Star Rating pipeline. The
supplied project includes SAS programs, input datasets, logs, and trusted SAS output artifacts.

## Why SASGuard

Producing Python code that runs is not enough to establish a correct migration. SASGuard treats
the existing SAS outputs as trusted reference behavior. Generated Python must be executed and
compared against those artifacts using deterministic validation software.

The planned workflow is:

```text
SAS source
    -> translation
    -> generated Python
    -> isolated execution
    -> deterministic validation
    -> first-divergence diagnosis
    -> constrained repair
    -> verification report
```

AI components perform translation and diagnostic reasoning. Ordinary software controls
execution, artifact comparison, and pass or fail decisions.

## Current status

The project is in the Data Exploration and Setup milestone. Current work focuses on:

- a reproducible Docker and VS Code development environment;
- a maintainable Python package and automated quality checks;
- inventorying the supplied SAS and data artifacts;
- documenting the three SAS processing stages;
- implementing trusted data loading and initial comparison utilities;
- protecting supplied artifacts and recording reproducible run metadata.

No end-to-end parity result is claimed at this stage.

## Team

| Name | GitHub | Initial milestone focus |
|---|---|---|
| Tony Mapeke | [@TonyMapeke](https://github.com/TonyMapeke) | Artifact inventory and regression facts |
| Vasco Hinostroza | [@theocsav](https://github.com/theocsav) | Development environment, project structure, and CI |
| Amiri Hayes | [@AmiriHayes](https://github.com/AmiriHayes) | Program 0 analysis and translation prototype |
| Keira Wong | [@keiraw777](https://github.com/keiraw777) | Program 1 analysis and translation prototype |
| Hailey Muñiz | [@haileybella](https://github.com/haileybella) | Program 2 analysis and contributor documentation |
| Loana-Ardi Igabaneza | [@Loaardi](https://github.com/Loaardi) | Data loaders and artifact comparison |

## Repository structure

```text
.
|-- data/                  Supplied input, SAS source, and trusted outputs
|-- configs/               Protected-artifact and pipeline configuration
|-- docs/                  Development and team workflow documentation
|-- notebooks/             Exploratory notebooks
|-- src/sasguard/          Installable Python package
|-- tests/                 Automated tests
|-- .devcontainer/         VS Code Dev Container configuration
|-- .github/workflows/     Continuous integration
|-- Dockerfile             Canonical development image
|-- compose.yaml           Local container workflow
`-- pyproject.toml         Dependencies and development-tool configuration
```

## Run with Docker

### Prerequisites

- Git
- Docker Desktop, or Docker Engine with Docker Compose

### Windows PowerShell

```powershell
git clone https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration.git
Set-Location .\Abt-Global-1A-ai-powered-sas-migration
docker compose build
docker compose run --rm sasguard sasguard verify-integrity
docker compose run --rm sasguard pytest
docker compose run --rm sasguard sasguard version
```

### macOS zsh

```zsh
git clone https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration.git
cd Abt-Global-1A-ai-powered-sas-migration
docker compose build
docker compose run --rm sasguard sasguard verify-integrity
docker compose run --rm sasguard pytest
docker compose run --rm sasguard sasguard version
```

The expected CLI version is currently `0.1.0`.

### Start JupyterLab

The following one-line command works in PowerShell and zsh:

```bash
docker compose run --rm --service-ports sasguard jupyter lab --ip=0.0.0.0 --no-browser
```

Open the tokenized URL shown in the terminal. The repository is mounted at `/workspace`, and the
supplied `data/` directory is mounted read-only inside the container.

See [Development setup](docs/development-setup.md) for VS Code Dev Containers, optional local
Python environments, and troubleshooting.

## Team workflow

- Read [Contributing](CONTRIBUTING.md) before creating a branch or pull request.
- Read [Issues and project board](docs/issues-and-project-board.md) before starting an issue.
- Track work on the [Abt-Global-1A Project Board](https://github.com/orgs/Break-Through-Tech/projects/58).
- View the repository's [GitHub issues](https://github.com/Break-Through-Tech/Abt-Global-1A-ai-powered-sas-migration/issues).

## Data integrity

Supplied SAS programs, input data, and trusted output artifacts are source-of-truth materials.
Contributors must not modify them to make generated results pass. Comparisons must align records
by `PROVIDER_ID`, preserve missing values, and explain numerical tolerances.

Run `docker compose run --rm sasguard sasguard verify-integrity` before requesting review. The
check validates all supplied artifacts against a version-controlled SHA-256 manifest. See
[Protected artifact integrity](docs/data-integrity.md) for the trust boundary and update policy.

SASGuard also provides versioned models for machine-readable artifact comparisons and run
provenance. See [Reproducible run manifests](docs/run-manifests.md) for the schema and usage.

## License

The project license has not yet been selected. The team will confirm an appropriate license with
the Challenge Advisor before publishing one.
