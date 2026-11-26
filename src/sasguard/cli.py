"""Command-line entry point for SASGuard."""

import csv
from pathlib import Path
from typing import Annotated
from uuid import uuid4

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
from sasguard.prototypes.local_model_reassessment import reassess_local_model_suite
from sasguard.prototypes.mortality import run_mortality_prototype
from sasguard.prototypes.pipeline_reference import PROGRAM2_REFERENCE
from sasguard.prototypes.pipeline_reference import run_human_program0 as produce_program0
from sasguard.prototypes.pipeline_reference import run_human_program1 as produce_program1
from sasguard.prototypes.pipeline_reference import run_human_program2 as produce_program2
from sasguard.prototypes.program0_model import ModelSettings, run_program0_model
from sasguard.prototypes.program0_prompt import (
    PromptInputFormat,
    check_program0_prompt,
    preview_program0_prompt,
)
from sasguard.prototypes.program01 import run_program01_chain
from sasguard.prototypes.program2_model import run_program2_model
from sasguard.reporting import write_run_report
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.pipeline import (
    StageInput,
    StageSource,
    render_summary,
    validate_pipeline,
)

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


@app.command("model-program0")
def model_program0_command(
    preview_directory: Annotated[Path, typer.Argument(help="Reviewed Program 0 prompt preview.")],
    image: Annotated[str, typer.Option(help="Existing isolated Docker runner image or image ID.")],
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    model: Annotated[
        str, typer.Option(help="Exact model ID for the Responses API.")
    ] = "gpt-6-luna",
    repair_attempts: Annotated[
        int, typer.Option(min=0, max=2, help="Maximum additional aggregate-guided repair calls.")
    ] = 0,
    max_output_tokens: Annotated[int, typer.Option(min=128, max=32768)] = 8192,
    timeout_seconds: Annotated[
        float, typer.Option(min=0.01, max=600, help="Timeout for each Docker execution.")
    ] = 60,
) -> None:
    """Send the source/header payload, then generate, run, and validate Program 0.

    Authorizes at most 1 + repair-attempts requests. The host reads SASGUARD_API_KEY.
    """
    try:
        result, report = run_program0_model(
            project_root,
            preview_directory,
            image=image,
            settings=ModelSettings(
                model=model, repair_attempts=repair_attempts, max_output_tokens=max_output_tokens
            ),
            limits=RunnerLimits(timeout_seconds=timeout_seconds),
        )
    except (OSError, ValueError) as error:
        typer.echo(f"Program 0 model workflow could not start: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Program 0 model workflow: {result.status}. Evidence: {report}")
    for attempt in result.attempts:
        typer.echo(
            f"Attempt {attempt.index}: generation {attempt.generation_status}, "
            f"execution {attempt.execution_status}, SAS comparison {attempt.validation_status}."
        )
    typer.echo("Scope: Program 0 only. Full pipeline and CMS ratings are not verified.")
    if result.status != "passed":
        raise typer.Exit(code=1)


@app.command("run-program01-chain")
def program01_chain_command(
    program0_directory: Annotated[
        Path, typer.Argument(help="Verified Program 0 candidate or model-workflow directory.")
    ],
    image: Annotated[str, typer.Option(help="Existing isolated Docker runner image or image ID.")],
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """Run human-reference Program 1 on verified Python Program 0 output."""
    try:
        result, report = run_program01_chain(project_root, program0_directory, image=image)
    except (OSError, ValueError) as error:
        typer.echo(f"Program 0 to Program 1 chain could not start: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Program 0 to Program 1 chain: {result.status}. Evidence: {report}")
    for name, comparison in result.comparisons.items():
        copied = result.input_passthrough.get(name)
        typer.echo(
            f"{name}: SAS comparison {'passed' if comparison.passed else 'failed'}, "
            f"input passthrough {'passed' if copied and copied.passed else 'failed'}."
        )
    typer.echo("Program 1 is human-reference Python. Full pipeline and ratings are not verified.")
    if result.status != "passed":
        raise typer.Exit(code=1)


REFERENCE_PROGRAM2_NOTE = "Program 2 reference implementation pending teammate review"
REFERENCE_PROGRAM2_REVIEWED_NOTE = "Program 2 reference implementation, teammate review recorded"


@app.command("validate-pipeline")
def validate_pipeline_command(
    program2_output: Annotated[
        Path | None, typer.Option(help="Directory with the actual Program 2 output CSVs.")
    ] = None,
    program2_source: Annotated[
        StageSource | None,
        typer.Option(
            help="Where the Program 2 output came from. Not allowed with "
            "--run-reference-program2, whose origin is fixed as helper_assisted_model_output."
        ),
    ] = None,
    program2_reviewed_by: Annotated[
        str,
        typer.Option(
            help="Teammate who reviewed the Program 2 code. Recorded separately; it does not "
            "change the code origin."
        ),
    ] = "",
    run_reference_program2: Annotated[
        bool,
        typer.Option(
            "--run-reference-program2",
            help="Produce Program 2 output from reference_python/program2.py (pending "
            "teammate review) on the Program 0 and Program 1 outputs.",
        ),
    ] = False,
    run_human_references: Annotated[
        bool,
        typer.Option(
            "--run-human-references",
            help="Produce Program 0 and Program 1 outputs from the human references.",
        ),
    ] = False,
    run_human_program1: Annotated[
        bool,
        typer.Option(
            "--run-human-program1",
            help="Produce Program 1 outputs from the human reference on --program0-output.",
        ),
    ] = False,
    program0_output: Annotated[
        Path | None, typer.Option(help="Directory with the actual Program 0 output CSVs.")
    ] = None,
    program0_source: Annotated[
        StageSource | None, typer.Option(help="Where the Program 0 output came from.")
    ] = None,
    program1_output: Annotated[
        Path | None, typer.Option(help="Directory with the actual Program 1 output CSVs.")
    ] = None,
    program1_source: Annotated[
        StageSource | None, typer.Option(help="Where the Program 1 output came from.")
    ] = None,
    program0_code: Annotated[
        Path | None, typer.Option(help="Candidate source file to hash for Program 0.")
    ] = None,
    program1_code: Annotated[
        Path | None, typer.Option(help="Candidate source file to hash for Program 1.")
    ] = None,
    program2_code: Annotated[
        Path | None, typer.Option(help="Candidate source file to hash for Program 2.")
    ] = None,
    program2_note: Annotated[str, typer.Option(help="Free-text provenance note.")] = "",
    output_directory: Annotated[
        Path | None, typer.Option(help="New directory under reports/runs for the record.")
    ] = None,
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """Validate all ten Program 0, 1 and 2 artifacts on actual chained Python outputs.

    Exits 0 only for PASS (all ten comparisons, both handoffs, integrity). PARTIAL and
    FAIL exit 1 and report the earliest divergence.
    """
    root = project_root.resolve()
    runs = (root / "reports" / "runs").resolve()
    run = (output_directory or runs / f"pipeline-{uuid4()}").resolve()
    if run == runs or not run.is_relative_to(runs) or run.exists():
        typer.echo("Output must be a new subdirectory of reports/runs.", err=True)
        raise typer.Exit(code=2)
    if run_human_references and (program0_output or program1_output or run_human_program1):
        typer.echo("--run-human-references cannot be combined with stage outputs.", err=True)
        raise typer.Exit(code=2)
    if run_human_program1 and program1_output:
        typer.echo("--run-human-program1 cannot be combined with --program1-output.", err=True)
        raise typer.Exit(code=2)
    if run_reference_program2 and program2_output:
        typer.echo("--run-reference-program2 cannot be combined with --program2-output.", err=True)
        raise typer.Exit(code=2)
    if run_reference_program2 and program2_source is not None:
        typer.echo(
            "--run-reference-program2 records its origin as helper_assisted_model_output; "
            "--program2-source cannot change it. Record a teammate review with "
            "--program2-reviewed-by.",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        run.mkdir(parents=True)
        if run_human_references:
            program0_output = run / "program0"
            produce_program0(root, program0_output)
            program0_source = StageSource.HUMAN_REFERENCE
        if run_human_references or run_human_program1:
            if program0_output is None:
                raise ValueError("--run-human-program1 needs --program0-output")
            program1_output = run / "program1"
            produce_program1(root, program0_output, program1_output)
            program1_source = StageSource.HUMAN_REFERENCE
        if program0_output is None or program0_source is None:
            raise ValueError("Program 0 needs --program0-output and --program0-source")
        if program1_output is None or program1_source is None:
            raise ValueError("Program 1 needs --program1-output and --program1-source")
        if run_reference_program2:
            program2_output = run / "program2"
            produce_program2(root, program0_output, program1_output, program2_output)
            program2_source = StageSource.HELPER_ASSISTED_MODEL_OUTPUT
            program2_code = program2_code or root / PROGRAM2_REFERENCE
            if not program2_note:
                program2_note = (
                    REFERENCE_PROGRAM2_REVIEWED_NOTE
                    if program2_reviewed_by.strip()
                    else REFERENCE_PROGRAM2_NOTE
                )
        if program2_output is None or program2_source is None:
            raise ValueError("Program 2 needs --program2-output and --program2-source")
        result = validate_pipeline(
            root,
            StageInput(
                source=program0_source, output_directory=program0_output, code_path=program0_code
            ),
            StageInput(
                source=program1_source, output_directory=program1_output, code_path=program1_code
            ),
            StageInput(
                source=program2_source,
                output_directory=program2_output,
                code_path=program2_code,
                note=program2_note,
                reviewed_by=program2_reviewed_by.strip(),
            ),
        )
    except (OSError, ValueError) as error:
        typer.echo(f"Pipeline validation could not complete: {error}", err=True)
        raise typer.Exit(code=2) from error
    (run / "pipeline-validation.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    summary = render_summary(result)
    (run / "summary.md").write_text(summary, encoding="utf-8")
    typer.echo(summary)
    typer.echo(f"Evidence: {run}")
    if result.status != "PASS":
        raise typer.Exit(code=1)


@app.command("model-program2")
def model_program2_command(
    image: Annotated[str, typer.Option(help="Exact isolated Docker image ID or existing tag.")],
    upstream_chain: Annotated[
        Path | None, typer.Option(help="Verified Program 0 to Program 1 chain directory.")
    ] = None,
    reference_inputs: Annotated[
        bool, typer.Option("--reference-inputs", help="Explicitly use supplied SAS intermediates.")
    ] = False,
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    repair_attempts: Annotated[int, typer.Option(min=0, max=2)] = 2,
) -> None:
    """Translate Program 2 with bounded Luna attempts and fixed host SAS verification."""
    if (upstream_chain is None) == (not reference_inputs):
        typer.echo("Select exactly one of --upstream-chain or --reference-inputs.", err=True)
        raise typer.Exit(code=2)
    try:
        result, path = run_program2_model(
            project_root,
            upstream_chain=upstream_chain,
            image=image,
            settings=ModelSettings(
                max_output_tokens=16384, repair_attempts=repair_attempts, api_timeout_seconds=300
            ),
        )
    except (OSError, ValueError) as error:
        typer.echo(f"Program 2 could not start: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Program 2 model workflow: {result.status}. Evidence: {path}")
    for attempt in result.attempts:
        typer.echo(
            f"Attempt {attempt.index}: generation {attempt.generation_status}, "
            f"execution {attempt.execution_status}, SAS comparison {attempt.validation_status}."
        )
    typer.echo("Scope: July 2025 Program 2. Program 1 uses a human/SAS reference.")
    if result.status != "passed":
        raise typer.Exit(code=1)


@app.command("report-run")
def report_run(
    run_directory: Annotated[Path, typer.Argument(help="Saved run directory inside reports/runs.")],
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    output_directory: Annotated[
        Path | None,
        typer.Option(help="New report directory inside reports/runs; never overwritten."),
    ] = None,
) -> None:
    """Write an internal handoff draft and technical summary from recorded evidence."""
    try:
        destination = write_run_report(
            project_root, run_directory, output_directory=output_directory
        )
    except (OSError, ValueError) as error:
        typer.echo(f"Report could not be generated: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Internal draft generated: {destination}. Review scope and status before sharing.")


@app.command("preview-program0-prompt")
def preview_program0_prompt_command(
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    output_directory: Annotated[
        Path | None, typer.Option(help="New direct child of reports/runs; never overwritten.")
    ] = None,
    input_format: Annotated[
        PromptInputFormat,
        typer.Option(help="Source input for execution; only its column names enter the prompt."),
    ] = PromptInputFormat.CSV,
) -> None:
    """Prepare a local prompt preview without model calls, generation, or execution."""
    try:
        destination = preview_program0_prompt(
            project_root, output_directory=output_directory, input_format=input_format
        )
    except (OSError, ValueError, csv.Error) as error:
        typer.echo(f"Prompt preview could not be prepared: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Local prompt preview: {destination}")
    typer.echo(f"Input source: {input_format.value}.")
    typer.echo("Payload approval and model selection are pending. No model call was made.")


@app.command("check-program0-prompt")
def check_program0_prompt_command(
    preview_directory: Annotated[
        Path, typer.Argument(help="Saved local prompt preview directory.")
    ],
    project_root: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """Check a saved preview without modifying it, approving it, or calling a model."""
    try:
        result = check_program0_prompt(project_root, preview_directory)
    except (OSError, ValueError, csv.Error) as error:
        typer.echo(f"Prompt preview could not be checked: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        f"Prompt preview integrity: {result.status}. Messages SHA-256: {result.messages_sha256}"
    )
    typer.echo("Payload approval remains pending. No model call was made.")
    typer.echo(f"Recorded input source: {result.input_format.value}.")
    for issue in result.issues:
        typer.echo(issue)
    if result.status != "matched":
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
