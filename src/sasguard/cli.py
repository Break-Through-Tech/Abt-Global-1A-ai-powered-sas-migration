"""Command-line entry point for SASGuard."""

from pathlib import Path
from typing import Annotated

import typer

from sasguard import __version__
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


if __name__ == "__main__":  # pragma: no cover
    app()
