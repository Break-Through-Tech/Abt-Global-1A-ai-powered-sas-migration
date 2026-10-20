"""Command-line entry point for SASGuard."""

from pathlib import Path
from typing import Annotated

import typer

from sasguard import __version__
from sasguard.prototypes.local_model import run_local_model_smoke, run_local_model_suite
from sasguard.prototypes.local_model_reassessment import reassess_local_model_suite
from sasguard.prototypes.mortality import run_mortality_prototype
from sasguard.verification.integrity import load_and_verify_integrity

app = typer.Typer(
    name="sasguard",
    help="Verification-guided SAS-to-Python migration tools.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Run SASGuard commands."""


@app.command()
def version() -> None:
    """Print the installed SASGuard version."""
    typer.echo(__version__)


@app.command("verify-integrity")
def verify_integrity(
    project_root: Annotated[
        Path,
        typer.Option(help="Repository root containing the protected paths."),
    ] = Path("."),
    manifest: Annotated[
        Path,
        typer.Option(help="Manifest path, relative to the repository root by default."),
    ] = Path("configs/protected-artifacts.json"),
) -> None:
    """Verify that supplied SAS, input, and reference artifacts are unchanged."""
    root = project_root.resolve()
    manifest_path = manifest if manifest.is_absolute() else root / manifest

    try:
        result = load_and_verify_integrity(root, manifest_path)
    except (OSError, ValueError) as error:
        typer.echo(f"Integrity check could not run: {error}", err=True)
        raise typer.Exit(code=2) from error

    if result.passed:
        typer.echo(f"Integrity check passed: {result.checked_files} protected files verified.")
        return

    typer.echo("Integrity check failed.", err=True)
    for label, paths in (
        ("Missing", result.missing_files),
        ("Modified", result.modified_files),
        ("Unexpected", result.unexpected_files),
    ):
        for path in paths:
            typer.echo(f"{label}: {path}", err=True)
    raise typer.Exit(code=1)


@app.command("mortality-prototype")
def mortality_prototype(
    project_root: Annotated[
        Path,
        typer.Option(help="Repository root containing the Mortality prototype inputs."),
    ] = Path("."),
    image: Annotated[
        str,
        typer.Option(help="Docker image used to run the reference implementation."),
    ] = "sasguard-runner:test",
) -> None:
    """Run the bounded human-reference Mortality comparison."""
    try:
        comparison, report_path = run_mortality_prototype(project_root, image=image)
    except (OSError, ValueError, RuntimeError) as error:
        typer.echo(f"Mortality prototype could not run: {error}", err=True)
        raise typer.Exit(code=2) from error

    scope = "Program 1 Mortality only, supplied Program 0 intermediate"
    if comparison.passed:
        typer.echo(f"Mortality prototype passed. Scope: {scope}. Report: {report_path}")
    else:
        typer.echo(f"Mortality prototype comparison failed. Scope: {scope}. Report: {report_path}")
    typer.echo(
        f"Trace: {report_path.with_name('trace.json')}. Other pipeline outputs are not checked."
    )
    if not comparison.passed:
        raise typer.Exit(code=1)


@app.command("local-model-smoke")
def local_model_smoke(
    project_root: Annotated[
        Path, typer.Option(help="Repository root for local run records.")
    ] = Path("."),
    model: Annotated[str, typer.Option(help="Exact installed Ollama model tag.")] = "qwen3:4b",
    image: Annotated[str, typer.Option(help="Existing isolated Docker runner image.")] = (
        "sasguard-runner:local"
    ),
    case: Annotated[
        str,
        typer.Option(help="Case name within the selected --case-set."),
    ] = "double-score",
    with_sas_helpers: Annotated[
        bool, typer.Option(help="Offer tested SAS helpers in a separate experimental condition.")
    ] = False,
    case_set: Annotated[str, typer.Option(help="development or holdout-v1.")] = "development",
) -> None:
    """Test one local model on synthetic SAS, with Docker execution and host validation."""
    try:
        passed, report = run_local_model_smoke(
            project_root,
            model=model,
            image=image,
            case=case,
            with_sas_helpers=with_sas_helpers,
            case_set=case_set,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"Local model smoke test could not start: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        f"Synthetic local model smoke test {'passed' if passed else 'failed'}. Report: {report}"
    )
    if not passed:
        raise typer.Exit(code=1)


@app.command("local-model-suite")
def local_model_suite(
    project_root: Annotated[
        Path, typer.Option(help="Repository root for local run records.")
    ] = Path("."),
    models: Annotated[
        list[str] | None,
        typer.Option("--model", help="Installed model tag; repeat for comparisons."),
    ] = None,
    image: Annotated[str, typer.Option(help="Existing isolated Docker runner image.")] = (
        "sasguard-runner:local"
    ),
    with_sas_helpers: Annotated[
        bool, typer.Option(help="Offer tested SAS helpers in a separate experimental condition.")
    ] = False,
    case_set: Annotated[str, typer.Option(help="development or holdout-v1.")] = "development",
) -> None:
    """Run all synthetic cases once per local model and save a comparison index."""
    try:
        passed, report = run_local_model_suite(
            project_root,
            models=tuple(models or ["qwen3:4b"]),
            image=image,
            with_sas_helpers=with_sas_helpers,
            case_set=case_set,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"Local model suite could not start: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Synthetic local model suite {'passed' if passed else 'failed'}. Report: {report}")
    if not passed:
        raise typer.Exit(code=1)


@app.command("reassess-local-model-suite")
def reassess_suite(
    suite: Annotated[Path, typer.Argument(help="Saved complete suite inside reports/runs.")],
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """Check saved outputs under the numeric policy without model calls or execution."""
    try:
        passed, report = reassess_local_model_suite(project_root, suite)
    except (OSError, ValueError) as error:
        typer.echo(f"Reassessment could not start: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Saved-output reassessment {'passed' if passed else 'failed'}. Report: {report}")
    if not passed:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
