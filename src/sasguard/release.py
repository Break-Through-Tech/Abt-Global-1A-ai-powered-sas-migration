"""Release-specific names for a CMS star-rating release.

A release is identified by a lowercase tag such as ``2025jul``. Everything that carries the
tag in its name (artifacts, output filenames, the input file) is derived here from a
release-neutral role, so a new release needs configuration and data files, not code edits.
Comparison policies are keyed by role: an artifact of any release uses the policy entry of the
same role in the committed policy files, which are written for July 2025.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

DEFAULT_TAG = "2025jul"
DEFAULT_CONFIG_PATH = "configs/cms_2025jul.yaml"
DEFAULT_INTEGRITY_MANIFEST = "configs/protected-artifacts.json"
TAG_PATTERN = re.compile(r"^[a-z0-9]+$")

# Role -> artifact name template. ``{TAG}`` is the upper-case release tag.
ROLE_TEMPLATES: dict[str, str] = {
    "LESS100_MEASURE": "LESS100_MEASURE",
    "MEASURE_AVERAGE_STDDEV": "MEASURE_AVERAGE_STDDEV_{TAG}",
    "STD_DATA_ANALYSIS": "STD_DATA_{TAG}_ANALYSIS",
    "OUTCOME_MORTALITY": "OUTCOME_MORTALITY",
    "OUTCOME_READMISSION": "OUTCOME_READMISSION",
    "OUTCOME_SAFETY": "OUTCOME_SAFETY",
    "PTEXP": "PTEXP",
    "PROCESS": "PROCESS",
    "STAR": "STAR_{TAG}",
    "NATIONAL_AVERAGE": "NATIONAL_AVERAGE_{TAG}",
}
PROGRAM0_ROLES = ("LESS100_MEASURE", "MEASURE_AVERAGE_STDDEV", "STD_DATA_ANALYSIS")
PROGRAM2_ROLES = ("STAR", "NATIONAL_AVERAGE")

T = TypeVar("T")


def validate_tag(tag: str) -> str:
    """Return ``tag`` if it is lowercase alphanumeric, else raise ``ValueError``."""
    if TAG_PATTERN.fullmatch(tag) is None:
        raise ValueError(f"release tag must be lowercase letters and digits: {tag!r}")
    return tag


@dataclass(frozen=True, slots=True)
class Release:
    """The release tag plus the project files that define it."""

    tag: str = DEFAULT_TAG
    integrity_manifest: str = DEFAULT_INTEGRITY_MANIFEST
    config_path: str = DEFAULT_CONFIG_PATH

    def __post_init__(self) -> None:
        validate_tag(self.tag)

    @property
    def label(self) -> str:
        """Human-readable name: ``July 2025`` for the default, else the upper-case tag."""
        if self.tag == DEFAULT_TAG:
            return "July 2025"
        return self.tag.upper()

    def artifact(self, role: str) -> str:
        """Artifact name for ``role``, e.g. ``STAR`` -> ``STAR_2025JUL``."""
        return ROLE_TEMPLATES[role].format(TAG=self.tag.upper())

    def filename(self, role: str) -> str:
        """Output CSV filename for ``role``, e.g. ``STAR`` -> ``star_2025jul.csv``."""
        return f"{self.artifact(role).lower()}.csv"

    @property
    def input_filename(self) -> str:
        """Name of the hospital input CSV, e.g. ``alldata_2025jul.csv``."""
        return f"alldata_{self.tag}.csv"

    @property
    def analysis_filename(self) -> str:
        return self.filename("STD_DATA_ANALYSIS")

    @property
    def star_filename(self) -> str:
        return self.filename("STAR")

    @property
    def program0_artifacts(self) -> dict[str, str]:
        """Program 0 output filename -> artifact name."""
        return {self.filename(role): self.artifact(role) for role in PROGRAM0_ROLES}

    @property
    def program2_artifacts(self) -> dict[str, str]:
        """Program 2 output filename -> artifact name."""
        return {self.filename(role): self.artifact(role) for role in PROGRAM2_ROLES}

    @property
    def artifact_names(self) -> frozenset[str]:
        return frozenset(self.artifact(role) for role in ROLE_TEMPLATES)

    def role_of(self, artifact: str) -> str:
        """The role an artifact name of this release plays; ``KeyError`` if it is not one."""
        for role in ROLE_TEMPLATES:
            if self.artifact(role) == artifact:
                return role
        raise KeyError(f"{artifact} is not an artifact of release {self.tag}")

    def policies_by_release_artifact(self, policies: Mapping[str, T]) -> dict[str, T]:
        """Re-key July 2025 policy entries to this release's artifact names, by role.

        Only the key changes. Every entry, and so every tolerance, is the committed one.
        """
        return {self.artifact(JULY_2025.role_of(name)): policy for name, policy in policies.items()}


JULY_2025 = Release()
