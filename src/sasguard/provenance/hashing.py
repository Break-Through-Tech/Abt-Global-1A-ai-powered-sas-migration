"""Deterministic file hashing and portable path normalization."""

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PORTABLE_TEXT_EXTENSIONS = frozenset(
    {
        ".csv",
        ".htm",
        ".html",
        ".json",
        ".log",
        ".md",
        ".py",
        ".sas",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)


def normalize_relative_path(value: str) -> str:
    """Return a portable repository-relative path or reject an unsafe path."""
    candidate = value.replace("\\", "/").strip()
    path = PurePosixPath(candidate)
    if (
        not candidate
        or path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or (path.parts and path.parts[0].endswith(":"))
    ):
        raise ValueError(f"path must be repository-relative: {value!r}")
    return path.as_posix()


def validate_sha256(value: str) -> str:
    """Normalize and validate a hexadecimal SHA-256 digest."""
    digest = value.lower()
    if SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError("SHA-256 values must contain exactly 64 hexadecimal characters")
    return digest


def sha256_file(
    path: Path,
    *,
    chunk_size: int = 1024 * 1024,
    normalize_text: bool | None = None,
) -> str:
    """Hash a file using portable LF normalization for known text formats."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    if normalize_text is None:
        normalize_text = path.suffix.lower() in PORTABLE_TEXT_EXTENSIONS

    digest = hashlib.sha256()
    trailing_carriage_return = b""
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            if normalize_text:
                chunk = trailing_carriage_return + chunk
                trailing_carriage_return = b""
                if chunk.endswith(b"\r"):
                    trailing_carriage_return = b"\r"
                    chunk = chunk[:-1]
                chunk = chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            digest.update(chunk)
    if normalize_text and trailing_carriage_return:
        digest.update(b"\n")
    return digest.hexdigest()


def hash_files(project_root: Path, paths: Iterable[str]) -> dict[str, str]:
    """Hash repository-relative files and return a path-sorted mapping."""
    root = project_root.resolve()
    normalized_paths = sorted({normalize_relative_path(path) for path in paths})
    hashes: dict[str, str] = {}
    for relative_path in normalized_paths:
        absolute_path = (root / Path(relative_path)).resolve()
        if not absolute_path.is_relative_to(root):
            raise ValueError(f"path escapes the project root: {relative_path}")
        if not absolute_path.is_file():
            raise FileNotFoundError(absolute_path)
        hashes[relative_path] = sha256_file(absolute_path)
    return hashes
