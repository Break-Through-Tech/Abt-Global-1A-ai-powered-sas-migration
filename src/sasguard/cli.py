"""Command-line entry point for SASGuard."""

import typer

from sasguard import __version__

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


if __name__ == "__main__":  # pragma: no cover
    app()
