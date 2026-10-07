"""Trusted environment metadata collected before generated code executes."""

import platform
import re
from importlib.metadata import distributions

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PythonEnvironment(BaseModel):
    """Interpreter, platform, and installed distribution versions without host paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    operating_system: str = Field(min_length=1)
    architecture: str = Field(min_length=1)
    packages: dict[str, str] = Field(min_length=1)

    @field_validator("packages")
    @classmethod
    def normalize_packages(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for name, version in values.items():
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is None:
                raise ValueError("distribution names must be valid package names")
            if not version or version != version.strip():
                raise ValueError("distribution versions must not be blank or padded")
            canonical = re.sub(r"[-_.]+", "-", name).lower()
            if canonical in normalized:
                raise ValueError("distribution names must be unique after normalization")
            normalized[canonical] = version
        return dict(sorted(normalized.items()))


class DockerImageIdentity(BaseModel):
    """Validated image identity supplied by the trusted Docker daemon."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_image: str = Field(min_length=1)
    image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    repo_digests: list[str] = Field(default_factory=list)
    operating_system: str = Field(min_length=1)
    architecture: str = Field(min_length=1)

    @field_validator("repo_digests")
    @classmethod
    def validate_repo_digests(cls, values: list[str]) -> list[str]:
        if any(re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", value) is None for value in values):
            raise ValueError("repository digests must include a SHA-256 digest")
        if len(values) != len(set(values)):
            raise ValueError("repository digests must be unique")
        return sorted(values)


class DockerRuntimeEnvironment(DockerImageIdentity):
    """Local immutable image identity and its Python environment."""

    python: PythonEnvironment


def collect_python_environment() -> PythonEnvironment:
    """Collect only interpreter, platform, and package versions, never credentials."""
    return PythonEnvironment(
        python_version=platform.python_version(),
        operating_system=platform.system(),
        architecture=platform.machine(),
        packages={
            distribution.metadata["Name"]: distribution.version for distribution in distributions()
        },
    )


# Runs with no repository mounts and with the image entry point overridden. The
# metadata comes from the trusted image, not from a generated program's output.
PYTHON_ENVIRONMENT_PROBE = """\
import json
import platform
from importlib.metadata import distributions
print(json.dumps({
    'python_version': platform.python_version(),
    'operating_system': platform.system(),
    'architecture': platform.machine(),
    'packages': {d.metadata['Name']: d.version for d in distributions()},
}, sort_keys=True))
"""
