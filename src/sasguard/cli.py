"""Command-line entry point for SASGuard."""

from pathlib import Path
from typing import Annotated

import pyreadstat
import typer

from sasguard import __version__
from sasguard.config import load_project_configuration
from sasguard.execution.program0 import (
    CandidateInputFormat,
    run_program0_candidate,
    validate_collected_program0,
)
from sasguard.execution.runner import RunnerLimits
from sasguard.program0 import translate_program0
from sasguard.prototypes.local_model import run_local_model_smoke, run_local_model_suite
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


@app.command("run-program0")
def run_program0(
    project_root: Annotated[
        Path,
        typer.Option(help="Repository root containing the supplied Program 0 input."),
    ] = Path("."),
    output_directory: Annotated[
        Path,
        typer.Option(help="Output directory under reports/runs in the repository."),
    ] = Path("reports/runs/program0"),
) -> None:
    """Write the three Program 0 Python outputs without reading reference values."""
    root = project_root.resolve()
    runs_root = (root / "reports" / "runs").resolve()
    data_root = (root / "data").resolve()
    destination = output_directory if output_directory.is_absolute() else root / output_directory
    destination = destination.resolve()
    if (
        destination == runs_root
        or not destination.is_relative_to(runs_root)
        or not runs_root.is_relative_to(root)
        or runs_root.is_relative_to(data_root)
        or destination.is_relative_to(data_root)
    ):
        typer.echo("Program 0 output must be in a subdirectory of reports/runs.", err=True)
        raise typer.Exit(code=2)

    output_names = (
        "less100_measure.csv",
        "measure_average_stddev_2025jul.csv",
        "std_data_2025jul_analysis.csv",
    )
    if any(
        (destination / name).exists() or (destination / name).is_symlink() for name in output_names
    ):
        typer.echo("Program 0 output already exists; choose a new output directory.", err=True)
        raise typer.Exit(code=2)

    try:
        configuration = load_project_configuration(
            root / "configs" / "cms_2025jul.yaml", project_root=root
        )
        paths = configuration.resolve_paths(root)
        source, _ = pyreadstat.read_sas7bdat(paths.input_sas7bdat)
        result = translate_program0(source)
        destination.mkdir(parents=True, exist_ok=True)
        for name, frame in zip(
            output_names,
            (result.excluded_measures, result.raw_statistics, result.analysis),
            strict=True,
        ):
            frame.to_csv(destination / name, index=False, float_format="%.17g")
    except (OSError, ValueError) as error:
        typer.echo(f"Program 0 run failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(
        f"Program 0 wrote three outputs for {len(result.analysis)} hospitals to {destination}."
    )


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


@app.command("run-program0-candidate")
def run_program0_candidate_command(
    candidate: Annotated[Path, typer.Argument(help="Standalone generated Python entry point.")],
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    image: Annotated[str, typer.Option(help="Existing isolated Docker runner image.")] = (
        "sasguard-runner:local"
    ),
    timeout_seconds: Annotated[
        float, typer.Option(min=0.01, max=600, help="Generated-code execution timeout.")
    ] = 60,
    validate: Annotated[
        bool, typer.Option("--validate", help="Compare collected outputs with SAS on the host.")
    ] = False,
    input_format: Annotated[
        CandidateInputFormat,
        typer.Option(help="Supplied input source; sas7bdat stages a full-precision CSV."),
    ] = CandidateInputFormat.CSV,
) -> None:
    """Execute a Program 0 candidate and collect CSVs for separate host validation."""
    try:
        result, report = run_program0_candidate(
            project_root,
            candidate,
            image=image,
            limits=RunnerLimits(timeout_seconds=timeout_seconds),
            validator=validate_collected_program0 if validate else None,
            input_format=input_format,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"Program 0 candidate could not start: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Program 0 candidate: {result.status}. Report: {report}")
    if result.validation_status == "not_run":
        typer.echo("SAS comparison: not run.")
    else:
        typer.echo(f"SAS comparison: {result.validation_status}.")
    if validate:
        typer.echo("Scope: Program 0 only. Full pipeline and CMS ratings are not verified.")
    if not result.ready_for_validation or (validate and result.validation_status != "passed"):
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
        typer.Option(help="double-score, missing-comparison, sum-missing, or grouped-mean."),
    ] = "double-score",
) -> None:
    """Test one local model on synthetic SAS, with Docker execution and host validation."""
    try:
        passed, report = run_local_model_smoke(project_root, model=model, image=image, case=case)
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
) -> None:
    """Run all synthetic cases once per local model and save a comparison index."""
    try:
        passed, report = run_local_model_suite(
            project_root, models=tuple(models or ["qwen3:4b"]), image=image
        )
    except (OSError, ValueError) as error:
        typer.echo(f"Local model suite could not start: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Synthetic local model suite {'passed' if passed else 'failed'}. Report: {report}")
    if not passed:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
