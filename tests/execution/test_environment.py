"""Tests for normalized host and container environment records."""

import pytest
from pydantic import ValidationError

from sasguard.execution.environment import DockerRuntimeEnvironment, PythonEnvironment


def test_python_environment_normalizes_and_sorts_package_names() -> None:
    environment = PythonEnvironment(
        python_version="3.12.2",
        operating_system="Windows",
        architecture="AMD64",
        packages={"Zed_Package": "2.0", "alpha-package": "1.0"},
    )

    assert list(environment.packages) == ["alpha-package", "zed-package"]


def test_python_environment_rejects_duplicate_normalized_names() -> None:
    with pytest.raises(ValidationError, match="unique"):
        PythonEnvironment(
            python_version="3.12.2",
            operating_system="Windows",
            architecture="AMD64",
            packages={"Example_Pkg": "1.0", "example-pkg": "2.0"},
        )


def test_docker_runtime_environment_validates_image_identity_and_sorts_digests() -> None:
    python = PythonEnvironment(
        python_version="3.11.9",
        operating_system="Linux",
        architecture="x86_64",
        packages={"pip": "24.0"},
    )
    environment = DockerRuntimeEnvironment(
        requested_image="sasguard-runner:test",
        image_id="sha256:" + "a" * 64,
        repo_digests=[
            "example/sasguard@sha256:" + "c" * 64,
            "example/sasguard@sha256:" + "b" * 64,
        ],
        python=python,
        operating_system="Linux",
        architecture="x86_64",
    )

    assert environment.repo_digests == sorted(environment.repo_digests)
    with pytest.raises(ValidationError, match="image"):
        DockerRuntimeEnvironment(
            requested_image="sasguard-runner:test",
            image_id="sha256:tag-is-not-an-id",
            repo_digests=[],
            python=python,
            operating_system="Linux",
            architecture="x86_64",
        )
