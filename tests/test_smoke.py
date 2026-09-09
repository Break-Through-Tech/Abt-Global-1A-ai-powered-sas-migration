"""Foundation smoke tests."""

from typer.testing import CliRunner

from sasguard import __version__
from sasguard.cli import app

runner = CliRunner()


def test_package_has_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_reports_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
