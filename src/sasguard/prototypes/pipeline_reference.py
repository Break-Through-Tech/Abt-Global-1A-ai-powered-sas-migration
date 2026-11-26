"""Produce Program 0 and Program 1 outputs from the human-written Python references.

These run on the host without Docker or models. They read only the supplied hospital input
(Program 0) and the Program 0 CSV that was just written (Program 1); trusted SAS outputs
are read later, and only by the host validator.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pandas as pd
import pyreadstat

from sasguard.config import load_project_configuration
from sasguard.program0 import translate_program0

PROGRAM0_OUTPUT_NAMES = (
    "less100_measure.csv",
    "measure_average_stddev_2025jul.csv",
    "std_data_2025jul_analysis.csv",
)
ANALYSIS = "std_data_2025jul_analysis.csv"
REFERENCE = "reference_python/domain_scoring.py"


def run_human_program0(project_root: Path, output_directory: Path) -> None:
    """Write the three Program 0 outputs from the supplied hospital input."""
    root = project_root.resolve()
    paths = load_project_configuration(
        root / "configs/cms_2025jul.yaml", project_root=root
    ).resolve_paths(root)
    source, _ = pyreadstat.read_sas7bdat(paths.input_sas7bdat)
    result = translate_program0(source)
    output_directory.mkdir(parents=True, exist_ok=True)
    for name, frame in zip(
        PROGRAM0_OUTPUT_NAMES,
        (result.excluded_measures, result.raw_statistics, result.analysis),
        strict=True,
    ):
        frame.to_csv(output_directory / name, index=False, float_format="%.17g")


def run_human_program1(
    project_root: Path, program0_directory: Path, output_directory: Path
) -> None:
    """Score the five domains from the actual Program 0 CSV with the human reference.

    The CSV is read with text provider IDs and round-trip floats so Program 1 consumes
    exactly the numbers that Program 0 wrote.
    """
    root = project_root.resolve()
    namespace = runpy.run_path(str(root / REFERENCE))
    frame = pd.read_csv(
        program0_directory / ANALYSIS, converters={"PROVIDER_ID": str}, float_precision="round_trip"
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    for name, table in namespace["calculate_all_domains"](frame).items():
        table.to_csv(output_directory / f"{name.lower()}.csv", index=False, float_format="%.17g")


PROGRAM2_REFERENCE = "reference_python/program2.py"


def run_human_program2(
    project_root: Path, program0_directory: Path, program1_directory: Path, output_directory: Path
) -> None:
    """Write Program 2 output from the actual Program 0 and Program 1 CSVs.

    Only the Program 1 domain CSVs and the Program 0 analysis CSV are read; trusted SAS
    outputs are never opened here. The implementation is pending teammate review, so
    callers label this stage's source accordingly.
    """
    root = project_root.resolve()
    namespace = runpy.run_path(str(root / PROGRAM2_REFERENCE))
    domains, analysis = namespace["read_inputs"](program1_directory, program0_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    for name, table in namespace["calculate_program2"](domains, analysis).items():
        table.to_csv(output_directory / f"{name.lower()}.csv", index=False, float_format="%.17g")
